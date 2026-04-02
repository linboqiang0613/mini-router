"""Rule tree evaluation for decisions."""

from mini_router.config.config import RuleType
from mini_router.signal_layer.types import SignalMatches


class RuleEvaluator:
    """Evaluates rule trees against signals."""

    def evaluate(self, rule_node: "RuleNode", signals: SignalMatches) -> tuple[bool, list[str]]:
        """
        Evaluate a rule node against signals.

        Returns:
            Tuple of (matched, list of matched rule names)
        """
        matched_rules: list[str] = []

        if rule_node.type == RuleType.KEYWORD:
            name = rule_node.name or ""
            matched = signals.has_keyword_match(name)
            if matched and name:
                matched_rules.append(name)
            return matched, matched_rules

        elif rule_node.type == RuleType.EMBEDDING:
            name = rule_node.name or ""
            matched = signals.has_embedding_match(name)
            if matched and name:
                matched_rules.append(name)
            return matched, matched_rules

        elif rule_node.type == RuleType.SIGNAL:
            matched = self._evaluate_signal_rule(rule_node, signals)
            if matched:
                rule_name = rule_node.name or rule_node.signal or "signal"
                matched_rules.append(rule_name)
            return matched, matched_rules

        elif rule_node.type == RuleType.AND:
            return self._evaluate_and(rule_node, signals)

        elif rule_node.type == RuleType.OR:
            return self._evaluate_or(rule_node, signals)

        elif rule_node.type == RuleType.NOT:
            return self._evaluate_not(rule_node, signals)

        return False, matched_rules

    def _evaluate_signal_rule(
        self, rule_node: "RuleNode", signals: SignalMatches
    ) -> bool:
        """Evaluate a signal-based rule."""
        signal = rule_node.signal
        condition = rule_node.condition

        if signal == "pii":
            if condition == "detected":
                return signals.has_pii()
        elif signal == "security":
            if condition == "detected":
                return signals.has_security_threat()
        elif signal == "intent":
            # Check if intent matches condition
            if signals.intent and condition:
                return signals.intent.label.lower() == condition.lower()
        elif signal == "complexity":
            # Check if complexity matches condition (simple/medium/complex)
            if condition:
                return signals.get_complexity_level() == condition.lower()

        return False

    def _evaluate_and(
        self, rule_node: "RuleNode", signals: SignalMatches
    ) -> tuple[bool, list[str]]:
        """Evaluate AND rule - all children must match."""
        all_matched = True
        all_matched_rules: list[str] = []

        for child in rule_node.children:
            matched, matched_rules = self.evaluate(child, signals)
            if not matched:
                all_matched = False
            all_matched_rules.extend(matched_rules)

        return all_matched, all_matched_rules if all_matched else []

    def _evaluate_or(
        self, rule_node: "RuleNode", signals: SignalMatches
    ) -> tuple[bool, list[str]]:
        """Evaluate OR rule - any child can match."""
        any_matched = False
        all_matched_rules: list[str] = []

        for child in rule_node.children:
            matched, matched_rules = self.evaluate(child, signals)
            if matched:
                any_matched = True
                all_matched_rules.extend(matched_rules)

        return any_matched, all_matched_rules

    def _evaluate_not(
        self, rule_node: "RuleNode", signals: SignalMatches
    ) -> tuple[bool, list[str]]:
        """Evaluate NOT rule - negate child result."""
        if not rule_node.children:
            return False, []

        child = rule_node.children[0]
        matched, matched_rules = self.evaluate(child, signals)
        return not matched, []


# Import here to avoid circular dependency
from mini_router.config.config import RuleNode  # noqa: E402


class Engine:
    """Decision engine that evaluates rules against signals."""

    def __init__(self, decisions: list["Decision"], strategy: str = "priority") -> None:
        self.decisions = sorted(decisions, key=lambda d: d.priority, reverse=True)
        self.strategy = strategy
        self.evaluator = RuleEvaluator()

    def evaluate(self, signals: SignalMatches) -> "DecisionResult | None":
        """
        Evaluate all decisions against signals.

        Returns the first matching decision based on strategy.
        """
        for decision in self.decisions:
            matched, matched_rules = self.evaluator.evaluate(decision.rules, signals)
            if matched:
                confidence = self._calculate_confidence(matched_rules, decision)
                return DecisionResult(
                    decision=decision,
                    confidence=confidence,
                    matched_rules=matched_rules,
                )

        return None

    def evaluate_all(self, signals: SignalMatches) -> list["DecisionResult"]:
        """
        Evaluate all decisions and return all matches.

        Useful for collecting all applicable decisions.
        """
        results: list[DecisionResult] = []

        for decision in self.decisions:
            matched, matched_rules = self.evaluator.evaluate(decision.rules, signals)
            if matched:
                confidence = self._calculate_confidence(matched_rules, decision)
                results.append(
                    DecisionResult(
                        decision=decision,
                        confidence=confidence,
                        matched_rules=matched_rules,
                    )
                )

        return results

    def _calculate_confidence(
        self, matched_rules: list[str], decision: "Decision"
    ) -> float:
        """Calculate confidence score for a matched decision."""
        if not matched_rules:
            return 1.0

        # Simple heuristic: more matched rules = higher confidence
        # Can be enhanced with ML-based confidence scoring
        return min(1.0, len(matched_rules) * 0.5 + 0.5)


# Import here to avoid circular dependency
from mini_router.config.config import Decision  # noqa: E402
from mini_router.decision.types import DecisionResult  # noqa: E402
