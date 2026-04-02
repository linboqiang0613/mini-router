"""Types for decision evaluation."""

from dataclasses import dataclass, field

from mini_router.config.config import Decision


@dataclass
class DecisionResult:
    """Result of decision evaluation."""

    decision: Decision
    confidence: float = 1.0
    matched_rules: list[str] = field(default_factory=list)
