"""Classifier implementation for signal extraction."""

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import structlog

from mini_router.client import OpenAIClient
from mini_router.config.config import ClassifierConfig, ClassifierModelConfig, KeywordRule, Operator
from mini_router.signal_layer.types import SignalMatches, TaskResult, TaskType

logger = structlog.get_logger()


class Classifier(ABC):
    """Abstract base class for all classifiers."""

    @abstractmethod
    async def classify(self, text: str) -> SignalMatches:
        """
        Classify text and return SignalMatches.

        Each subclass fills only its responsible field.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Classifier name for logging and debugging."""
        pass


class MLClassifierBase(Classifier):
    """Base class for ML-based classifiers with timeout and fallback."""

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        task_type: TaskType,
        prompt: str,
        fallback_label: str | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.task_type = task_type
        self.prompt = prompt
        self._fallback_label = fallback_label

    @property
    def name(self) -> str:
        return self.task_type.value

    @abstractmethod
    def _parse_response(self, content: str) -> str:
        """Parse API response content to extract label."""
        pass

    @abstractmethod
    def _get_field_name(self) -> str:
        """Get SignalMatches field name for this classifier."""
        pass

    async def classify(self, text: str) -> SignalMatches:
        """Classify with timeout control and fallback."""
        if not self.config.enabled:
            return SignalMatches()

        try:
            result = await asyncio.wait_for(
                self._call_api(text),
                timeout=self.config.timeout
            )
            return SignalMatches(**{self._get_field_name(): result})
        except asyncio.TimeoutError:
            logger.warning(
                f"{self.name}_classifier_timeout",
                timeout=self.config.timeout,
                fallback=self._fallback_label,
            )
            return self._create_fallback_result()
        except Exception as e:
            logger.error(
                f"{self.name}_classifier_error",
                error=str(e),
                error_type=type(e).__name__,
                fallback=self._fallback_label,
            )
            return self._create_fallback_result()

    async def _call_api(self, text: str) -> TaskResult:
        """Call OpenAI API for classification."""
        response = await self.client.chat_completion(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=50,
        )

        content = response["choices"][0]["message"]["content"]
        label = self._parse_response(content)

        return TaskResult(
            task=self.task_type,
            label=label,
            confidence=1.0,
        )

    def _create_fallback_result(self) -> SignalMatches:
        """Create fallback result when timeout or error."""
        if self._fallback_label is None:
            return SignalMatches()

        return SignalMatches(
            **{self._get_field_name(): TaskResult(
                task=self.task_type,
                label=self._fallback_label,
                confidence=0.0,
                metadata={"fallback": True},
            )}
        )


class IntentClassifier(MLClassifierBase):
    """Intent classification using ML API."""

    PROMPT = (
        "Classify the intent of the following text. "
        "Respond with just the intent label."
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str | None = None,
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            task_type=TaskType.INTENT,
            prompt=self.PROMPT,
            fallback_label=fallback_label,
        )

    def _parse_response(self, content: str) -> str:
        return content.strip()

    def _get_field_name(self) -> str:
        return "intent"


class PIIClassifier(MLClassifierBase):
    """PII detection using ML API."""

    PROMPT = (
        "Detect if the following text contains PII "
        "(personally identifiable information). "
        "Respond with 'detected' or 'none'."
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str = "detected",  # Safety-first default
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            task_type=TaskType.PII,
            prompt=self.PROMPT,
            fallback_label=fallback_label,
        )

    def _parse_response(self, content: str) -> str:
        return content.strip().lower()

    def _get_field_name(self) -> str:
        return "pii"


class SecurityClassifier(MLClassifierBase):
    """Security threat detection using ML API."""

    PROMPT = (
        "Detect if the following text contains security threats "
        "(jailbreak, injection, malicious content). "
        "Respond with 'safe' or the threat type."
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str = "detected",  # Safety-first default
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            task_type=TaskType.SECURITY,
            prompt=self.PROMPT,
            fallback_label=fallback_label,
        )

    def _parse_response(self, content: str) -> str:
        return content.strip()

    def _get_field_name(self) -> str:
        return "security"


class KeywordClassifier(Classifier):
    """Keyword-based classifier for simple rule matching."""

    def __init__(self, rules: list[KeywordRule]) -> None:
        self.rules = {rule.name: rule for rule in rules}

    @property
    def name(self) -> str:
        return "keyword"

    async def classify(self, text: str) -> SignalMatches:
        """Check keyword rules against text and return SignalMatches."""
        results: dict[str, bool] = {}

        for name, rule in self.rules.items():
            keywords = rule.keywords
            search_text = text

            if not rule.case_sensitive:
                keywords = [k.lower() for k in keywords]
                search_text = text.lower()

            if rule.operator == Operator.ANY:
                results[name] = any(kw in search_text for kw in keywords)
            else:  # ALL
                results[name] = all(kw in search_text for kw in keywords)

        return SignalMatches(keyword_rules=results)


