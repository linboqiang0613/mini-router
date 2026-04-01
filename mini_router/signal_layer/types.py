"""Types for signal extraction."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    """Classification task types."""

    KEYWORD = "keyword"  # 新增：关键词匹配
    INTENT = "intent"
    PII = "pii"
    SECURITY = "security"
    COMPLEXITY = "complexity"
    CONTEXT_LENGTH = "context_length"


@dataclass
class TaskResult:
    """Result of a single classification task."""

    task: TaskType
    label: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalMatches:
    """Collection of matched signals from all classifiers."""

    keyword_rules: dict[str, bool] = field(default_factory=dict)
    embedding_rules: dict[str, bool] = field(default_factory=dict)
    # Classification results
    intent: TaskResult | None = None
    pii: TaskResult | None = None
    security: TaskResult | None = None
    complexity: TaskResult | None = None
    context_length: TaskResult | None = None

    def has_keyword_match(self, name: str) -> bool:
        """Check if a keyword rule matched."""
        return self.keyword_rules.get(name, False)

    def has_embedding_match(self, name: str) -> bool:
        """Check if an embedding rule matched."""
        return self.embedding_rules.get(name, False)

    def get_intent_label(self) -> str | None:
        """Get the intent classification label."""
        return self.intent.label if self.intent else None

    def has_pii(self) -> bool:
        """Check if PII was detected."""
        if self.pii is None:
            return False
        return self.pii.label.lower() in ("detected", "true", "yes", "1")

    def has_security_threat(self) -> bool:
        """Check if security threat was detected."""
        if self.security is None:
            return False
        return self.security.label.lower() not in ("safe", "benign", "none", "normal")

    def get_complexity_level(self) -> str:
        """Get the complexity level (simple/medium/complex)."""
        if self.complexity is None:
            return "medium"  # default
        return self.complexity.label.lower()

    def is_complex(self) -> bool:
        """Check if the query is complex."""
        return self.get_complexity_level() == "complex"

    def is_simple(self) -> bool:
        """Check if the query is simple."""
        return self.get_complexity_level() == "simple"

    def get_context_length(self) -> int | None:
        """Get the token count from context_length result."""
        if self.context_length is None:
            return None
        return self.context_length.metadata.get("token_count")