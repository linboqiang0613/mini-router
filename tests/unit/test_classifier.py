"""Tests for classifier module."""

import asyncio

import pytest

from mini_router.config.config import KeywordRule, Operator
from mini_router.signal_layer.classifier import KeywordClassifier
from mini_router.signal_layer.types import SignalMatches, TaskResult, TaskType


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


class TestTaskType:
    """Tests for TaskType enum."""

    def test_keyword_task_type_exists(self) -> None:
        """Test KEYWORD task type exists."""
        from mini_router.signal_layer.types import TaskType

        assert TaskType.KEYWORD == "keyword"
        assert TaskType.KEYWORD.value == "keyword"


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


class TestSignalMatches:
    """Tests for SignalMatches dataclass."""

    def test_keyword_match_helpers(self) -> None:
        """Test keyword match helper methods."""
        matches = SignalMatches(
            keyword_rules={"code_related": True, "math_related": False},
        )

        assert matches.has_keyword_match("code_related") is True
        assert matches.has_keyword_match("math_related") is False
        assert matches.has_keyword_match("unknown") is False

    def test_pii_detection(self) -> None:
        """Test PII detection helper."""
        # With PII detected
        matches = SignalMatches(
            pii=TaskResult(task=TaskType.PII, label="detected", confidence=1.0),
        )
        assert matches.has_pii() is True

        # Without PII
        matches = SignalMatches(
            pii=TaskResult(task=TaskType.PII, label="none", confidence=1.0),
        )
        assert matches.has_pii() is False

        # No PII classification
        matches = SignalMatches()
        assert matches.has_pii() is False

    def test_security_threat_detection(self) -> None:
        """Test security threat detection helper."""
        # With threat
        matches = SignalMatches(
            security=TaskResult(task=TaskType.SECURITY, label="jailbreak", confidence=1.0),
        )
        assert matches.has_security_threat() is True

        # Safe
        matches = SignalMatches(
            security=TaskResult(task=TaskType.SECURITY, label="safe", confidence=1.0),
        )
        assert matches.has_security_threat() is False


class TestPIIClassifier:
    """Tests for PIIClassifier."""

    def test_pii_classifier_exists(self) -> None:
        """Test PIIClassifier can be imported."""
        from mini_router.signal_layer.classifier import PIIClassifier
        assert PIIClassifier is not None

    def test_pii_classifier_name(self) -> None:
        """Test PIIClassifier name property."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import PIIClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = PIIClassifier(config, client)
        assert classifier.name == "pii"

    def test_pii_default_fallback_is_detected(self) -> None:
        """Test PIIClassifier default fallback is 'detected'."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import PIIClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = PIIClassifier(config, client)
        assert classifier._fallback_label == "detected"

    def test_pii_field_name(self) -> None:
        """Test PIIClassifier field name is 'pii'."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import PIIClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = PIIClassifier(config, client)
        assert classifier._get_field_name() == "pii"


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


class TestIntentClassifier:
    """Tests for IntentClassifier."""

    def test_intent_classifier_exists(self) -> None:
        """Test IntentClassifier can be imported."""
        from mini_router.signal_layer.classifier import IntentClassifier
        assert IntentClassifier is not None

    def test_intent_classifier_name(self) -> None:
        """Test IntentClassifier name property."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import IntentClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = IntentClassifier(config, client)
        assert classifier.name == "intent"

    def test_intent_field_name(self) -> None:
        """Test IntentClassifier field name is 'intent'."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import IntentClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = IntentClassifier(config, client)
        assert classifier._get_field_name() == "intent"


class TestSecurityClassifier:
    """Tests for SecurityClassifier."""

    def test_security_classifier_exists(self) -> None:
        """Test SecurityClassifier can be imported."""
        from mini_router.signal_layer.classifier import SecurityClassifier
        assert SecurityClassifier is not None

    def test_security_classifier_name(self) -> None:
        """Test SecurityClassifier name property."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import SecurityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = SecurityClassifier(config, client)
        assert classifier.name == "security"

    def test_security_default_fallback_is_detected(self) -> None:
        """Test SecurityClassifier default fallback is 'detected'."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import SecurityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = SecurityClassifier(config, client)
        assert classifier._fallback_label == "detected"

    def test_security_field_name(self) -> None:
        """Test SecurityClassifier field name is 'security'."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import SecurityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = SecurityClassifier(config, client)
        assert classifier._get_field_name() == "security"

