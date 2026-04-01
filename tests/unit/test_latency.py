"""Tests for latency tracking and LatencyAwareSelector."""

import asyncio

import pytest

from mini_router.algorithm.selector import LatencyAwareSelector, Registry
from mini_router.algorithm.types import SelectionContext, SelectionMethod
from mini_router.config.config import ModelRef
from mini_router.metrics.latency import LatencyTracker


@pytest.fixture
def tracker() -> LatencyTracker:
    """Create a fresh latency tracker for each test."""
    return LatencyTracker()


@pytest.fixture
def selector(tracker: LatencyTracker) -> LatencyAwareSelector:
    """Create a latency-aware selector with a fresh tracker."""
    return LatencyAwareSelector(tracker)


class TestLatencyTracker:
    """Tests for LatencyTracker."""

    @pytest.mark.asyncio
    async def test_update_latency(self, tracker: LatencyTracker) -> None:
        """Test updating latency."""
        await tracker.update_latency("model-a", 1.0)
        await tracker.update_latency("model-a", 2.0)

        stats = await tracker.get_model_stats("model-a")
        assert stats is not None
        assert stats.latency_observation_count == 2
        assert stats.last_latency == 2.0

    @pytest.mark.asyncio
    async def test_average_latency(self, tracker: LatencyTracker) -> None:
        """Test average latency calculation with EMA."""
        await tracker.update_latency("model-a", 1.0)
        avg = await tracker.get_average_latency("model-a")
        assert avg == 1.0

        await tracker.update_latency("model-a", 2.0)
        avg = await tracker.get_average_latency("model-a")
        # EMA: 0.3 * 2.0 + 0.7 * 1.0 = 1.3
        assert abs(avg - 1.3) < 0.01

    @pytest.mark.asyncio
    async def test_latency_percentile(self, tracker: LatencyTracker) -> None:
        """Test latency percentile calculation."""
        # Add multiple values
        for i in range(1, 11):  # 1, 2, 3, ..., 10
            await tracker.update_latency("model-a", float(i))

        # Test p50 (median)
        p50 = await tracker.get_latency_percentile("model-a", 50)
        assert p50 is not None
        assert 5.0 <= p50 <= 6.0  # Median should be around 5.5

        # Test p90
        p90 = await tracker.get_latency_percentile("model-a", 90)
        assert p90 is not None
        assert p90 >= 9.0  # p90 should be high

    @pytest.mark.asyncio
    async def test_tpot_tracking(self, tracker: LatencyTracker) -> None:
        """Test TPOT (Time Per Output Token) tracking."""
        await tracker.update_tpot("model-a", 0.05)
        await tracker.update_tpot("model-a", 0.10)

        stats = await tracker.get_model_stats("model-a")
        assert stats is not None
        assert stats.tpot_observation_count == 2

        tpot = await tracker.get_tpot_percentile("model-a", 50)
        assert tpot is not None

    @pytest.mark.asyncio
    async def test_ttft_tracking(self, tracker: LatencyTracker) -> None:
        """Test TTFT (Time To First Token) tracking."""
        await tracker.update_ttft("model-a", 0.3)
        await tracker.update_ttft("model-a", 0.5)

        stats = await tracker.get_model_stats("model-a")
        assert stats is not None
        assert stats.ttft_observation_count == 2

        ttft = await tracker.get_ttft_percentile("model-a", 50)
        assert ttft is not None

    @pytest.mark.asyncio
    async def test_get_all_stats(self, tracker: LatencyTracker) -> None:
        """Test getting all latency statistics."""
        await tracker.update_latency("model-a", 1.0)
        await tracker.update_latency("model-b", 2.0)

        all_stats = await tracker.get_all_stats()
        assert "model-a" in all_stats
        assert "model-b" in all_stats

    @pytest.mark.asyncio
    async def test_reset(self, tracker: LatencyTracker) -> None:
        """Test resetting tracker."""
        await tracker.update_latency("model-a", 1.0)
        await tracker.reset()

        stats = await tracker.get_model_stats("model-a")
        assert stats is None

    @pytest.mark.asyncio
    async def test_remove_model(self, tracker: LatencyTracker) -> None:
        """Test removing a model from tracking."""
        await tracker.update_latency("model-a", 1.0)
        await tracker.update_latency("model-b", 2.0)

        await tracker.remove_model("model-a")

        stats_a = await tracker.get_model_stats("model-a")
        stats_b = await tracker.get_model_stats("model-b")

        assert stats_a is None
        assert stats_b is not None

    @pytest.mark.asyncio
    async def test_has_sufficient_data(self, tracker: LatencyTracker) -> None:
        """Test checking sufficient data."""
        assert not await tracker.has_sufficient_data("model-a", min_observations=3)

        await tracker.update_latency("model-a", 1.0)
        assert not await tracker.has_sufficient_data("model-a", min_observations=3)

        await tracker.update_latency("model-a", 2.0)
        await tracker.update_latency("model-a", 3.0)
        assert await tracker.has_sufficient_data("model-a", min_observations=3)


