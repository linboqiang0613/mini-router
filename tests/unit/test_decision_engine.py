"""Tests for decision engine."""

import pytest

from mini_router.config.config import Decision, KeywordRule, ModelRef, Operator, RuleNode, RuleType
from mini_router.decision.engine import Engine
from mini_router.signal_layer.classifier import KeywordClassifier
from mini_router.signal_layer.types import SignalMatches, TaskResult, TaskType


@pytest.fixture
def decisions() -> list[Decision]:
    """Create test decisions."""
    return [
        Decision(
            name="high_priority",
            priority=100,
            rules=RuleNode(type=RuleType.KEYWORD, name="urgent"),
            model_refs=[ModelRef(model="priority-model", weight=1.0)],
        ),
        Decision(
            name="code_route",
            priority=10,
            rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
            model_refs=[ModelRef(model="codellama", weight=1.0)],
        ),
        Decision(
            name="math_route",
            priority=5,
            rules=RuleNode(type=RuleType.KEYWORD, name="math_related"),
            model_refs=[ModelRef(model="math-model", weight=1.0)],
        ),
    ]


class TestRuleEvaluator:
    """Tests for rule evaluation."""

    def test_keyword_rule_match(self) -> None:
        """Test keyword rule matching."""
        engine = Engine([
            Decision(
                name="test",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[ModelRef(model="test-model", weight=1.0)],
            ),
        ])

        signals = SignalMatches(keyword_rules={"code_related": True})
        result = engine.evaluate(signals)

        assert result is not None
        assert result.decision.name == "test"
        assert "code_related" in result.matched_rules

    def test_keyword_rule_no_match(self) -> None:
        """Test keyword rule not matching."""
        engine = Engine([
            Decision(
                name="test",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[ModelRef(model="test-model", weight=1.0)],
            ),
        ])

        signals = SignalMatches(keyword_rules={"code_related": False})
        result = engine.evaluate(signals)

        assert result is None


class TestEngine:
    """Tests for decision engine."""

    def test_priority_ordering(self, decisions: list[Decision]) -> None:
        """Test that higher priority decisions are evaluated first."""
        engine = Engine(decisions)

        # Both urgent and code_related match, urgent has higher priority
        signals = SignalMatches(keyword_rules={"urgent": True, "code_related": True})
        result = engine.evaluate(signals)

        assert result is not None
        assert result.decision.name == "high_priority"

    def test_no_matching_decision(self, decisions: list[Decision]) -> None:
        """Test when no decision matches."""
        engine = Engine(decisions)

        signals = SignalMatches(keyword_rules={"unknown": True})
        result = engine.evaluate(signals)

        assert result is None

    def test_and_rule(self) -> None:
        """Test AND rule - all children must match."""
        engine = Engine([
            Decision(
                name="and_decision",
                priority=10,
                rules=RuleNode(
                    type=RuleType.AND,
                    children=[
                        RuleNode(type=RuleType.KEYWORD, name="code"),
                        RuleNode(type=RuleType.KEYWORD, name="debug"),
                    ],
                ),
                model_refs=[ModelRef(model="test-model", weight=1.0)],
            ),
        ])

        # Both match
        signals = SignalMatches(keyword_rules={"code": True, "debug": True})
        result = engine.evaluate(signals)
        assert result is not None
        assert result.decision.name == "and_decision"

        # Only one matches
        signals = SignalMatches(keyword_rules={"code": True, "debug": False})
        result = engine.evaluate(signals)
        assert result is None

    def test_or_rule(self) -> None:
        """Test OR rule - any child can match."""
        engine = Engine([
            Decision(
                name="or_decision",
                priority=10,
                rules=RuleNode(
                    type=RuleType.OR,
                    children=[
                        RuleNode(type=RuleType.KEYWORD, name="code"),
                        RuleNode(type=RuleType.KEYWORD, name="debug"),
                    ],
                ),
                model_refs=[ModelRef(model="test-model", weight=1.0)],
            ),
        ])

        # Either matches
        signals = SignalMatches(keyword_rules={"code": True, "debug": False})
        result = engine.evaluate(signals)
        assert result is not None

        signals = SignalMatches(keyword_rules={"code": False, "debug": True})
        result = engine.evaluate(signals)
        assert result is not None

        # Neither matches
        signals = SignalMatches(keyword_rules={"code": False, "debug": False})
        result = engine.evaluate(signals)
        assert result is None

    def test_not_rule(self) -> None:
        """Test NOT rule - negate child."""
        engine = Engine([
            Decision(
                name="not_decision",
                priority=10,
                rules=RuleNode(
                    type=RuleType.NOT,
                    children=[RuleNode(type=RuleType.KEYWORD, name="code")],
                ),
                model_refs=[ModelRef(model="test-model", weight=1.0)],
            ),
        ])

        # NOT code -> True when code is False
        signals = SignalMatches(keyword_rules={"code": False})
        result = engine.evaluate(signals)
        assert result is not None

        # NOT code -> False when code is True
        signals = SignalMatches(keyword_rules={"code": True})
        result = engine.evaluate(signals)
        assert result is None

    def test_signal_rule_pii(self) -> None:
        """Test signal rule for PII detection."""
        engine = Engine([
            Decision(
                name="block_pii",
                priority=100,
                rules=RuleNode(type=RuleType.SIGNAL, signal="pii", condition="detected"),
                model_refs=[],
            ),
        ])

        # PII detected
        signals = SignalMatches(pii=TaskResult(task=TaskType.PII, label="detected", confidence=1.0))
        result = engine.evaluate(signals)
        assert result is not None

        # No PII
        signals = SignalMatches(pii=TaskResult(task=TaskType.PII, label="none", confidence=1.0))
        result = engine.evaluate(signals)
        assert result is None