class TestComplexityClassifier:
    """Tests for ComplexityClassifier."""

    def test_complexity_classifier_exists(self) -> None:
        """Test ComplexityClassifier can be imported."""
        from mini_router.signal_layer.classifier import ComplexityClassifier
        assert ComplexityClassifier is not None

    def test_complexity_classifier_name(self) -> None:
        """Test ComplexityClassifier name property."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import ComplexityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = ComplexityClassifier(config, client)
        assert classifier.name == "complexity"

    def test_complexity_default_fallback_is_complex(self) -> None:
        """Test that complexity classifier defaults to 'complex' fallback."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import ComplexityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = ComplexityClassifier(config, client)
        assert classifier._fallback_label == "complex"

    def test_complexity_parse_response_normalizes_labels(self) -> None:
        """Test ComplexityClassifier normalizes labels."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import ComplexityClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(model="test-model")
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = ComplexityClassifier(config, client)

        # Simple labels
        assert classifier._parse_response("simple") == "simple"
        assert classifier._parse_response("EASY") == "simple"
        assert classifier._parse_response("low") == "simple"
        # Complex labels
        assert classifier._parse_response("complex") == "complex"
        assert classifier._parse_response("HARD") == "complex"
        assert classifier._parse_response("difficult") == "complex"
        # Unknown labels default to complex
        assert classifier._parse_response("unknown") == "complex"
        # Backward compatibility: medium maps to complex
        assert classifier._parse_response("medium") == "complex"


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


class TestContextLengthClassifier:
    """Tests for ContextLengthClassifier."""

    @pytest.mark.asyncio
    async def test_context_length_classifier_short(self):
        """Test ContextLengthClassifier returns 'short' for text below threshold."""
        try:
            from mini_router.signal_layer.classifier import ContextLengthClassifier

            # Use a simple tokenizer for testing (GPT-2 is small and commonly available)
            classifier = ContextLengthClassifier(
                tokenizer_path="gpt2",
                threshold=100,
                fallback_label="short",
            )

            # Short text should return 'short'
            short_text = "user: hello world"
            result = await classifier.classify(short_text)

            assert result.context_length is not None
            assert result.context_length.label == "short"
            assert result.context_length.metadata.get("token_count") < 100
            assert result.context_length.confidence == 1.0
        except ImportError:
            pytest.skip("transformers not installed")

    @pytest.mark.asyncio
    async def test_context_length_classifier_long(self):
        """Test ContextLengthClassifier returns 'long' for text above threshold."""
        try:
            from mini_router.signal_layer.classifier import ContextLengthClassifier

            classifier = ContextLengthClassifier(
                tokenizer_path="gpt2",
                threshold=10,  # Low threshold for testing
                fallback_label="short",
            )

            # Long text should return 'long'
            long_text = "user: " + "hello " * 50  # Definitely >10 tokens
            result = await classifier.classify(long_text)

            assert result.context_length is not None
            assert result.context_length.label == "long"
            assert result.context_length.metadata.get("token_count") >= 10
        except ImportError:
            pytest.skip("transformers not installed")

    @pytest.mark.asyncio
    async def test_context_length_classifier_at_threshold(self):
        """Test ContextLengthClassifier at exact threshold boundary."""
        try:
            from mini_router.signal_layer.classifier import ContextLengthClassifier

            classifier = ContextLengthClassifier(
                tokenizer_path="gpt2",
                threshold=5,
                fallback_label="short",
            )

            # Test that >= threshold is "long"
            text_at_threshold = "user: hello world test"  # Should be around 5-6 tokens
            result = await classifier.classify(text_at_threshold)

            # token_count >= threshold should be "long"
            token_count = result.context_length.metadata.get("token_count")
            expected_label = "long" if token_count >= 5 else "short"
            assert result.context_length.label == expected_label
        except ImportError:
            pytest.skip("transformers not installed")


class TestMLClassifierTimeoutFallback:
    """Tests for ML classifier timeout and fallback behavior."""

    @pytest.mark.asyncio
    async def test_timeout_returns_fallback_result(self) -> None:
        """Test timeout returns fallback with confidence 0.0."""
        from unittest.mock import patch, MagicMock, AsyncMock

        from mini_router.signal_layer.classifier import PIIClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(
            model="test-model",
            enabled=True,
            timeout=1.0,  # Short timeout
            fallback_label="detected",
        )

        # Mock client that takes longer than timeout
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        client.chat_completion = AsyncMock(side_effect=lambda *args, **kwargs: asyncio.sleep(2))

        classifier = PIIClassifier(config, client)

        result = await classifier.classify("test text")
        assert result.pii is not None
        assert result.pii.label == "detected"
        assert result.pii.confidence == 0.0
        assert result.pii.metadata.get("fallback") is True

    @pytest.mark.asyncio
    async def test_disabled_classifier_returns_empty(self) -> None:
        """Test disabled classifier returns empty SignalMatches."""
        from unittest.mock import patch, MagicMock

        from mini_router.signal_layer.classifier import IntentClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(
            model="test-model",
            enabled=False,
            timeout=10.0,
            fallback_label="question",
        )

        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        classifier = IntentClassifier(config, client)

        result = await classifier.classify("test text")
        assert result.intent is None

    @pytest.mark.asyncio
    async def test_no_fallback_returns_empty_on_error(self) -> None:
        """Test classifier with no fallback returns empty SignalMatches on error."""
        from unittest.mock import patch, MagicMock, AsyncMock

        from mini_router.signal_layer.classifier import IntentClassifier
        from mini_router.config.config import ClassifierModelConfig
        from mini_router.client import OpenAIClient

        config = ClassifierModelConfig(
            model="test-model",
            enabled=True,
            timeout=10.0,
            fallback_label=None,  # No fallback
        )

        with patch("httpx.AsyncClient", return_value=MagicMock()):
            client = OpenAIClient(timeout=60.0)
        client.chat_completion = AsyncMock(side_effect=Exception("API error"))

        classifier = IntentClassifier(config, client)

        result = await classifier.classify("test text")
        assert result.intent is None
