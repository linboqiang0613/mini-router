"""Main router combining all layers."""

from dataclasses import dataclass, field
from typing import Any

import structlog

from mini_router.algorithm.selector import Registry, SelectionMethod
from mini_router.algorithm.types import SelectionContext
from mini_router.client import OpenAIClient
from mini_router.config.config import DecisionAction, RouterConfig, SelectionStrategy
from mini_router.decision.engine import Engine
from mini_router.decision.types import DecisionResult
from mini_router.metrics.latency import LatencyTracker
from mini_router.plugin.cache import Cache, CacheEntry, MemoryCache, SemanticCache
from mini_router.signal_layer.classifier import KeywordClassifier, MLClassifier, UnifiedClassifier
from mini_router.signal_layer.embedder import Embedder, MockEmbedder, OpenAIEmbedder
from mini_router.signal_layer.types import SignalMatches, TaskType

logger = structlog.get_logger()


@dataclass
class RoutingRequest:
    """A routing request."""

    query: str
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingResult:
    """Result of routing."""

    selected_model: str | None = None
    decision_name: str | None = None
    matched_rules: list[str] = field(default_factory=list)
    confidence: float = 1.0
    cache_hit: bool = False
    cache_response: str | None = None
    signals: SignalMatches | None = None
    action: DecisionAction = DecisionAction.ROUTE
    reject_message: str | None = None


