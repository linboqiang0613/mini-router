"""Signal extraction layer - classifiers and embedders."""

from mini_router.signal_layer.classifier import (
    Classifier,
    ComplexityClassifier,
    IntentClassifier,
    KeywordClassifier,
    PIIClassifier,
    SecurityClassifier,
    UnifiedClassifier,
    ContextLengthClassifier,
)
from mini_router.signal_layer.embedder import (
    Embedder,
    MockEmbedder,
    OpenAIEmbedder,
    cosine_similarity,
)
from mini_router.signal_layer.types import (
    SignalMatches,
    TaskResult,
    TaskType,
)

__all__ = [
    "Classifier",
    "KeywordClassifier",
    "IntentClassifier",
    "PIIClassifier",
    "SecurityClassifier",
    "ComplexityClassifier",
    "UnifiedClassifier",
    "ContextLengthClassifier",
    "Embedder",
    "MockEmbedder",
    "OpenAIEmbedder",
    "cosine_similarity",
    "TaskType",
    "TaskResult",
    "SignalMatches",
]
