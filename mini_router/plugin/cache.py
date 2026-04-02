"""Cache implementations for the plugin layer."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class CacheEntry:
    """A cache entry."""

    query: str
    response: str
    query_embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    access_count: int = 0


class Cache(ABC):
    """Abstract cache interface."""

    @abstractmethod
    def get(self, key: str) -> CacheEntry | None:
        """Get entry by exact key match."""
        pass

    @abstractmethod
    def set(self, key: str, entry: CacheEntry) -> None:
        """Store entry with key."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete entry by key."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all entries."""
        pass

    @abstractmethod
    def size(self) -> int:
        """Return number of entries."""
        pass


class MemoryCache(Cache):
    """Simple in-memory cache implementation."""

    def __init__(self, max_entries: int = 10000) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._max_entries = max_entries

    def get(self, key: str) -> CacheEntry | None:
        """Get entry by exact key match."""
        entry = self._cache.get(key)
        if entry:
            entry.access_count += 1
        return entry

    def set(self, key: str, entry: CacheEntry) -> None:
        """Store entry with key."""
        # Evict oldest if at capacity
        if len(self._cache) >= self._max_entries and key not in self._cache:
            self._evict_oldest()

        self._cache[key] = entry

    def delete(self, key: str) -> bool:
        """Delete entry by key."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all entries."""
        self._cache.clear()

    def size(self) -> int:
        """Return number of entries."""
        return len(self._cache)

    def _evict_oldest(self) -> None:
        """Evict the oldest entry (LRU-style)."""
        if not self._cache:
            return

        # Find entry with lowest access count and oldest creation time
        oldest_key = min(
            self._cache.keys(),
            key=lambda k: (
                self._cache[k].access_count,
                self._cache[k].created_at,
            ),
        )
        del self._cache[oldest_key]
        logger.debug("cache_evicted", key=oldest_key)


class SemanticCache:
    """
    Semantic cache using embedding similarity.

    Requires an embedder to compute embeddings for queries.
    """

    def __init__(
        self,
        embedder: "Embedder",
        similarity_threshold: float = 0.95,
        max_entries: int = 10000,
    ) -> None:
        from mini_router.signal_layer.embedder import Embedder

        self._embedder: Embedder = embedder
        self._similarity_threshold = similarity_threshold
        self._memory_cache = MemoryCache(max_entries=max_entries)
        self._embedding_index: dict[str, list[float]] = {}

    async def get_similar(self, query: str) -> CacheEntry | None:
        """Find a semantically similar cached entry."""
        import numpy as np

        from mini_router.signal_layer.embedder import cosine_similarity

        # Get embedding for query
        query_embedding = await self._embedder.embed(query)
        query_vec = query_embedding.tolist()

        # Search for similar entries
        best_match: tuple[str, float] | None = None
        for key, cached_vec in self._embedding_index.items():
            similarity = cosine_similarity(
                np.array(query_vec, dtype=np.float32),
                np.array(cached_vec, dtype=np.float32),
            )
            if similarity >= self._similarity_threshold:
                if best_match is None or similarity > best_match[1]:
                    best_match = (key, similarity)

        if best_match:
            entry = self._memory_cache.get(best_match[0])
            if entry:
                entry.metadata["similarity"] = best_match[1]
            return entry

        return None

    async def set(self, query: str, response: str, metadata: dict[str, Any] | None = None) -> None:
        """Store entry with its embedding."""
        embedding = await self._embedder.embed(query)

        entry = CacheEntry(
            query=query,
            response=response,
            query_embedding=embedding.tolist(),
            metadata=metadata or {},
        )

        self._memory_cache.set(query, entry)
        self._embedding_index[query] = embedding.tolist()

    def get(self, key: str) -> CacheEntry | None:
        """Get entry by exact key match."""
        return self._memory_cache.get(key)

    def delete(self, key: str) -> bool:
        """Delete entry by key."""
        result = self._memory_cache.delete(key)
        if result:
            self._embedding_index.pop(key, None)
        return result

    def clear(self) -> None:
        """Clear all entries."""
        self._memory_cache.clear()
        self._embedding_index.clear()

    def size(self) -> int:
        """Return number of entries."""
        return self._memory_cache.size()
