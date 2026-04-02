"""Latency tracking for model selection.

This module provides latency statistics tracking per model, including:
- Sliding window of recent latency values for percentile calculation
- Exponential moving average for smooth latency estimation
- Thread-safe operations with asyncio locks

Based on the Go implementation in pkg/latency/cache.go
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

# Constants (matching Go implementation)
TPOT_ALPHA = 0.3  # EMA weight: 30% new value, 70% historical
MAX_HISTORY_SIZE = 1000  # Maximum values in sliding window
MIN_OBSERVATIONS_FOR_PERCENTILE = 3  # Min observations for percentile calc


@dataclass
class ModelLatencyStats:
    """Statistics for a single model's latency."""

    # TPOT (Time Per Output Token) - latency per token
    recent_tpots: list[float] = field(default_factory=list)
    average_tpot: float = 0.0
    last_tpot: float = 0.0
    tpot_observation_count: int = 0
    last_tpot_updated: float = 0.0

    # TTFT (Time To First Token) - first token latency
    recent_ttfts: list[float] = field(default_factory=list)
    average_ttft: float = 0.0
    last_ttft: float = 0.0
    ttft_observation_count: int = 0
    last_ttft_updated: float = 0.0

    # General latency (for simple use cases)
    recent_latencies: list[float] = field(default_factory=list)
    average_latency: float = 0.0
    last_latency: float = 0.0
    latency_observation_count: int = 0
    last_latency_updated: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tpot": {
                "average": self.average_tpot,
                "last": self.last_tpot,
                "count": self.tpot_observation_count,
                "recent_count": len(self.recent_tpots),
            },
            "ttft": {
                "average": self.average_ttft,
                "last": self.last_ttft,
                "count": self.ttft_observation_count,
                "recent_count": len(self.recent_ttfts),
            },
            "latency": {
                "average": self.average_latency,
                "last": self.last_latency,
                "count": self.latency_observation_count,
                "recent_count": len(self.recent_latencies),
            },
        }


def _compute_percentile(values: list[float], percentile: float) -> float:
    """Compute percentile from a list of values.

    Args:
        values: List of latency values
        percentile: Percentile to compute (0.0-1.0)

    Returns:
        The percentile value
    """
    if not values:
        return 0.0

    # Sort the values
    sorted_values = sorted(values)

    # Calculate index
    index = percentile * (len(sorted_values) - 1)
    lower = int(index)
    upper = lower + 1

    if upper >= len(sorted_values):
        return sorted_values[-1]

    # Linear interpolation
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


