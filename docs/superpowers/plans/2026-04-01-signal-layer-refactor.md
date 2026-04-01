# Signal Layer Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor signal_layer to unify Classifier interface, split MLClassifier into 4 independent classes, add timeout control and configurable fallback mechanism.

**Architecture:** Introduce Classifier(ABC) as unified interface returning SignalMatches. Create MLClassifierBase for shared ML logic (timeout, fallback). Implement 4 specific ML classifiers (Intent, PII, Security, Complexity) and simplify UnifiedClassifier to use composition over if-elif dispatch.

**Tech Stack:** Python 3.11+, Pydantic v2, asyncio, pytest

---

## Files Overview

| File | Action | Responsibility |
|------|--------|---------------|
| `mini_router/signal_layer/types.py` | Modify | Add `TaskType.KEYWORD` |
| `mini_router/config/config.py` | Modify | Extend `ClassifierModelConfig` with `timeout` and `fallback_label` |
| `mini_router/signal_layer/classifier.py` | Rewrite | New Classifier ABC, MLClassifierBase, 4 ML subclasses, simplified UnifiedClassifier |
| `mini_router/router/router.py` | Modify | Update `_initialize_components()`, simplify `route()`, delete `_get_classification_tasks()` |
| `mini_router/signal_layer/__init__.py` | Modify | Export new classes |
| `tests/unit/test_classifier.py` | Modify | Add tests for new classifiers, timeout, fallback |
| `config.yaml` | Modify | Add timeout and fallback_label fields |
| `tests/conftest.py` | Modify | Update fixtures for new config fields |

---

## Task 1: Extend TaskType with KEYWORD

**Files:**
- Modify: `mini_router/signal_layer/types.py:8-14`

- [ ] **Step 1: Write the failing test**

Create test in `tests/unit/test_classifier.py`:

```python
class TestTaskType:
    """Tests for TaskType enum."""

    def test_keyword_task_type_exists(self) -> None:
        """Test KEYWORD task type exists."""
        from mini_router.signal_layer.types import TaskType
        assert TaskType.KEYWORD == "keyword"
        assert TaskType.KEYWORD.value == "keyword"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_classifier.py::TestTaskType::test_keyword_task_type_exists -v`
Expected: FAIL with "AttributeError: KEYWORD" or similar

- [ ] **Step 3: Modify types.py**

```python
# mini_router/signal_layer/types.py:8-14
class TaskType(str, Enum):
    """Classification task types."""

    KEYWORD = "keyword"       # 新增：关键词匹配
    INTENT = "intent"
    PII = "pii"
    SECURITY = "security"
    COMPLEXITY = "complexity"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_classifier.py::TestTaskType::test_keyword_task_type_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mini_router/signal_layer/types.py tests/unit/test_classifier.py
git commit -m "feat(signal): add TaskType.KEYWORD enum"
```

---

## Task 2: Extend ClassifierModelConfig

