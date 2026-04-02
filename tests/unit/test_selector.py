"""Tests for model selectors."""

import pytest

from mini_router.algorithm.selector import Registry, RoundRobinSelector, StaticSelector
from mini_router.algorithm.types import SelectionContext
from mini_router.config.config import ModelRef, SelectionMethod


@pytest.fixture
def candidates() -> list[ModelRef]:
    """Create test candidate models."""
    return [
        ModelRef(model="model-a", weight=1.0),
        ModelRef(model="model-b", weight=0.5),
        ModelRef(model="model-c", weight=0.3),
    ]


class TestStaticSelector:
    """Tests for StaticSelector."""

    @pytest.mark.asyncio
    async def test_single_candidate(self) -> None:
        """Test selection with single candidate."""
        selector = StaticSelector()
        context = SelectionContext(
            query="test",
            candidate_models=[ModelRef(model="only-model", weight=1.0)],
        )

        result = await selector.select(context)
        assert result.selected_model == "only-model"

    @pytest.mark.asyncio
    async def test_weight_based_selection(self, candidates: list[ModelRef]) -> None:
        """Test weight-based probabilistic selection."""
        selector = StaticSelector()
        context = SelectionContext(query="test", candidate_models=candidates)

        # Run multiple times to verify weight distribution
        selections: dict[str, int] = {}
        for _ in range(1000):
            result = await selector.select(context)
            model = result.selected_model
            selections[model] = selections.get(model, 0) + 1

        # model-a (weight 1.0) should be selected most often
        # model-b (weight 0.5) less often
        # model-c (weight 0.3) least often
        assert selections.get("model-a", 0) > selections.get("model-c", 0)


class TestRoundRobinSelector:
    """Tests for RoundRobinSelector."""

    @pytest.mark.asyncio
    async def test_round_robin_order(self, candidates: list[ModelRef]) -> None:
        """Test that selection follows round-robin order."""
        selector = RoundRobinSelector()
        context = SelectionContext(
            query="test",
            candidate_models=candidates,
            metadata={"decision_name": "test"},
        )

        # First three selections should cycle through models
        result1 = await selector.select(context)
        result2 = await selector.select(context)
        result3 = await selector.select(context)
        result4 = await selector.select(context)  # Should wrap around

        assert result1.selected_model == "model-a"
        assert result2.selected_model == "model-b"
        assert result3.selected_model == "model-c"
        assert result4.selected_model == "model-a"  # Wrapped around


class TestRegistry:
    """Tests for selector registry."""

    @pytest.mark.asyncio
    async def test_static_method(self, candidates: list[ModelRef]) -> None:
        """Test registry with static method."""
        registry = Registry()
        context = SelectionContext(query="test", candidate_models=candidates)

        result = await registry.select(SelectionMethod.STATIC, context)
        assert result.selected_model in ["model-a", "model-b", "model-c"]

    @pytest.mark.asyncio
    async def test_round_robin_method(self, candidates: list[ModelRef]) -> None:
        """Test registry with round-robin method."""
        registry = Registry()
        context = SelectionContext(
            query="test",
            candidate_models=candidates,
            metadata={"decision_name": "test"},
        )

        result = await registry.select(SelectionMethod.ROUND_ROBIN, context)
        assert result.selected_model == "model-a"