class TestLatencyAwareSelector:
    """Tests for LatencyAwareSelector."""

    @pytest.mark.asyncio
    async def test_select_with_latency_data(self, selector: LatencyAwareSelector, tracker: LatencyTracker) -> None:
        """Test selection with latency data available."""
        # Add latency data for two models
        for _ in range(5):
            await tracker.update_latency("model-a", 1.0)  # Faster
            await tracker.update_latency("model-b", 2.0)  # Slower

        candidates = [
            ModelRef(model="model-a", weight=0.5),
            ModelRef(model="model-b", weight=1.0),
        ]

        context = SelectionContext(
            query="test query",
            candidate_models=candidates,
            latency_percentile=50,
            weight_blend=0.0,  # Pure latency-based selection
        )

        result = await selector.select(context)

        # Should select model-a (lower latency)
        assert result.selected_model == "model-a"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_select_fallback_to_weight(self, selector: LatencyAwareSelector) -> None:
        """Test fallback to weight-based selection when no latency data."""
        candidates = [
            ModelRef(model="model-a", weight=1.0),
            ModelRef(model="model-b", weight=0.5),
        ]

        context = SelectionContext(
            query="test query",
            candidate_models=candidates,
            fallback_to_weight=True,
        )

        result = await selector.select(context)

        # Should still return a result (fallback to weight)
        assert result.selected_model in ["model-a", "model-b"]

    @pytest.mark.asyncio
    async def test_select_no_fallback_raises(self, selector: LatencyAwareSelector) -> None:
        """Test that selection raises when no latency data and no fallback."""
        candidates = [
            ModelRef(model="model-a", weight=1.0),
            ModelRef(model="model-b", weight=0.5),
        ]

        context = SelectionContext(
            query="test query",
            candidate_models=candidates,
            fallback_to_weight=False,
        )

        with pytest.raises(ValueError, match="No latency data"):
            await selector.select(context)

    @pytest.mark.asyncio
    async def test_select_single_candidate(self, selector: LatencyAwareSelector) -> None:
        """Test selection with single candidate."""
        candidates = [ModelRef(model="model-a", weight=1.0)]

        context = SelectionContext(
            query="test query",
            candidate_models=candidates,
        )

        result = await selector.select(context)
        assert result.selected_model == "model-a"

    @pytest.mark.asyncio
    async def test_select_with_weight_blend(self, selector: LatencyAwareSelector, tracker: LatencyTracker) -> None:
        """Test selection with weight blending."""
        # Model-a has lower latency but lower weight
        for _ in range(5):
            await tracker.update_latency("model-a", 1.0)  # Faster
            await tracker.update_latency("model-b", 2.0)  # Slower

        candidates = [
            ModelRef(model="model-a", weight=0.3),  # Lower weight
            ModelRef(model="model-b", weight=1.0),  # Higher weight
        ]

        # With pure latency (weight_blend=0), should select model-a
        context = SelectionContext(
            query="test query",
            candidate_models=candidates,
            weight_blend=0.0,
        )

        result = await selector.select(context)
        assert result.selected_model == "model-a"

    @pytest.mark.asyncio
    async def test_select_with_tpot_ttft(self, selector: LatencyAwareSelector, tracker: LatencyTracker) -> None:
        """Test selection considering TPOT and TTFT."""
        # Model-a: lower latency but higher TPOT
        for _ in range(5):
            await tracker.update_latency("model-a", 1.0)
            await tracker.update_tpot("model-a", 0.1)
            await tracker.update_ttft("model-a", 0.5)

            await tracker.update_latency("model-b", 1.5)
            await tracker.update_tpot("model-b", 0.05)  # Better TPOT
            await tracker.update_ttft("model-b", 0.3)   # Better TTFT

        candidates = [
            ModelRef(model="model-a", weight=1.0),
            ModelRef(model="model-b", weight=1.0),
        ]

        context = SelectionContext(
            query="test query",
            candidate_models=candidates,
            latency_percentile=50,
            tpot_percentile=50,
            ttft_percentile=50,
        )

        result = await selector.select(context)
        assert result.selected_model in ["model-a", "model-b"]

    @pytest.mark.asyncio
    async def test_no_candidates_raises(self, selector: LatencyAwareSelector) -> None:
        """Test that selection raises with no candidates."""
        context = SelectionContext(
            query="test query",
            candidate_models=[],
        )

        with pytest.raises(ValueError, match="No candidate models"):
            await selector.select(context)


class TestRegistry:
    """Tests for Registry with LatencyAwareSelector."""

    @pytest.mark.asyncio
    async def test_latency_aware_selection(self, tracker: LatencyTracker) -> None:
        """Test latency-aware selection through registry."""
        registry = Registry(latency_tracker=tracker)

        # Add latency data
        for _ in range(5):
            await tracker.update_latency("model-a", 1.0)
            await tracker.update_latency("model-b", 2.0)

        candidates = [
            ModelRef(model="model-a", weight=1.0),
            ModelRef(model="model-b", weight=1.0),
        ]

        context = SelectionContext(
            query="test query",
            candidate_models=candidates,
            fallback_to_weight=True,
            weight_blend=0.0,  # Pure latency-based selection
        )

        result = await registry.select(SelectionMethod.LATENCY_AWARE, context)
        assert result.selected_model == "model-a"

    @pytest.mark.asyncio
    async def test_static_selection_still_works(self, tracker: LatencyTracker) -> None:
        """Test that static selection still works."""
        registry = Registry(latency_tracker=tracker)

        candidates = [
            ModelRef(model="model-a", weight=1.0),
            ModelRef(model="model-b", weight=1.0),
        ]

        context = SelectionContext(
            query="test query",
            candidate_models=candidates,
        )

        result = await registry.select(SelectionMethod.STATIC, context)
        assert result.selected_model in ["model-a", "model-b"]


class TestSlidingWindow:
    """Tests for sliding window functionality."""

    @pytest.mark.asyncio
    async def test_sliding_window_limit(self) -> None:
        """Test that sliding window is limited to max size."""
        tracker = LatencyTracker(max_history_size=10)

        # Add more values than max
        for i in range(20):
            await tracker.update_latency("model-a", float(i))

        stats = await tracker.get_model_stats("model-a")
        assert stats is not None
        assert len(stats.recent_latencies) == 10
        # Should keep the most recent values
        assert stats.last_latency == 19.0