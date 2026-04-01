"""Tests for classifier module."""

import pytest

from mini_router.config.config import KeywordRule, Operator
from mini_router.signal_layer.classifier import KeywordClassifier
from mini_router.signal_layer.types import SignalMatches, TaskResult, TaskType


class TestTaskType:
    """Tests for TaskType enum."""

    def test_keyword_task_type_exists(self) -> None:
        """Test KEYWORD task type exists."""
        from mini_router.signal_layer.types import TaskType

        assert TaskType.KEYWORD == "keyword"
        assert TaskType.KEYWORD.value == "keyword"


class TestKeywordClassifier:
    """Tests for KeywordClassifier."""

    def test_any_operator_match(self) -> None:
        """Test ANY operator - any keyword match."""
        classifier = KeywordClassifier([
            KeywordRule(
                name="code_related",
                keywords=["code", "debug", "programming"],
                operator=Operator.ANY,
                case_sensitive=False,
            ),
        ])

        result = classifier.classify("How do I debug this code?")
        assert result["code_related"] is True

        result = classifier.classify("What is the weather?")
        assert result.get("code_related", False) is False

    def test_all_operator_match(self) -> None:
        """Test ALL operator - all keywords must match."""
        classifier = KeywordClassifier([
            KeywordRule(
                name="code_debug",
                keywords=["code", "debug"],
                operator=Operator.ALL,
                case_sensitive=False,
            ),
        ])

        result = classifier.classify("How do I debug this code?")
        assert result["code_debug"] is True

        result = classifier.classify("I have some code")
        assert result.get("code_debug", False) is False

    def test_case_sensitive(self) -> None:
        """Test case sensitive matching."""
        classifier = KeywordClassifier([
            KeywordRule(
                name="uppercase",
                keywords=["CODE"],
                operator=Operator.ANY,
                case_sensitive=True,
            ),
        ])

        result = classifier.classify("CODE is uppercase")
        assert result["uppercase"] is True

        result = classifier.classify("code is lowercase")
        assert result.get("uppercase", False) is False


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