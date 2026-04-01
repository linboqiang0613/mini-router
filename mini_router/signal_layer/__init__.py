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