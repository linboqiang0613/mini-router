"""Model selection implementations."""

import random
from abc import ABC, abstractmethod

import structlog

from mini_router.algorithm.types import SelectionContext, SelectionResult
from mini_router.config.config import SelectionMethod
from mini_router.metrics.latency import LatencyTracker, get_global_tracker

logger = structlog.get_logger()


class ModelSelector(ABC):
    """Abstract model selector interface."""

    @abstractmethod
    async def select(self, context: SelectionContext) -> SelectionResult:
        """Select a model from candidates."""
        pass


class StaticSelector(ModelSelector):
    """Static weight-based model selector."""

    async def select(self, context: SelectionContext) -> SelectionResult:
        """Select model based on weights."""
        candidates = context.candidate_models
        if not candidates:
            raise ValueError("No candidate models available")

        if len(candidates) == 1:
            return SelectionResult(selected_model=candidates[0].model)

        # Weight-based selection
        total_weight = sum(c.weight for c in candidates)
        if total_weight <= 0:
            # Equal weights if all weights are zero or negative
            return SelectionResult(
                selected_model=random.choice(candidates).model,
                confidence=1.0 / len(candidates),
            )

        # Probabilistic selection based on weights
        r = random.random() * total_weight
        cumulative = 0.0
        for candidate in candidates:
            cumulative += candidate.weight
            if r <= cumulative:
                return SelectionResult(
                    selected_model=candidate.model,
                    confidence=candidate.weight / total_weight,
                )

        # Fallback to last candidate
        return SelectionResult(
            selected_model=candidates[-1].model,
            confidence=candidates[-1].weight / total_weight,
        )