class LatencyTracker:
    """Thread-safe latency tracker for multiple models."""

    def __init__(self, max_history_size: int = MAX_HISTORY_SIZE):
        self._max_history_size = max_history_size
        self._stats: dict[str, ModelLatencyStats] = {}
        self._lock = asyncio.Lock()

    async def update_tpot(self, model: str, tpot: float) -> None:
        """Update TPOT (Time Per Output Token) for a model.

        Args:
            model: Model name
            tpot: TPOT value in seconds
        """
        model = model.strip()
        if not model or tpot <= 0:
            return

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None:
                stats = ModelLatencyStats()
                self._stats[model] = stats

            # Update with exponential moving average
            n = stats.tpot_observation_count + 1
            if n == 1:
                stats.average_tpot = tpot
            else:
                stats.average_tpot = TPOT_ALPHA * tpot + (1 - TPOT_ALPHA) * stats.average_tpot

            stats.last_tpot = tpot
            stats.tpot_observation_count = n
            stats.last_tpot_updated = time.time()

            # Add to sliding window
            stats.recent_tpots.append(tpot)
            if len(stats.recent_tpots) > self._max_history_size:
                stats.recent_tpots = stats.recent_tpots[-self._max_history_size:]

    async def update_ttft(self, model: str, ttft: float) -> None:
        """Update TTFT (Time To First Token) for a model.

        Args:
            model: Model name
            ttft: TTFT value in seconds
        """
        model = model.strip()
        if not model or ttft <= 0:
            return

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None:
                stats = ModelLatencyStats()
                self._stats[model] = stats

            # Update with exponential moving average
            n = stats.ttft_observation_count + 1
            if n == 1:
                stats.average_ttft = ttft
            else:
                stats.average_ttft = TPOT_ALPHA * ttft + (1 - TPOT_ALPHA) * stats.average_ttft

            stats.last_ttft = ttft
            stats.ttft_observation_count = n
            stats.last_ttft_updated = time.time()

            # Add to sliding window
            stats.recent_ttfts.append(ttft)
            if len(stats.recent_ttfts) > self._max_history_size:
                stats.recent_ttfts = stats.recent_ttfts[-self._max_history_size:]

    async def update_latency(self, model: str, latency: float) -> None:
        """Update general latency for a model.

        Args:
            model: Model name
            latency: Latency value in seconds
        """
        model = model.strip()
        if not model or latency <= 0:
            return

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None:
                stats = ModelLatencyStats()
                self._stats[model] = stats

            # Update with exponential moving average
            n = stats.latency_observation_count + 1
            if n == 1:
                stats.average_latency = latency
            else:
                stats.average_latency = TPOT_ALPHA * latency + (1 - TPOT_ALPHA) * stats.average_latency

            stats.last_latency = latency
            stats.latency_observation_count = n
            stats.last_latency_updated = time.time()

            # Add to sliding window
            stats.recent_latencies.append(latency)
            if len(stats.recent_latencies) > self._max_history_size:
                stats.recent_latencies = stats.recent_latencies[-self._max_history_size:]

    async def get_tpot_percentile(self, model: str, percentile: int) -> float | None:
        """Get TPOT percentile for a model.

        Args:
            model: Model name
            percentile: Percentile to get (1-100)

        Returns:
            TPOT percentile value or None if no data
        """
        if percentile < 1 or percentile > 100:
            return None

        model = model.strip()
        if not model:
            return None

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None or not stats.recent_tpots:
                return None

            # Copy the list
            recent_tpots = list(stats.recent_tpots)
            avg = stats.average_tpot
            last = stats.last_tpot

        # For small sample sizes, use average
        if len(recent_tpots) < MIN_OBSERVATIONS_FOR_PERCENTILE:
            return avg if avg > 0 else last

        return _compute_percentile(recent_tpots, percentile / 100.0)

    async def get_ttft_percentile(self, model: str, percentile: int) -> float | None:
        """Get TTFT percentile for a model.

        Args:
            model: Model name
            percentile: Percentile to get (1-100)

        Returns:
            TTFT percentile value or None if no data
        """
        if percentile < 1 or percentile > 100:
            return None

        model = model.strip()
        if not model:
            return None

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None or not stats.recent_ttfts:
                return None

            # Copy the list
            recent_ttfts = list(stats.recent_ttfts)
            avg = stats.average_ttft
            last = stats.last_ttft

        # For small sample sizes, use average
        if len(recent_ttfts) < MIN_OBSERVATIONS_FOR_PERCENTILE:
            return avg if avg > 0 else last

        return _compute_percentile(recent_ttfts, percentile / 100.0)

    async def get_latency_percentile(self, model: str, percentile: int) -> float | None:
        """Get general latency percentile for a model.

        Args:
            model: Model name
            percentile: Percentile to get (1-100)

        Returns:
            Latency percentile value or None if no data
        """
        if percentile < 1 or percentile > 100:
            return None

        model = model.strip()
        if not model:
            return None

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None or not stats.recent_latencies:
                return None

            # Copy the list
            recent_latencies = list(stats.recent_latencies)
            avg = stats.average_latency
            last = stats.last_latency

        # For small sample sizes, use average
        if len(recent_latencies) < MIN_OBSERVATIONS_FOR_PERCENTILE:
            return avg if avg > 0 else last

        return _compute_percentile(recent_latencies, percentile / 100.0)

    async def get_average_tpot(self, model: str) -> float | None:
        """Get average TPOT for a model."""
        model = model.strip()
        if not model:
            return None

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None:
                return None
            return stats.average_tpot if stats.average_tpot > 0 else None

    async def get_average_ttft(self, model: str) -> float | None:
        """Get average TTFT for a model."""
        model = model.strip()
        if not model:
            return None

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None:
                return None
            return stats.average_ttft if stats.average_ttft > 0 else None

    async def get_average_latency(self, model: str) -> float | None:
        """Get average latency for a model."""
        model = model.strip()
        if not model:
            return None

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None:
                return None
            return stats.average_latency if stats.average_latency > 0 else None

    async def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get all model latency statistics."""
        async with self._lock:
            return {model: stats.to_dict() for model, stats in self._stats.items()}

    async def get_model_stats(self, model: str) -> ModelLatencyStats | None:
        """Get stats for a specific model."""
        model = model.strip()
        if not model:
            return None

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None:
                return None
            # Return a copy
            return ModelLatencyStats(
                recent_tpots=list(stats.recent_tpots),
                average_tpot=stats.average_tpot,
                last_tpot=stats.last_tpot,
                tpot_observation_count=stats.tpot_observation_count,
                last_tpot_updated=stats.last_tpot_updated,
                recent_ttfts=list(stats.recent_ttfts),
                average_ttft=stats.average_ttft,
                last_ttft=stats.last_ttft,
                ttft_observation_count=stats.ttft_observation_count,
                last_ttft_updated=stats.last_ttft_updated,
                recent_latencies=list(stats.recent_latencies),
                average_latency=stats.average_latency,
                last_latency=stats.last_latency,
                latency_observation_count=stats.latency_observation_count,
                last_latency_updated=stats.last_latency_updated,
            )

    async def has_sufficient_data(
        self,
        model: str,
        min_observations: int = MIN_OBSERVATIONS_FOR_PERCENTILE,
    ) -> bool:
        """Check if model has sufficient latency data."""
        model = model.strip()
        if not model:
            return False

        async with self._lock:
            stats = self._stats.get(model)
            if stats is None:
                return False
            return stats.latency_observation_count >= min_observations

    async def reset(self) -> None:
        """Reset all latency statistics."""
        async with self._lock:
            self._stats.clear()

    async def remove_model(self, model: str) -> None:
        """Remove a model from tracking."""
        model = model.strip()
        if not model:
            return

        async with self._lock:
            self._stats.pop(model, None)


# Global latency tracker instance
_global_tracker: LatencyTracker | None = None


def get_global_tracker() -> LatencyTracker:
    """Get the global latency tracker instance."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = LatencyTracker()
    return _global_tracker