class Router:
    """Main router combining signal, decision, algorithm, and plugin layers."""

    def __init__(self, config: RouterConfig) -> None:
        self.config = config
        self._latency_tracker = LatencyTracker()
        self._initialize_components()

    def _initialize_components(self) -> None:
        """Initialize all router components."""
        # Signal layer
        keyword_classifier = KeywordClassifier(self.config.signals.keyword_rules)

        # OpenAI client for ML classifiers and embedder (also used by ChatProxy)
        self._client = OpenAIClient(
            base_url=self.config.models.base_url,
            api_key=self.config.models.api_key,
            timeout=self.config.models.timeout,
        )
        ml_classifier = MLClassifier(self.config.models.classifier, self._client)

        self.classifier = UnifiedClassifier(keyword_classifier, ml_classifier)

        # Embedder
        self.embedder: Embedder
        if self.config.models.embedder and self.config.models.embedder.enabled:
            self.embedder = OpenAIEmbedder(
                config=self.config.models.embedder,
                base_url=self.config.models.base_url,
                api_key=self.config.models.api_key,
                timeout=self.config.models.timeout,
            )
        else:
            self.embedder = MockEmbedder()

        # Decision layer
        self.decision_engine = Engine(
            decisions=self.config.decisions,
            strategy=self.config.selection.strategy.value,
        )

        # Algorithm layer - pass latency tracker to registry
        self.selector_registry = Registry(latency_tracker=self._latency_tracker)

        # Plugin layer - cache
        self.cache: Cache
        if self.config.cache.enabled:
            self.cache = SemanticCache(
                embedder=self.embedder,
                similarity_threshold=self.config.cache.similarity_threshold,
                max_entries=self.config.cache.max_entries,
            )
        else:
            self.cache = MemoryCache(max_entries=self.config.cache.max_entries)

    async def route(self, request: RoutingRequest) -> RoutingResult:
        """
        Route a query through all layers.

        Flow:
        1. Check cache
        2. Extract signals (classify)
        3. Evaluate decisions
        4. Select model
        5. Return result
        """
        # 1. Check cache
        if isinstance(self.cache, SemanticCache):
            cache_entry = await self.cache.get_similar(request.query)
        else:
            cache_entry = self.cache.get(request.query)

        if cache_entry:
            logger.info(
                "cache_hit",
                query=request.query[:50],
                similarity=cache_entry.metadata.get("similarity"),
            )
            return RoutingResult(
                cache_hit=True,
                cache_response=cache_entry.response,
            )

        # 2. Extract signals
        tasks = self._get_classification_tasks()
        signals = await self.classifier.classify(request.query, tasks)

        logger.debug(
            "signals_extracted",
            query=request.query[:50],
            keyword_matches=signals.keyword_rules,
            intent=signals.get_intent_label(),
            has_pii=signals.has_pii(),
            complexity=signals.get_complexity_level(),
        )

        # 3. Evaluate decisions
        decision_result = self.decision_engine.evaluate(signals)

        if decision_result is None:
            logger.warning("no_matching_decision", query=request.query[:50])
            return RoutingResult(
                signals=signals,
                confidence=0.0,
            )

        # Check action
        if decision_result.decision.action == DecisionAction.REJECT:
            logger.info(
                "request_rejected",
                decision=decision_result.decision.name,
                reason=decision_result.decision.reject_message,
            )
            return RoutingResult(
                decision_name=decision_result.decision.name,
                matched_rules=decision_result.matched_rules,
                signals=signals,
                action=DecisionAction.REJECT,
                reject_message=decision_result.decision.reject_message,
            )

        # 4. Select model
        if not decision_result.decision.model_refs:
            logger.warning("no_models_configured", decision=decision_result.decision.name)
            return RoutingResult(
                decision_name=decision_result.decision.name,
                matched_rules=decision_result.matched_rules,
                signals=signals,
                confidence=decision_result.confidence,
            )

        # Get latency-aware configuration
        latency_config = self.config.selection.latency_aware

        selection_context = SelectionContext(
            query=request.query,
            candidate_models=decision_result.decision.model_refs,
            user_id=request.user_id,
            metadata={"decision_name": decision_result.decision.name},
            latency_percentile=latency_config.latency_percentile,
            tpot_percentile=latency_config.tpot_percentile,
            ttft_percentile=latency_config.ttft_percentile,
            min_observations=latency_config.min_observations,
            fallback_to_weight=latency_config.fallback_to_weight,
            weight_blend=latency_config.weight_blend,
        )

        method = self._get_selection_method()
        selection_result = await self.selector_registry.select(method, selection_context)

        logger.info(
            "request_routed",
            query=request.query[:50],
            model=selection_result.selected_model,
            decision=decision_result.decision.name,
            confidence=selection_result.confidence,
        )

        return RoutingResult(
            selected_model=selection_result.selected_model,
            decision_name=decision_result.decision.name,
            matched_rules=decision_result.matched_rules,
            confidence=min(decision_result.confidence, selection_result.confidence),
            signals=signals,
        )

    def _get_classification_tasks(self) -> list[TaskType]:
        """Determine which classification tasks to run."""
        tasks: list[TaskType] = []

        classifier_config = self.config.models.classifier
        if classifier_config.intent and classifier_config.intent.enabled:
            tasks.append(TaskType.INTENT)
        if classifier_config.pii and classifier_config.pii.enabled:
            tasks.append(TaskType.PII)
        if classifier_config.security and classifier_config.security.enabled:
            tasks.append(TaskType.SECURITY)
        if classifier_config.complexity and classifier_config.complexity.enabled:
            tasks.append(TaskType.COMPLEXITY)

        return tasks

    def _get_selection_method(self) -> SelectionMethod:
        """Get the selection method based on configuration."""
        strategy = self.config.selection.strategy
        if strategy == SelectionStrategy.PRIORITY:
            return SelectionMethod.STATIC
        elif strategy == SelectionStrategy.WEIGHTED:
            return SelectionMethod.STATIC
        elif strategy == SelectionStrategy.LATENCY_AWARE:
            return SelectionMethod.LATENCY_AWARE
        else:
            return SelectionMethod.STATIC

    async def set_cache(self, query: str, response: str) -> None:
        """Store a response in cache."""
        if isinstance(self.cache, SemanticCache):
            await self.cache.set(query, response)
        else:
            self.cache.set(query, CacheEntry(query=query, response=response))

    def clear_cache(self) -> None:
        """Clear the cache."""
        self.cache.clear()

    async def record_latency(
        self,
        model: str,
        latency_seconds: float,
        tpot: float | None = None,
        ttft: float | None = None,
    ) -> None:
        """Record latency for a model after response is received.

        Args:
            model: Model name
            latency_seconds: Total latency in seconds
            tpot: Time Per Output Token (optional)
            ttft: Time To First Token (optional)
        """
        await self._latency_tracker.update_latency(model, latency_seconds)
        if tpot is not None:
            await self._latency_tracker.update_tpot(model, tpot)
        if ttft is not None:
            await self._latency_tracker.update_ttft(model, ttft)

        logger.debug(
            "latency_recorded",
            model=model,
            latency=latency_seconds,
            tpot=tpot,
            ttft=ttft,
        )

    async def get_latency_stats(self) -> dict[str, dict[str, Any]]:
        """Get latency statistics for all models."""
        return await self._latency_tracker.get_all_stats()

    async def get_model_latency_stats(self, model: str) -> dict[str, Any] | None:
        """Get latency statistics for a specific model."""
        stats = await self._latency_tracker.get_model_stats(model)
        return stats.to_dict() if stats else None

    @property
    def client(self) -> OpenAIClient:
        """Get the OpenAI client for making API calls."""
        return self._client