class RoundRobinSelector(ModelSelector):
    """Round-robin model selector."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    async def select(self, context: SelectionContext) -> SelectionResult:
        """Select model in round-robin fashion."""
        candidates = context.candidate_models
        if not candidates:
            raise ValueError("No candidate models available")

        # Use decision name as key for round-robin
        key = context.metadata.get("decision_name", "default")
        if key not in self._counters:
            self._counters[key] = 0

        index = self._counters[key] % len(candidates)
        self._counters[key] += 1

        return SelectionResult(
            selected_model=candidates[index].model,
            confidence=1.0 / len(candidates),
        )


class LatencyAwareSelector(ModelSelector):
    """Latency-aware model selector.

    Selects models based on latency percentiles. Lower latency = higher priority.
    Falls back to weight-based selection if no latency data is available.

    Based on the Go implementation in pkg/selection/latency_aware.go
    """

    def __init__(self, tracker: LatencyTracker | None = None) -> None:
        """Initialize the latency-aware selector.

        Args:
            tracker: Latency tracker instance. If None, uses the global tracker.
        """
        self._tracker = tracker
        self._static_selector = StaticSelector()

    def _get_tracker(self) -> LatencyTracker:
        """Get the latency tracker."""
        if self._tracker is not None:
            return self._tracker
        return get_global_tracker()

    async def select(self, context: SelectionContext) -> SelectionResult:
        """Select model based on latency percentiles.

        Selection algorithm:
        1. Get latency stats for each candidate model
        2. Calculate normalized latency score (lower is better)
        3. Select model with lowest combined score
        4. Fall back to weight-based selection if no latency data
        """
        candidates = context.candidate_models
        if not candidates:
            raise ValueError("No candidate models available")

        if len(candidates) == 1:
            return SelectionResult(selected_model=candidates[0].model)

        tracker = self._get_tracker()

        # Collect latency data for each candidate
        scored_candidates: list[tuple[str, float, float, float]] = []  # (model, latency, tpot, ttft)

        for candidate in candidates:
            latency = await tracker.get_latency_percentile(
                candidate.model, context.latency_percentile
            )
            tpot = await tracker.get_tpot_percentile(
                candidate.model, context.tpot_percentile
            )
            ttft = await tracker.get_ttft_percentile(
                candidate.model, context.ttft_percentile
            )

            if latency is not None:
                scored_candidates.append((candidate.model, latency, tpot or 0.0, ttft or 0.0))

        # If no latency data, fall back to weight-based selection
        if not scored_candidates:
            if context.fallback_to_weight:
                return await self._static_selector.select(context)
            raise ValueError("No latency data available for any candidate model")

        # Calculate normalized scores
        min_latency = min(s[1] for s in scored_candidates)

        # Get min TPOT and TTFT, but only from models that have them
        tpot_values = [s[2] for s in scored_candidates if s[2] > 0]
        ttft_values = [s[3] for s in scored_candidates if s[3] > 0]

        min_tpot = min(tpot_values) if tpot_values else None
        min_ttft = min(ttft_values) if ttft_values else None

        # Score each candidate (lower is better)
        final_scores: list[tuple[str, float]] = []
        for model, latency, tpot, ttft in scored_candidates:
            # Normalize latency score
            latency_score = latency / min_latency if min_latency > 0 else 1.0

            # Add TPOT and TTFT if available
            additional_score = 0.0
            score_parts = 1

            if tpot > 0 and min_tpot is not None and min_tpot > 0:
                additional_score += tpot / min_tpot
                score_parts += 1
            if ttft > 0 and min_ttft is not None and min_ttft > 0:
                additional_score += ttft / min_ttft
                score_parts += 1

            # Combined score (lower is better)
            combined_score = (latency_score + additional_score) / score_parts

            # Blend with weight if configured
            if context.weight_blend > 0:
                # Find the candidate's weight
                weight = 1.0
                for c in candidates:
                    if c.model == model:
                        weight = c.weight
                        break

                # Normalize weight score (higher weight = lower score)
                max_weight = max(c.weight for c in candidates) or 1.0
                weight_score = 1.0 - (weight / max_weight) if max_weight > 0 else 0.5

                # Blend latency and weight scores
                combined_score = (
                    combined_score * (1 - context.weight_blend) +
                    weight_score * context.weight_blend
                )

            final_scores.append((model, combined_score))

        # Sort by score (lower is better)
        final_scores.sort(key=lambda x: x[1])

        # Select the best model
        best_model = final_scores[0][0]
        best_score = final_scores[0][1]

        # Calculate confidence based on gap between best and second-best
        confidence = 1.0
        if len(final_scores) > 1:
            second_score = final_scores[1][1]
            if second_score > 0:
                gap = second_score - best_score
                confidence = min(1.0, gap / second_score)

        return SelectionResult(
            selected_model=best_model,
            confidence=confidence,
            metadata={
                "score": best_score,
                "method": "latency_aware",
                "candidates_evaluated": len(scored_candidates),
                "all_scores": {m: s for m, s in final_scores},
            },
        )


def _filter_by_max_tokens(
    candidates: list["ModelRef"],
    signals: "SignalMatches | None"
) -> list["ModelRef"]:
    """Filter candidates by max_tokens constraint.

    Args:
        candidates: List of candidate ModelRef
        signals: SignalMatches containing context_length with token_count in metadata

    Returns:
        Filtered list of candidates. If all filtered, returns first candidate as fallback.
    """
    if not signals or not signals.context_length:
        return candidates

    token_count = signals.context_length.metadata.get("token_count")
    if token_count is None:
        return candidates

    filtered = [
        m for m in candidates
        if m.max_tokens is None or m.max_tokens >= token_count
    ]

    if not filtered:
        logger.warning(
            "all_models_exceed_max_tokens",
            token_count=token_count,
            candidates=[m.model for m in candidates],
            fallback="using_first_candidate",
        )
        return [candidates[0]]

    return filtered


class Registry:
    """Registry for model selectors."""

    def __init__(self, latency_tracker: LatencyTracker | None = None) -> None:
        """Initialize the registry.

        Args:
            latency_tracker: Optional latency tracker for LatencyAwareSelector.
        """
        self._selectors: dict[SelectionMethod, ModelSelector] = {
            SelectionMethod.STATIC: StaticSelector(),
            SelectionMethod.ROUND_ROBIN: RoundRobinSelector(),
            SelectionMethod.LATENCY_AWARE: LatencyAwareSelector(latency_tracker),
        }

    def register(self, method: SelectionMethod, selector: ModelSelector) -> None:
        """Register a selector for a method."""
        self._selectors[method] = selector

    def set_latency_tracker(self, tracker: LatencyTracker) -> None:
        """Set the latency tracker for LatencyAwareSelector."""
        self._selectors[SelectionMethod.LATENCY_AWARE] = LatencyAwareSelector(tracker)

    async def select(
        self, method: SelectionMethod, context: SelectionContext
    ) -> SelectionResult:
        """Select a model using the specified method.

        Applies max_tokens filtering before selection if signals are provided.
        """
        # Filter candidates by max_tokens before selection
        filtered_candidates = _filter_by_max_tokens(
            context.candidate_models,
            context.signals
        )

        # Create context with filtered candidates
        filtered_context = SelectionContext(
            query=context.query,
            candidate_models=filtered_candidates,
            user_id=context.user_id,
            metadata=context.metadata,
            signals=context.signals,
            latency_percentile=context.latency_percentile,
            tpot_percentile=context.tpot_percentile,
            ttft_percentile=context.ttft_percentile,
            min_observations=context.min_observations,
            fallback_to_weight=context.fallback_to_weight,
            weight_blend=context.weight_blend,
        )

        selector = self._selectors.get(method)
        if not selector:
            raise ValueError(f"Unknown selection method: {method}")
        return await selector.select(filtered_context)


# Import here to avoid circular dependency
from mini_router.config.config import ModelRef  # noqa: E402