def set_global_tracker(tracker: LatencyTracker) -> None:
    """Set the global latency tracker instance."""
    global _global_tracker
    _global_tracker = tracker


# Convenience functions using the global tracker
async def update_tpot(model: str, tpot: float) -> None:
    """Update TPOT for a model using the global tracker."""
    await get_global_tracker().update_tpot(model, tpot)


async def update_ttft(model: str, ttft: float) -> None:
    """Update TTFT for a model using the global tracker."""
    await get_global_tracker().update_ttft(model, ttft)


async def update_latency(model: str, latency: float) -> None:
    """Update latency for a model using the global tracker."""
    await get_global_tracker().update_latency(model, latency)


async def get_latency_percentile(model: str, percentile: int) -> float | None:
    """Get latency percentile for a model using the global tracker."""
    return await get_global_tracker().get_latency_percentile(model, percentile)


async def get_average_latency(model: str) -> float | None:
    """Get average latency for a model using the global tracker."""
    return await get_global_tracker().get_average_latency(model)


async def get_all_latency_stats() -> dict[str, dict[str, Any]]:
    """Get all model latency statistics using the global tracker."""
    return await get_global_tracker().get_all_stats()


async def reset_latency() -> None:
    """Reset all latency statistics in the global tracker."""
    await get_global_tracker().reset()