class MLClassifier:
    """ML-based classifier using OpenAI-compatible API."""

    def __init__(self, config: ClassifierConfig, client: OpenAIClient) -> None:
        self.config = config
        self.client = client

    async def classify_intent(self, text: str) -> TaskResult | None:
        """Classify intent using API."""
        if not self.config.intent or not self.config.intent.enabled:
            return None

        try:
            response = await self.client.chat_completion(
                model=self.config.intent.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Classify the intent of the following text. "
                        "Respond with just the intent label.",
                    },
                    {"role": "user", "content": text},
                ],
                max_tokens=50,
            )

            label = response["choices"][0]["message"]["content"].strip()
            return TaskResult(
                task=TaskType.INTENT,
                label=label,
                confidence=1.0,  # API doesn't provide confidence
            )
        except Exception as e:
            logger.error(
                "intent_classification_failed",
                error=str(e),
                error_type=type(e).__name__,
                model=self.config.intent.model if self.config.intent else None,
            )
            return None

    async def classify_pii(self, text: str) -> TaskResult | None:
        """Classify PII using API."""
        if not self.config.pii or not self.config.pii.enabled:
            return None

        try:
            response = await self.client.chat_completion(
                model=self.config.pii.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Detect if the following text contains PII "
                        "(personally identifiable information). "
                        "Respond with 'detected' or 'none'.",
                    },
                    {"role": "user", "content": text},
                ],
                max_tokens=50,
            )

            label = response["choices"][0]["message"]["content"].strip().lower()
            return TaskResult(
                task=TaskType.PII,
                label=label,
                confidence=1.0,
                metadata={"has_pii": label == "detected"},
            )
        except Exception as e:
            logger.error(
                "pii_classification_failed",
                error=str(e),
                error_type=type(e).__name__,
                model=self.config.pii.model if self.config.pii else None,
            )
            return None

    async def classify_security(self, text: str) -> TaskResult | None:
        """Classify security threats using API."""
        if not self.config.security or not self.config.security.enabled:
            return None

        try:
            response = await self.client.chat_completion(
                model=self.config.security.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Detect if the following text contains security threats "
                        "(jailbreak, injection, malicious content). "
                        "Respond with 'safe' or the threat type.",
                    },
                    {"role": "user", "content": text},
                ],
                max_tokens=50,
            )

            label = response["choices"][0]["message"]["content"].strip()
            return TaskResult(
                task=TaskType.SECURITY,
                label=label,
                confidence=1.0,
                metadata={"is_safe": label.lower() == "safe"},
            )
        except Exception as e:
            logger.error(
                "security_classification_failed",
                error=str(e),
                error_type=type(e).__name__,
                model=self.config.security.model if self.config.security else None,
            )
            return None

    async def classify_complexity(self, text: str) -> TaskResult | None:
        """Classify query complexity using API."""
        if not self.config.complexity or not self.config.complexity.enabled:
            return None

        try:
            response = await self.client.chat_completion(
                model=self.config.complexity.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Analyze the complexity of the following query. "
                        "Consider factors like: length, number of tasks, reasoning required, "
                        "domain knowledge needed, and ambiguity. "
                        "Respond with exactly one of: 'simple', 'medium', or 'complex'. "
                        "simple: short, single task, straightforward\n"
                        "medium: moderate length, may need some reasoning\n"
                        "complex: long, multiple tasks, requires deep reasoning or domain expertise",
                    },
                    {"role": "user", "content": text},
                ],
                max_tokens=20,
            )

            label = response["choices"][0]["message"]["content"].strip().lower()
            # Normalize the label
            if label in ("simple", "easy", "low"):
                label = "simple"
            elif label in ("complex", "hard", "high", "difficult"):
                label = "complex"
            else:
                label = "medium"

            return TaskResult(
                task=TaskType.COMPLEXITY,
                label=label,
                confidence=1.0,
                metadata={"complexity_level": label},
            )
        except Exception as e:
            logger.error(
                "complexity_classification_failed",
                error=str(e),
                error_type=type(e).__name__,
                model=self.config.complexity.model if self.config.complexity else None,
            )
            return None


class UnifiedClassifier:
    """Unified classifier combining keyword and ML classifiers."""

    def __init__(
        self,
        keyword_classifier: KeywordClassifier,
        ml_classifier: MLClassifier | None = None,
    ) -> None:
        self.keyword_classifier = keyword_classifier
        self.ml_classifier = ml_classifier

    async def classify(
        self,
        text: str,
        tasks: list[TaskType] | None = None,
    ) -> SignalMatches:
        """Classify text using all available classifiers."""
        matches = SignalMatches()

        # Keyword classification (always run)
        matches.keyword_rules = (await self.keyword_classifier.classify(text)).keyword_rules

        # ML classification
        if self.ml_classifier and tasks:
            ml_tasks = asyncio.gather(
                *[
                    self._run_ml_task(text, task)
                    for task in tasks
                    if task in (TaskType.INTENT, TaskType.PII, TaskType.SECURITY, TaskType.COMPLEXITY)
                ]
            )
            results = await ml_tasks
            for result in results:
                if result is None:
                    continue
                if result.task == TaskType.INTENT:
                    matches.intent = result
                elif result.task == TaskType.PII:
                    matches.pii = result
                elif result.task == TaskType.SECURITY:
                    matches.security = result
                elif result.task == TaskType.COMPLEXITY:
                    matches.complexity = result

        return matches

    async def _run_ml_task(self, text: str, task: TaskType) -> TaskResult | None:
        """Run a single ML classification task."""
        if not self.ml_classifier:
            return None

        if task == TaskType.INTENT:
            return await self.ml_classifier.classify_intent(text)
        elif task == TaskType.PII:
            return await self.ml_classifier.classify_pii(text)
        elif task == TaskType.SECURITY:
            return await self.ml_classifier.classify_security(text)
        elif task == TaskType.COMPLEXITY:
            return await self.ml_classifier.classify_complexity(text)
        return None