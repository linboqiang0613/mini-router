"""Embedder implementation for semantic similarity."""

from abc import ABC, abstractmethod
from typing import Any

import httpx
import numpy as np
import structlog

from mini_router.config.config import EmbedderConfig

logger = structlog.get_logger()


class Embedder(ABC):
    """Abstract embedder interface."""

    @abstractmethod
    async def embed(self, text: str | list[dict[str, Any]]) -> np.ndarray:
        """Generate embedding for text. Supports string or content array format."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str | list[dict[str, Any]]]) -> list[np.ndarray]:
        """Generate embeddings for multiple texts."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return embedding dimension."""
        pass


class MockEmbedder(Embedder):
    """Mock embedder for testing without real embedding model."""

    def __init__(self, dimension: int = 768) -> None:
        self._dimension = dimension

    async def embed(self, text: str) -> np.ndarray:
        """Generate mock embedding based on text hash."""
        # Handle both string and list content (from ChatMessage.content)
        if isinstance(text, list):
            # Extract text from content blocks
            text_parts = []
            for block in text:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            text = " ".join(text_parts)

        # Use text hash to generate deterministic embedding
        np.random.seed(hash(text) % (2**32))
        embedding = np.random.randn(self._dimension).astype(np.float32)
        # Normalize to unit vector
        return embedding / np.linalg.norm(embedding)

    async def embed_batch(self, texts: list[str | list[dict[str, Any]]]) -> list[np.ndarray]:
        """Generate mock embeddings for multiple texts."""
        return [await self.embed(text) for text in texts]

    @property
    def dimension(self) -> int:
        return self._dimension


class OpenAIEmbedder(Embedder):
    """Embedder using OpenAI-compatible API."""

    def __init__(
        self,
        config: EmbedderConfig,
        base_url: str,
        api_key: str = "",
        timeout: float = 60.0,
    ) -> None:
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=timeout,
                write=10.0,
                pool=10.0,
            )
        )
        self._dimension: int | None = None

    async def embed(self, text: str | list[dict[str, Any]]) -> np.ndarray:
        """Generate embedding for text."""
        embeddings = await self.embed_batch([text])
        return embeddings[0]

    async def embed_batch(self, texts: list[str | list[dict[str, Any]]]) -> list[np.ndarray]:
        """Generate embeddings for multiple texts."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Convert any list content to string
        string_texts = []
        for text in texts:
            if isinstance(text, list):
                text_parts = []
                for block in text:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                string_texts.append(" ".join(text_parts))
            else:
                string_texts.append(text)

        payload = {
            "model": self.config.model,
            "input": string_texts,
        }

        response = await self.client.post(
            f"{self.base_url}/embeddings",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()

        embeddings = []
        for item in data["data"]:
            embedding = np.array(item["embedding"], dtype=np.float32)
            embeddings.append(embedding)
            if self._dimension is None:
                self._dimension = len(embedding)

        return embeddings

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            # Default dimension for common models
            return 1536
        return self._dimension

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