**Files:**
- Modify: `mini_router/config/config.py:41-45`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classifier.py`:

```python
class TestClassifierModelConfig:
    """Tests for ClassifierModelConfig."""

    def test_timeout_field_exists(self) -> None:
        """Test timeout field with default value."""
        from mini_router.config.config import ClassifierModelConfig
        config = ClassifierModelConfig(model="test-model")
        assert config.timeout == 10.0

    def test_fallback_label_field_exists(self) -> None:
        """Test fallback_label field with default None."""
        from mini_router.config.config import ClassifierModelConfig
        config = ClassifierModelConfig(model="test-model")
        assert config.fallback_label is None

    def test_fallback_label_can_be_set(self) -> None:
        """Test fallback_label can be configured."""
        from mini_router.config.config import ClassifierModelConfig
        config = ClassifierModelConfig(model="test-model", fallback_label="detected")
        assert config.fallback_label == "detected"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_classifier.py::TestClassifierModelConfig -v`
Expected: FAIL with "AttributeError: timeout" or similar

- [ ] **Step 3: Modify config.py**

```python
# mini_router/config/config.py:41-45
class ClassifierModelConfig(BaseModel):
    """Configuration for a single classifier model."""

    model: str = Field("glm-5", description="Model name for API calls")
    enabled: bool = Field(True, description="Whether this classifier is enabled")
    timeout: float = Field(10.0, description="Timeout for single classification task in seconds", ge=1.0, le=60.0)
    fallback_label: str | None = Field(
        None,
        description="Default label when timeout/error occurs. None means no fallback"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_classifier.py::TestClassifierModelConfig -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mini_router/config/config.py tests/unit/test_classifier.py
git commit -m "feat(config): add timeout and fallback_label to ClassifierModelConfig"
```

---

## Task 3: Write Classifier ABC and MLClassifierBase

**Files:**
- Modify: `mini_router/signal_layer/classifier.py:1-50`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classifier.py`:

```python
class TestClassifierABC:
    """Tests for Classifier abstract base class."""

    def test_classifier_has_classify_method(self) -> None:
        """Test Classifier has abstract classify method."""
        from mini_router.signal_layer.classifier import Classifier
        import inspect
        assert hasattr(Classifier, 'classify')
        assert inspect.iscoroutinefunction(Classifier.classify)

    def test_classifier_has_name_property(self) -> None:
        """Test Classifier has abstract name property."""
        from mini_router.signal_layer.classifier import Classifier
        assert hasattr(Classifier, 'name')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_classifier.py::TestClassifierABC -v`
Expected: FAIL (Classifier not imported correctly or missing methods)

- [ ] **Step 3: Add Classifier ABC and MLClassifierBase to classifier.py**

Add at the beginning of `mini_router/signal_layer/classifier.py` (after imports):

```python
"""Classifier implementation for signal extraction."""

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import structlog

from mini_router.client import OpenAIClient
from mini_router.config.config import ClassifierModelConfig, KeywordRule, Operator
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_classifier.py::TestClassifierABC -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mini_router/signal_layer/classifier.py tests/unit/test_classifier.py
git commit -m "feat(signal): add Classifier ABC and MLClassifierBase"
```

---

## Task 4: Implement KeywordClassifier with new interface

**Files:**
- Modify: `mini_router/signal_layer/classifier.py` (KeywordClassifier section)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classifier.py`:

```python
class TestKeywordClassifierNewInterface:
    """Tests for KeywordClassifier with new interface."""

    @pytest.mark.asyncio
    async def test_classify_returns_signal_matches(self) -> None:
        """Test classify returns SignalMatches with keyword_rules."""
        from mini_router.signal_layer.classifier import KeywordClassifier
        from mini_router.signal_layer.types import SignalMatches
        from mini_router.config.config import KeywordRule, Operator

        classifier = KeywordClassifier([
            KeywordRule(
                name="code_related",
                keywords=["code", "debug"],
                operator=Operator.ANY,
                case_sensitive=False,
            ),
        ])

        result = await classifier.classify("How do I debug this code?")
        assert isinstance(result, SignalMatches)
        assert result.keyword_rules == {"code_related": True}

    @pytest.mark.asyncio
    async def test_classify_no_match(self) -> None:
        """Test classify with no keyword match."""
        from mini_router.signal_layer.classifier import KeywordClassifier
        from mini_router.config.config import KeywordRule, Operator

        classifier = KeywordClassifier([
            KeywordRule(
                name="code_related",
                keywords=["code", "debug"],
                operator=Operator.ANY,
                case_sensitive=False,
            ),
        ])

        result = await classifier.classify("What is the weather?")
        assert result.keyword_rules == {"code_related": False}

    def test_name_property(self) -> None:
        """Test name property returns 'keyword'."""
        from mini_router.signal_layer.classifier import KeywordClassifier
        from mini_router.config.config import KeywordRule, Operator

        classifier = KeywordClassifier([])
        assert classifier.name == "keyword"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_classifier.py::TestKeywordClassifierNewInterface -v`
Expected: FAIL (KeywordClassifier.classify returns dict, not SignalMatches)

- [ ] **Step 3: Rewrite KeywordClassifier**

Replace existing `KeywordClassifier` class in `mini_router/signal_layer/classifier.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_classifier.py::TestKeywordClassifierNewInterface -v`
Expected: PASS

- [ ] **Step 5: Update existing tests to use new interface**

Modify `tests/unit/test_classifier.py` `TestKeywordClassifier` class:

```python
class TestKeywordClassifier:
    """Tests for KeywordClassifier."""

    @pytest.mark.asyncio
    async def test_any_operator_match(self) -> None:
        """Test ANY operator - any keyword match."""
        classifier = KeywordClassifier([
            KeywordRule(
                name="code_related",
                keywords=["code", "debug", "programming"],
                operator=Operator.ANY,
                case_sensitive=False,
            ),
        ])

        result = await classifier.classify("How do I debug this code?")
        assert result.keyword_rules["code_related"] is True

        result = await classifier.classify("What is the weather?")
        assert result.keyword_rules.get("code_related", False) is False

    @pytest.mark.asyncio
    async def test_all_operator_match(self) -> None:
        """Test ALL operator - all keywords must match."""
        classifier = KeywordClassifier([
            KeywordRule(
                name="code_debug",
                keywords=["code", "debug"],
                operator=Operator.ALL,
                case_sensitive=False,
            ),
        ])

        result = await classifier.classify("How do I debug this code?")
        assert result.keyword_rules["code_debug"] is True

        result = await classifier.classify("I have some code")
        assert result.keyword_rules.get("code_debug", False) is False

    @pytest.mark.asyncio
    async def test_case_sensitive(self) -> None:
        """Test case sensitive matching."""
        classifier = KeywordClassifier([
            KeywordRule(
                name="uppercase",
                keywords=["CODE"],
                operator=Operator.ANY,
                case_sensitive=True,
            ),
        ])

        result = await classifier.classify("CODE is uppercase")
        assert result.keyword_rules["uppercase"] is True

        result = await classifier.classify("code is lowercase")
        assert result.keyword_rules.get("uppercase", False) is False
```

- [ ] **Step 6: Run all classifier tests**

Run: `pytest tests/unit/test_classifier.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add mini_router/signal_layer/classifier.py tests/unit/test_classifier.py
git commit -m "feat(signal): rewrite KeywordClassifier with unified interface"
```

---

## Task 5: Implement IntentClassifier

**Files:**
- Modify: `mini_router/signal_layer/classifier.py` (add IntentClassifier)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classifier.py`:

```python
class TestIntentClassifier:
    """Tests for IntentClassifier."""

    def test_intent_classifier_exists(self) -> None:
        """Test IntentClassifier can be imported."""
        from mini_router.signal_layer.classifier import IntentClassifier
        assert IntentClassifier is not None

    def test_intent_classifier_name(self) -> None:
        """Test IntentClassifier name property."""
        from mini_router.signal_layer.classifier import IntentClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = IntentClassifier(config, client)
        assert classifier.name == "intent"

    def test_intent_field_name(self) -> None:
        """Test IntentClassifier field name is 'intent'."""
        from mini_router.signal_layer.classifier import IntentClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = IntentClassifier(config, client)
        assert classifier._get_field_name() == "intent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_classifier.py::TestIntentClassifier -v`
Expected: FAIL (IntentClassifier not defined)

- [ ] **Step 3: Implement IntentClassifier**

Add to `mini_router/signal_layer/classifier.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_classifier.py::TestIntentClassifier -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mini_router/signal_layer/classifier.py tests/unit/test_classifier.py
git commit -m "feat(signal): add IntentClassifier"
```

---

## Task 6: Implement PIIClassifier

**Files:**
- Modify: `mini_router/signal_layer/classifier.py` (add PIIClassifier)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classifier.py`:

```python
class TestPIIClassifier:
    """Tests for PIIClassifier."""

    def test_pii_classifier_exists(self) -> None:
        """Test PIIClassifier can be imported."""
        from mini_router.signal_layer.classifier import PIIClassifier
        assert PIIClassifier is not None

    def test_pii_classifier_name(self) -> None:
        """Test PIIClassifier name property."""
        from mini_router.signal_layer.classifier import PIIClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = PIIClassifier(config, client)
        assert classifier.name == "pii"

    def test_pii_default_fallback_is_detected(self) -> None:
        """Test PIIClassifier default fallback is 'detected'."""
        from mini_router.signal_layer.classifier import PIIClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = PIIClassifier(config, client)
        assert classifier._fallback_label == "detected"

    def test_pii_field_name(self) -> None:
        """Test PIIClassifier field name is 'pii'."""
        from mini_router.signal_layer.classifier import PIIClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = PIIClassifier(config, client)
        assert classifier._get_field_name() == "pii"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_classifier.py::TestPIIClassifier -v`
Expected: FAIL (PIIClassifier not defined)

- [ ] **Step 3: Implement PIIClassifier**

Add to `mini_router/signal_layer/classifier.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_classifier.py::TestPIIClassifier -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mini_router/signal_layer/classifier.py tests/unit/test_classifier.py
git commit -m "feat(signal): add PIIClassifier with safety-first fallback"
```

---

## Task 7: Implement SecurityClassifier

**Files:**
- Modify: `mini_router/signal_layer/classifier.py` (add SecurityClassifier)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classifier.py`:

```python
class TestSecurityClassifier:
    """Tests for SecurityClassifier."""

    def test_security_classifier_exists(self) -> None:
        """Test SecurityClassifier can be imported."""
        from mini_router.signal_layer.classifier import SecurityClassifier
        assert SecurityClassifier is not None

    def test_security_classifier_name(self) -> None:
        """Test SecurityClassifier name property."""
        from mini_router.signal_layer.classifier import SecurityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = SecurityClassifier(config, client)
        assert classifier.name == "security"

    def test_security_default_fallback_is_detected(self) -> None:
        """Test SecurityClassifier default fallback is 'detected'."""
        from mini_router.signal_layer.classifier import SecurityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = SecurityClassifier(config, client)
        assert classifier._fallback_label == "detected"

    def test_security_field_name(self) -> None:
        """Test SecurityClassifier field name is 'security'."""
        from mini_router.signal_layer.classifier import SecurityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = SecurityClassifier(config, client)
        assert classifier._get_field_name() == "security"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_classifier.py::TestSecurityClassifier -v`
Expected: FAIL (SecurityClassifier not defined)

- [ ] **Step 3: Implement SecurityClassifier**

Add to `mini_router/signal_layer/classifier.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_classifier.py::TestSecurityClassifier -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mini_router/signal_layer/classifier.py tests/unit/test_classifier.py
git commit -m "feat(signal): add SecurityClassifier with safety-first fallback"
```

---

## Task 8: Implement ComplexityClassifier

**Files:**
- Modify: `mini_router/signal_layer/classifier.py` (add ComplexityClassifier)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classifier.py`:

```python
class TestComplexityClassifier:
    """Tests for ComplexityClassifier."""

    def test_complexity_classifier_exists(self) -> None:
        """Test ComplexityClassifier can be imported."""
        from mini_router.signal_layer.classifier import ComplexityClassifier
        assert ComplexityClassifier is not None

    def test_complexity_classifier_name(self) -> None:
        """Test ComplexityClassifier name property."""
        from mini_router.signal_layer.classifier import ComplexityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = ComplexityClassifier(config, client)
        assert classifier.name == "complexity"

    def test_complexity_default_fallback_is_medium(self) -> None:
        """Test ComplexityClassifier default fallback is 'medium'."""
        from mini_router.signal_layer.classifier import ComplexityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = ComplexityClassifier(config, client)
        assert classifier._fallback_label == "medium"

    def test_complexity_parse_response_normalizes_labels(self) -> None:
        """Test ComplexityClassifier normalizes labels."""
        from mini_router.signal_layer.classifier import ComplexityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = ComplexityClassifier(config, client)

        assert classifier._parse_response("simple") == "simple"
        assert classifier._parse_response("easy") == "simple"
        assert classifier._parse_response("low") == "simple"
        assert classifier._parse_response("complex") == "complex"
        assert classifier._parse_response("hard") == "complex"
        assert classifier._parse_response("medium") == "medium"
        assert classifier._parse_response("unknown") == "medium"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_classifier.py::TestComplexityClassifier -v`
Expected: FAIL (ComplexityClassifier not defined)

- [ ] **Step 3: Implement ComplexityClassifier**

Add to `mini_router/signal_layer/classifier.py`:

```python
class ComplexityClassifier(MLClassifierBase):
    """Complexity analysis using ML API."""

    PROMPT = (
        "Analyze the complexity of the following query. "
        "Consider factors like: length, number of tasks, reasoning required, "
        "domain knowledge needed, and ambiguity. "
        "Respond with exactly one of: 'simple', 'medium', or 'complex'. "
        "simple: short, single task, straightforward\n"
        "medium: moderate length, may need some reasoning\n"
        "complex: long, multiple tasks, requires deep reasoning or domain expertise"
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str = "medium",  # Neutral default
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            task_type=TaskType.COMPLEXITY,
            prompt=self.PROMPT,
            fallback_label=fallback_label,
        )

    def _parse_response(self, content: str) -> str:
        label = content.strip().lower()
        # Normalize labels
        if label in ("simple", "easy", "low"):
            return "simple"
        elif label in ("complex", "hard", "high", "difficult"):
            return "complex"
        else:
            return "medium"

    def _get_field_name(self) -> str:
        return "complexity"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_classifier.py::TestComplexityClassifier -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mini_router/signal_layer/classifier.py tests/unit/test_classifier.py
git commit -m "feat(signal): add ComplexityClassifier with neutral fallback"
```

---

## Task 9: Simplify UnifiedClassifier

**Files:**
- Modify: `mini_router/signal_layer/classifier.py` (UnifiedClassifier section)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classifier.py`:

```python
class TestUnifiedClassifierNewInterface:
    """Tests for simplified UnifiedClassifier."""

    @pytest.mark.asyncio
    async def test_unified_combines_multiple_classifiers(self) -> None:
        """Test UnifiedClassifier combines results from multiple classifiers."""
        from mini_router.signal_layer.classifier import (
            UnifiedClassifier,
            KeywordClassifier,
        )
        from mini_router.config.config import KeywordRule, Operator

        keyword = KeywordClassifier([
            KeywordRule(
                name="test_rule",
                keywords=["test"],
                operator=Operator.ANY,
                case_sensitive=False,
            ),
        ])

        unified = UnifiedClassifier([keyword])
        result = await unified.classify("this is a test")

        assert result.keyword_rules == {"test_rule": True}

    @pytest.mark.asyncio
    async def test_unified_merges_signal_matches(self) -> None:
        """Test UnifiedClassifier properly merges SignalMatches."""
        from mini_router.signal_layer.classifier import UnifiedClassifier
        from mini_router.signal_layer.types import SignalMatches, TaskResult, TaskType

        # Mock classifier that returns intent
        class MockIntentClassifier:
            name = "mock_intent"
            async def classify(self, text: str) -> SignalMatches:
                return SignalMatches(
                    intent=TaskResult(task=TaskType.INTENT, label="question", confidence=1.0)
                )

        # Mock classifier that returns keyword
        class MockKeywordClassifier:
            name = "mock_keyword"
            async def classify(self, text: str) -> SignalMatches:
                return SignalMatches(keyword_rules={"test": True})

        unified = UnifiedClassifier([MockIntentClassifier(), MockKeywordClassifier()])
        result = await unified.classify("test question")

        assert result.keyword_rules == {"test": True}
        assert result.intent is not None
        assert result.intent.label == "question"

    def test_unified_name_property(self) -> None:
        """Test UnifiedClassifier name property."""
        from mini_router.signal_layer.classifier import UnifiedClassifier
        unified = UnifiedClassifier([])
        assert unified.name == "unified"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_classifier.py::TestUnifiedClassifierNewInterface -v`
Expected: FAIL (UnifiedClassifier old interface incompatible)

- [ ] **Step 3: Rewrite UnifiedClassifier**

Replace existing `UnifiedClassifier` class in `mini_router/signal_layer/classifier.py`:

```python
class UnifiedClassifier(Classifier):
    """Unified classifier combining all classifier instances."""

    def __init__(self, classifiers: list[Classifier]) -> None:
        self.classifiers = classifiers

    @property
    def name(self) -> str:
        return "unified"

    async def classify(self, text: str) -> SignalMatches:
        """
        Run all classifiers in parallel and merge results.

        Uses asyncio.gather with return_exceptions=True to ensure
        single classifier failure doesn't affect others.
        """
        results = await asyncio.gather(
            *[c.classify(text) for c in self.classifiers],
            return_exceptions=True,
        )

        final_matches = SignalMatches()
        for classifier, result in zip(self.classifiers, results):
            if isinstance(result, Exception):
                logger.error(
                    "classifier_failed",
                    classifier=classifier.name,
                    error=str(result),
                )
                continue
            if isinstance(result, SignalMatches):
                final_matches = self._merge_matches(final_matches, result)

        return final_matches

    def _merge_matches(
        self,
        base: SignalMatches,
        new: SignalMatches,
    ) -> SignalMatches:
        """Merge two SignalMatches objects."""
        # Merge keyword_rules
        base.keyword_rules.update(new.keyword_rules)

        # Merge ML results (non-None overwrites)
        if new.intent is not None:
            base.intent = new.intent
        if new.pii is not None:
            base.pii = new.pii
        if new.security is not None:
            base.security = new.security
        if new.complexity is not None:
            base.complexity = new.complexity

        return base
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_classifier.py::TestUnifiedClassifierNewInterface -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mini_router/signal_layer/classifier.py tests/unit/test_classifier.py
git commit -m "feat(signal): simplify UnifiedClassifier with composition"
```

---

## Task 10: Remove old MLClassifier class

**Files:**
- Modify: `mini_router/signal_layer/classifier.py` (delete old MLClassifier)

- [ ] **Step 1: Verify old MLClassifier is no longer imported anywhere**

Run: `grep -r "from mini_router.signal_layer.classifier import MLClassifier" mini_router/ tests/`
Expected: No matches (MLClassifier only used internally, replaced by MLClassifierBase)

- [ ] **Step 2: Delete old MLClassifier class**

Remove the old `MLClassifier` class from `mini_router/signal_layer/classifier.py` (approximately lines 51-210 in original file).

- [ ] **Step 3: Run all classifier tests**

Run: `pytest tests/unit/test_classifier.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add mini_router/signal_layer/classifier.py
git commit -m "refactor(signal): remove old MLClassifier class"
```

---

## Task 11: Update Router initialization

**Files:**
- Modify: `mini_router/router/router.py:50-100`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_router.py`:

```python
class TestRouterSignalLayerInit:
    """Tests for Router signal layer initialization."""

    def test_router_creates_unified_classifier(self, basic_config) -> None:
        """Test Router creates UnifiedClassifier with classifiers list."""
        from mini_router.router.router import Router
        router = Router(basic_config)
        from mini_router.signal_layer.classifier import UnifiedClassifier
        assert isinstance(router.classifier, UnifiedClassifier)

    def test_router_includes_keyword_classifier(self, basic_config) -> None:
        """Test Router includes KeywordClassifier in unified classifier."""
        from mini_router.router.router import Router
        router = Router(basic_config)
        # Check that keyword classifier is present
        classifier_names = [c.name for c in router.classifier.classifiers]
        assert "keyword" in classifier_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_router.py::TestRouterSignalLayerInit -v`
Expected: FAIL (Router still uses old UnifiedClassifier constructor)

- [ ] **Step 3: Rewrite Router._initialize_components**

Replace `_initialize_components` method in `mini_router/router/router.py`:

```python
def _initialize_components(self) -> None:
    """Initialize all router components."""
    from mini_router.signal_layer.classifier import (
        Classifier,
        KeywordClassifier,
        IntentClassifier,
        PIIClassifier,
        SecurityClassifier,
        ComplexityClassifier,
        UnifiedClassifier,
    )

    # === Signal Layer ===
    classifiers: list[Classifier] = []

    # 1. KeywordClassifier (always added)
    keyword_classifier = KeywordClassifier(self.config.signals.keyword_rules)
    classifiers.append(keyword_classifier)

    # 2. OpenAI Client
    self._client = OpenAIClient(
        base_url=self.config.models.base_url,
        api_key=self.config.models.api_key,
        timeout=self.config.models.timeout,
    )

    # 3. ML Classifiers (added based on config)
    classifier_config = self.config.models.classifier

    # Intent
    if classifier_config.intent and classifier_config.intent.enabled:
        intent_fallback = classifier_config.intent.fallback_label
        classifiers.append(IntentClassifier(
            config=classifier_config.intent,
            client=self._client,
            fallback_label=intent_fallback,
        ))

    # PII (safety-first default)
    if classifier_config.pii and classifier_config.pii.enabled:
        pii_fallback = classifier_config.pii.fallback_label or "detected"
        classifiers.append(PIIClassifier(
            config=classifier_config.pii,
            client=self._client,
            fallback_label=pii_fallback,
        ))

    # Security (safety-first default)
    if classifier_config.security and classifier_config.security.enabled:
        security_fallback = classifier_config.security.fallback_label or "detected"
        classifiers.append(SecurityClassifier(
            config=classifier_config.security,
            client=self._client,
            fallback_label=security_fallback,
        ))

    # Complexity (neutral default)
    if classifier_config.complexity and classifier_config.complexity.enabled:
        complexity_fallback = classifier_config.complexity.fallback_label or "medium"
        classifiers.append(ComplexityClassifier(
            config=classifier_config.complexity,
            client=self._client,
            fallback_label=complexity_fallback,
        ))

    # 4. UnifiedClassifier
    self.classifier = UnifiedClassifier(classifiers)

    # === Embedder ===
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

    # === Decision Layer ===
    self.decision_engine = Engine(
        decisions=self.config.decisions,
        strategy=self.config.selection.strategy.value,
    )

    # === Algorithm Layer ===
    self.selector_registry = Registry(latency_tracker=self._latency_tracker)

    # === Cache Layer ===
    if self.config.cache.enabled:
        self.cache = SemanticCache(
            embedder=self.embedder,
            similarity_threshold=self.config.cache.similarity_threshold,
            max_entries=self.config.cache.max_entries,
        )
    else:
        self.cache = MemoryCache(max_entries=self.config.cache.max_entries)
```

- [ ] **Step 4: Update imports in router.py**

Add imports at top of `mini_router/router/router.py`:

```python
from mini_router.signal_layer.classifier import (
    KeywordClassifier,
    UnifiedClassifier,
    IntentClassifier,
    PIIClassifier,
    SecurityClassifier,
    ComplexityClassifier,
)
```

Remove old imports:
```python
# Remove these:
from mini_router.signal_layer.classifier import KeywordClassifier, MLClassifier, UnifiedClassifier
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_router.py::TestRouterSignalLayerInit -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mini_router/router/router.py tests/unit/test_router.py
git commit -m "feat(router): update initialization for new signal layer"
```

---

## Task 12: Simplify Router.route and remove _get_classification_tasks

**Files:**
- Modify: `mini_router/router/router.py:102-132`

- [ ] **Step 1: Simplify route method call**

In `mini_router/router/router.py`, find the `route` method and simplify the classifier call:

```python
# Old code (around line 130-132):
# tasks = self._get_classification_tasks()
# signals = await self.classifier.classify(request.query, tasks)

# New code:
signals = await self.classifier.classify(request.query)
```

- [ ] **Step 2: Delete _get_classification_tasks method**

Remove the `_get_classification_tasks` method from `mini_router/router/router.py` (approximately lines 213-227).

- [ ] **Step 3: Run router tests**

Run: `pytest tests/unit/test_router.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add mini_router/router/router.py
git commit -m "refactor(router): simplify route() call, remove _get_classification_tasks"
```

---

## Task 13: Update signal_layer __init__.py exports

**Files:**
- Modify: `mini_router/signal_layer/__init__.py`

- [ ] **Step 1: Update exports**

Replace content of `mini_router/signal_layer/__init__.py`:

```python
"""Signal extraction layer - classifiers and embedders."""

from mini_router.signal_layer.classifier import (
    Classifier,
    KeywordClassifier,
    IntentClassifier,
    PIIClassifier,
    SecurityClassifier,
    ComplexityClassifier,
    UnifiedClassifier,
)
from mini_router.signal_layer.embedder import (
    Embedder,
    MockEmbedder,
    OpenAIEmbedder,
    cosine_similarity,
)
from mini_router.signal_layer.types import (
    TaskType,
    TaskResult,
    SignalMatches,
)

__all__ = [
    "Classifier",
    "KeywordClassifier",
    "IntentClassifier",
    "PIIClassifier",
    "SecurityClassifier",
    "ComplexityClassifier",
    "UnifiedClassifier",
    "Embedder",
    "MockEmbedder",
    "OpenAIEmbedder",
    "cosine_similarity",
    "TaskType",
    "TaskResult",
    "SignalMatches",
]
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/unit/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add mini_router/signal_layer/__init__.py
git commit -m "feat(signal): update __init__.py exports for new classifiers"
```

---

## Task 14: Update conftest.py fixtures

**Files:**
- Modify: `tests/conftest.py:20-66`

- [ ] **Step 1: Update ClassifierConfig in fixtures**

Modify `basic_config` fixture in `tests/conftest.py`:

```python
@pytest.fixture
def basic_config() -> RouterConfig:
    """Create a basic router configuration for testing."""
    return RouterConfig(
        models={
            "base_url": "http://localhost:8000/v1",
            "classifier": ClassifierConfig(
                intent=ClassifierModelConfig(
                    model="intent-classifier",
                    enabled=True,
                    timeout=10.0,
                    fallback_label=None,
                ),
                pii=ClassifierModelConfig(
                    model="pii-classifier",
                    enabled=False,
                    timeout=10.0,
                    fallback_label="detected",
                ),
                security=ClassifierModelConfig(
                    model="security-classifier",
                    enabled=False,
                    timeout=10.0,
                    fallback_label="detected",
                ),
                complexity=ClassifierModelConfig(
                    model="complexity-classifier",
                    enabled=False,
                    timeout=10.0,
                    fallback_label="medium",
                ),
            ),
        },
        signals=SignalsConfig(
            keyword_rules=[
                KeywordRule(
                    name="code_related",
                    keywords=["code", "debug", "programming"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
                KeywordRule(
                    name="math_related",
                    keywords=["calculate", "math", "equation"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
            ],
        ),
        decisions=[
            Decision(
                name="route_to_code_model",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[
                    ModelRef(model="codellama-70b", weight=1.0),
                ],
            ),
            Decision(
                name="route_to_math_model",
                priority=5,
                rules=RuleNode(type=RuleType.KEYWORD, name="math_related"),
                model_refs=[
                    ModelRef(model="llama-3-math", weight=1.0),
                ],
            ),
        ],
        cache={"enabled": False},
    )
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: update fixtures with timeout and fallback_label"
```

---

## Task 15: Update config.yaml example

**Files:**
- Modify: `config.yaml:15-29`

- [ ] **Step 1: Add timeout and fallback_label to config.yaml**

Update classifier section in `config.yaml`:

```yaml
  # 分类器配置
  classifier:
    intent:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 5.0
      fallback_label: null
    pii:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 10.0
      fallback_label: "detected"
    security:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 10.0
      fallback_label: "detected"
    complexity:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 8.0
      fallback_label: "medium"
```

- [ ] **Step 2: Verify config loads correctly**

Run: `python -c "from mini_router.config.config import RouterConfig; RouterConfig.from_yaml('config.yaml')"`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add config.yaml
git commit -m "docs: update config.yaml with timeout and fallback_label"
```

---

## Task 16: Add timeout and fallback tests

**Files:**
- Modify: `tests/unit/test_classifier.py`

- [ ] **Step 1: Write test for timeout fallback**

Add to `tests/unit/test_classifier.py`:

```python
class TestMLClassifierTimeoutFallback:
    """Tests for ML classifier timeout and fallback behavior."""

    @pytest.mark.asyncio
    async def test_timeout_returns_fallback_result(self) -> None:
        """Test timeout returns fallback with confidence 0.0."""
        from mini_router.signal_layer.classifier import PIIClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient
        from unittest.mock import AsyncMock, patch

        config = ClassifierModelConfig(
            model="test-model",
            enabled=True,
            timeout=0.1,  # Very short timeout
            fallback_label="detected",
        )

        # Mock client that takes longer than timeout
        client = OpenAIClient(base_url="http://localhost:8000/v1")
        client.chat_completion = AsyncMock(side_effect=lambda *args, **kwargs: asyncio.sleep(1))

        classifier = PIIClassifier(config, client)

        result = await classifier.classify("test text")
        assert result.pii is not None
        assert result.pii.label == "detected"
        assert result.pii.confidence == 0.0
        assert result.pii.metadata.get("fallback") is True

    @pytest.mark.asyncio
    async def test_disabled_classifier_returns_empty(self) -> None:
        """Test disabled classifier returns empty SignalMatches."""
        from mini_router.signal_layer.classifier import IntentClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(
            model="test-model",
            enabled=False,
            timeout=10.0,
            fallback_label="question",
        )

        client = OpenAIClient(base_url="http://localhost:8000/v1")
        classifier = IntentClassifier(config, client)

        result = await classifier.classify("test text")
        assert result.intent is None

    @pytest.mark.asyncio
    async def test_no_fallback_returns_empty_on_error(self) -> None:
        """Test classifier with no fallback returns empty SignalMatches on error."""
        from mini_router.signal_layer.classifier import IntentClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient
        from unittest.mock import AsyncMock

        config = ClassifierModelConfig(
            model="test-model",
            enabled=True,
            timeout=10.0,
            fallback_label=None,  # No fallback
        )

        client = OpenAIClient(base_url="http://localhost:8000/v1")
        client.chat_completion = AsyncMock(side_effect=Exception("API error"))

        classifier = IntentClassifier(config, client)

        result = await classifier.classify("test text")
        assert result.intent is None
```

- [ ] **Step 2: Add asyncio import to test file**

Add at top of `tests/unit/test_classifier.py`:

```python
import asyncio
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_classifier.py::TestMLClassifierTimeoutFallback -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_classifier.py
git commit -m "test: add timeout and fallback behavior tests"
```

---

## Task 17: Run full test suite and fix any issues

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Fix any failing tests**

If any tests fail, diagnose and fix them. Common issues might include:
- Import errors from refactored classes
- Mock issues with new interface
- Fixture issues

- [ ] **Step 3: Run tests again**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit any fixes**

```bash
git add tests/
git commit -m "fix: resolve test failures after signal layer refactor"
```

---

## Task 18: Final verification and cleanup

- [ ] **Step 1: Run all tests with coverage**

Run: `pytest tests/ --cov=mini_router -v`
Expected: All tests pass, coverage report generated

- [ ] **Step 2: Check type hints with mypy**

Run: `mypy mini_router/`
Expected: No type errors (or only minor warnings)

- [ ] **Step 3: Check code style with ruff**

Run: `ruff check mini_router/ tests/`
Expected: No linting errors

- [ ] **Step 4: Create final commit with summary**

```bash
git add -A
git commit -m "feat(signal): complete signal layer refactor

- Add Classifier ABC with unified interface
- Split MLClassifier into 4 independent classes
- Add MLClassifierBase with timeout and fallback
- Simplify UnifiedClassifier with composition
- Add TaskType.KEYWORD enum
- Extend ClassifierModelConfig with timeout/fallback_label
- Update Router initialization and simplify route()
- Add comprehensive tests for new classifiers"
```

---

## Self-Review Checklist

| Spec Requirement | Task Coverage |
|-----------------|---------------|
| Classifier ABC interface | Task 3 |
| MLClassifierBase with timeout/fallback | Task 3 |
| KeywordClassifier new interface | Task 4 |
| IntentClassifier | Task 5 |
| PIIClassifier with safety-first fallback | Task 6 |
| SecurityClassifier with safety-first fallback | Task 7 |
| ComplexityClassifier with neutral fallback | Task 8 |
| UnifiedClassifier simplified | Task 9 |
| TaskType.KEYWORD | Task 1 |
| ClassifierModelConfig extended | Task 2 |
| Router initialization updated | Task 11, 12 |
| __init__.py exports | Task 13 |
| Tests for timeout/fallback | Task 16 |
| config.yaml updated | Task 15 |

**Placeholder scan:** No TBD/TODO found.
**Type consistency:** All method signatures and field names consistent across tasks.