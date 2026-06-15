"""Types for model selection."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SelectionContext:
    """Context for model selection."""

    query: str
    candidate_models: list["ModelRef"]
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    signals: "SignalMatches | None" = None  # for max_tokens filtering

    # Latency-aware selection parameters
    latency_percentile: int = 50
    tpot_percentile: int = 50
    ttft_percentile: int = 90
    min_observations: int = 3
    fallback_to_weight: bool = True
    weight_blend: float = 0.5


@dataclass
class SelectionResult:
    """Result of model selection."""

    selected_model: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    filtered_candidates: list[str] = field(default_factory=list)


# Import here to avoid circular dependency
from mini_router.config.config import ModelRef  # noqa: E402
from mini_router.signal_layer.types import SignalMatches  # noqa: E402
