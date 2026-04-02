"""Configuration types for mini-router."""

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class SelectionMethod(str, Enum):
    """Available selection methods."""

    STATIC = "static"
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    LATENCY_AWARE = "latency_aware"


class Operator(str, Enum):
    """Keyword rule operator."""

    ANY = "any"
    ALL = "all"


class RuleType(str, Enum):
    """Rule node type."""

    KEYWORD = "keyword"
    EMBEDDING = "embedding"
    SIGNAL = "signal"
    AND = "and"
    OR = "or"
    NOT = "not"


# === Model Configuration ===


class ClassifierModelConfig(BaseModel):
    """Configuration for a single classifier model."""

    model: str = Field("glm-5", description="Model name for API calls")
    enabled: bool = Field(True, description="Whether this classifier is enabled")
    timeout: float = Field(10.0, description="Timeout for single classification task in seconds", ge=1.0, le=60.0)
    fallback_label: str | None = Field(
        None,
        description="Default label when timeout/error occurs. None means no fallback"
    )
    threshold: int | None = Field(None, description="Threshold for context_length classifier only")


class ClassifierConfig(BaseModel):
    """Configuration for all classifier models."""

    intent: ClassifierModelConfig | None = None
    pii: ClassifierModelConfig | None = None
    security: ClassifierModelConfig | None = None
    complexity: ClassifierModelConfig | None = None
    context_length: ClassifierModelConfig | None = None


class EmbedderConfig(BaseModel):
    """Configuration for embedding model."""

    model: str = Field(..., description="Model name for embedding API")
    enabled: bool = Field(True, description="Whether embedder is enabled")


class ModelsConfig(BaseModel):
    """Configuration for all models."""

    base_url: str = Field("http://localhost:8000/v1", description="Base URL for model API")
    api_key: str = Field("", description="API key (optional for local deployment)")
    timeout: float = Field(60.0, description="Request timeout in seconds")
    tokenizer_path: str | None = Field(None, description="HuggingFace tokenizer directory path")
    classifier: ClassifierConfig = Field(default_factory=ClassifierConfig)
    embedder: EmbedderConfig | None = None


# === Signal Configuration ===


class KeywordRule(BaseModel):
    """Keyword-based signal rule."""

    name: str = Field(..., description="Rule name")
    keywords: list[str] = Field(..., description="List of keywords")
    operator: Operator = Field(Operator.ANY, description="Match operator: any or all")
    case_sensitive: bool = Field(False, description="Case sensitive matching")


class EmbeddingRule(BaseModel):
    """Embedding-based signal rule."""

    name: str = Field(..., description="Rule name")
    examples: list[str] = Field(..., description="Example phrases")
    threshold: float = Field(0.85, description="Similarity threshold")


class CategoryConfig(BaseModel):
    """Configuration for a signal category."""

    name: str = Field(..., description="Category name")
    labels: list[str] = Field(default_factory=list, description="Possible labels")


class SignalsConfig(BaseModel):
    """Configuration for signal extraction."""

    keyword_rules: list[KeywordRule] = Field(default_factory=list)
    embedding_rules: list[EmbeddingRule] = Field(default_factory=list)
    categories: list[CategoryConfig] = Field(default_factory=list)


# === Decision Configuration ===


class RuleNode(BaseModel):
    """Rule node for decision evaluation."""

    type: RuleType = Field(..., description="Rule type")
    name: str | None = Field(None, description="Rule name (for keyword/embedding/signal)")
    signal: str | None = Field(None, description="Signal name (for signal type)")
    condition: str | None = Field(None, description="Condition to check")
    children: list["RuleNode"] = Field(default_factory=list, description="Child rules (for AND/OR/NOT)")

    def is_leaf(self) -> bool:
        """Check if this is a leaf node."""
        return self.type in (RuleType.KEYWORD, RuleType.EMBEDDING, RuleType.SIGNAL)


# Allow self-referencing model
RuleNode.model_rebuild()


class ModelRef(BaseModel):
    """Reference to a model with weight."""

    model: str = Field(..., description="Model name")
    weight: float = Field(1.0, description="Selection weight")
    max_tokens: int | None = Field(None, description="Maximum context tokens this model supports")


class DecisionAction(str, Enum):
    """Action to take when decision matches."""

    ROUTE = "route"
    REJECT = "reject"


class Decision(BaseModel):
    """A routing decision."""

    name: str = Field(..., description="Decision name")
    priority: int = Field(0, description="Priority (higher = evaluated first)")
    rules: RuleNode = Field(..., description="Rule tree")
    model_refs: list[ModelRef] = Field(default_factory=list, description="Candidate models")
    action: DecisionAction = Field(DecisionAction.ROUTE, description="Action to take")
    reject_message: str | None = Field(None, description="Message for reject action")


# === Selection Configuration ===


class LatencyAwareConfig(BaseModel):
    """Configuration for latency-aware model selection."""

    tpot_percentile: int = Field(50, description="TPOT percentile to use (1-100)", ge=1, le=100)
    ttft_percentile: int = Field(90, description="TTFT percentile to use (1-100)", ge=1, le=100)
    latency_percentile: int = Field(50, description="General latency percentile (1-100)", ge=1, le=100)
    min_observations: int = Field(3, description="Minimum observations before using latency", ge=1)
    fallback_to_weight: bool = Field(True, description="Fall back to weight if no latency data")
    weight_blend: float = Field(0.5, description="Blend factor for weight (0=latency only, 1=weight only)", ge=0, le=1)


class SelectionConfig(BaseModel):
    """Configuration for model selection."""

    strategy: SelectionMethod = Field(SelectionMethod.STATIC)
    latency_aware: LatencyAwareConfig = Field(default_factory=LatencyAwareConfig)


# === Cache Configuration ===


class CacheConfig(BaseModel):
    """Configuration for caching."""

    enabled: bool = Field(True, description="Whether caching is enabled")
    similarity_threshold: float = Field(0.95, description="Similarity threshold for cache hit")
    max_entries: int = Field(10000, description="Maximum cache entries")


# === Server Configuration ===


class ServerConfig(BaseModel):
    """Configuration for server."""

    host: str = Field("0.0.0.0")
    port: int = Field(50051)
    max_workers: int = Field(10)


# === Root Configuration ===


class RouterConfig(BaseModel):
    """Root configuration for the router."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    decisions: list[Decision] = Field(default_factory=list)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RouterConfig":
        """Load configuration from YAML file."""
        path = Path(path)
        with path.open() as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RouterConfig":
        """Create configuration from dictionary."""
        return cls.model_validate(data)
