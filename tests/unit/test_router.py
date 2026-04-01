"""Tests for main router."""

import pytest

from mini_router.config.config import (
    Decision,
    DecisionAction,
    KeywordRule,
    ModelRef,
    Operator,
    RouterConfig,
    RuleNode,
    RuleType,
)
from mini_router.router.router import Router, RoutingRequest


class TestRouter:
    """Tests for Router."""

    @pytest.mark.asyncio
    async def test_basic_routing(self, basic_config: RouterConfig) -> None:
        """Test basic routing flow."""
        router = Router(basic_config)

        result = await router.route(RoutingRequest(query="How do I debug this code?"))

        assert result.cache_hit is False
        assert result.selected_model == "codellama-70b"
        assert result.decision_name == "route_to_code_model"
        assert "code_related" in result.matched_rules

    @pytest.mark.asyncio
    async def test_no_matching_decision(self, basic_config: RouterConfig) -> None:
        """Test when no decision matches."""
        router = Router(basic_config)

        result = await router.route(RoutingRequest(query="What is the weather today?"))

        assert result.selected_model is None
        assert result.decision_name is None

    @pytest.mark.asyncio
    async def test_reject_action(self) -> None:
        """Test reject action."""
        config = RouterConfig(
            models={
                "base_url": "http://localhost:8000/v1",
            },
            signals={
                "keyword_rules": [
                    KeywordRule(
                        name="blocked",
                        keywords=["blocked_word"],
                        operator=Operator.ANY,
                    ),
                ],
            },
            decisions=[
                Decision(
                    name="reject_blocked",
                    priority=100,
                    rules=RuleNode(type=RuleType.KEYWORD, name="blocked"),
                    model_refs=[],
                    action=DecisionAction.REJECT,
                    reject_message="Content blocked",
                ),
            ],
            cache={"enabled": False},
        )

        router = Router(config)
        result = await router.route(RoutingRequest(query="This contains blocked_word"))

        assert result.action == DecisionAction.REJECT
        assert result.reject_message == "Content blocked"

    @pytest.mark.asyncio
    async def test_cache_set_and_hit(self, basic_config: RouterConfig) -> None:
        """Test cache set and hit."""
        # Enable cache for this test
        basic_config.cache.enabled = True

        router = Router(basic_config)

        # Set cache
        await router.set_cache("cached query", "cached response")

        # Should get cache hit
        result = await router.route(RoutingRequest(query="cached query"))
        assert result.cache_hit is True
        assert result.cache_response == "cached response"

    @pytest.mark.asyncio
    async def test_clear_cache(self, basic_config: RouterConfig) -> None:
        """Test cache clearing."""
        basic_config.cache.enabled = True
        router = Router(basic_config)

        await router.set_cache("query", "response")
        router.clear_cache()

        result = await router.route(RoutingRequest(query="query"))
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_priority_ordering(self) -> None:
        """Test that higher priority decisions are evaluated first."""
        config = RouterConfig(
            models={"base_url": "http://localhost:8000/v1"},
            signals={
                "keyword_rules": [
                    KeywordRule(name="code", keywords=["code"], operator=Operator.ANY),
                    KeywordRule(name="urgent", keywords=["urgent"], operator=Operator.ANY),
                ],
            },
            decisions=[
                Decision(
                    name="urgent_route",
                    priority=100,
                    rules=RuleNode(type=RuleType.KEYWORD, name="urgent"),
                    model_refs=[ModelRef(model="urgent-model", weight=1.0)],
                ),
                Decision(
                    name="code_route",
                    priority=10,
                    rules=RuleNode(type=RuleType.KEYWORD, name="code"),
                    model_refs=[ModelRef(model="code-model", weight=1.0)],
                ),
            ],
            cache={"enabled": False},
        )

        router = Router(config)

        # Both keywords match, but urgent has higher priority
        result = await router.route(RoutingRequest(query="urgent code request"))
        assert result.decision_name == "urgent_route"