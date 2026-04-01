"""Tests for cache implementations."""

import pytest

from mini_router.plugin.cache import CacheEntry, MemoryCache


class TestMemoryCache:
    """Tests for MemoryCache."""

    def test_set_and_get(self) -> None:
        """Test basic set and get operations."""
        cache = MemoryCache()

        entry = CacheEntry(query="test query", response="test response")
        cache.set("test-key", entry)

        result = cache.get("test-key")
        assert result is not None
        assert result.query == "test query"
        assert result.response == "test response"

    def test_get_nonexistent(self) -> None:
        """Test getting nonexistent key."""
        cache = MemoryCache()
        result = cache.get("nonexistent")
        assert result is None

    def test_delete(self) -> None:
        """Test delete operation."""
        cache = MemoryCache()

        entry = CacheEntry(query="test", response="response")
        cache.set("key", entry)

        assert cache.delete("key") is True
        assert cache.get("key") is None
        assert cache.delete("key") is False  # Already deleted

    def test_clear(self) -> None:
        """Test clear operation."""
        cache = MemoryCache()

        cache.set("key1", CacheEntry(query="q1", response="r1"))
        cache.set("key2", CacheEntry(query="q2", response="r2"))

        assert cache.size() == 2
        cache.clear()
        assert cache.size() == 0

    def test_max_entries_eviction(self) -> None:
        """Test eviction when max entries reached."""
        cache = MemoryCache(max_entries=3)

        cache.set("key1", CacheEntry(query="q1", response="r1"))
        cache.set("key2", CacheEntry(query="q2", response="r2"))
        cache.set("key3", CacheEntry(query="q3", response="r3"))
        cache.set("key4", CacheEntry(query="q4", response="r4"))  # Should evict

        assert cache.size() == 3

    def test_access_count(self) -> None:
        """Test that access count is incremented."""
        cache = MemoryCache()

        entry = CacheEntry(query="test", response="response")
        cache.set("key", entry)

        assert cache.get("key").access_count == 1
        assert cache.get("key").access_count == 2