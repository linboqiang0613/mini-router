"""Unit tests for API key selection strategies."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx

from mini_router.proxy.strategies import (
    ApiKeyStrategy,
    RoundRobinStrategy,
    FallbackStrategy,
    create_apikey_strategy,
)
from mini_router.proxy.apikey_selector import ApiKeyPoolSelector


@pytest.fixture
def pool():
    """Sample API key pool."""
    return ["sk-key-1", "sk-key-2", "sk-key-3"]


@pytest.fixture
def selector():
    """ApiKeyPoolSelector instance."""
    return ApiKeyPoolSelector()


@pytest.fixture
def tenant_id():
    """Sample tenant ID."""
    return "tenant-001"


class TestApiKeyStrategyInterface:
    """Tests for ApiKeyStrategy abstract interface."""

    def test_strategy_has_select_key_method(self):
        """Strategy must have select_key method."""
        assert hasattr(ApiKeyStrategy, "select_key")

    def test_strategy_has_next_key_on_error_method(self):
        """Strategy must have next_key_on_error method."""
        assert hasattr(ApiKeyStrategy, "next_key_on_error")

    def test_cannot_instantiate_abstract_class(self):
        """ApiKeyStrategy cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ApiKeyStrategy()


class TestRoundRobinStrategy:
    """Tests for RoundRobinStrategy."""

    @pytest.mark.asyncio
    async def test_select_key_returns_first_key(self, pool, selector, tenant_id):
        """select_key returns first key from pool (stateful rotation)."""
        strategy = RoundRobinStrategy(selector)
        key1 = await strategy.select_key(pool, tenant_id)
        assert key1 == "sk-key-1"

    @pytest.mark.asyncio
    async def test_select_key_rotates_on_second_call(self, pool, selector, tenant_id):
        """select_key rotates to next key on subsequent calls."""
        strategy = RoundRobinStrategy(selector)
        key1 = await strategy.select_key(pool, tenant_id)
        key2 = await strategy.select_key(pool, tenant_id)
        key3 = await strategy.select_key(pool, tenant_id)
        key4 = await strategy.select_key(pool, tenant_id)

        assert key1 == "sk-key-1"
        assert key2 == "sk-key-2"
        assert key3 == "sk-key-3"
        assert key4 == "sk-key-1"  # Wraps around

    @pytest.mark.asyncio
    async def test_select_key_empty_pool_returns_empty(self, selector, tenant_id):
        """select_key returns empty string for empty pool."""
        strategy = RoundRobinStrategy(selector)
        assert await strategy.select_key([], tenant_id) == ""

    def test_next_key_on_error_returns_none(self, pool, selector):
        """RoundRobin does not retry on error."""
        strategy = RoundRobinStrategy(selector)
        error = httpx.HTTPStatusError("429", request=None, response=httpx.Response(429))
        assert strategy.next_key_on_error(pool, "sk-key-1", error) is None

    def test_next_key_on_error_429_returns_none(self, pool, selector):
        """RoundRobin ignores 429 errors."""
        strategy = RoundRobinStrategy(selector)
        error = httpx.HTTPStatusError("429", request=None, response=httpx.Response(429))
        assert strategy.next_key_on_error(pool, "sk-key-1", error) is None

    def test_next_key_on_error_other_error_returns_none(self, pool, selector):
        """RoundRobin ignores any error."""
        strategy = RoundRobinStrategy(selector)
        error = httpx.HTTPStatusError("500", request=None, response=httpx.Response(500))
        assert strategy.next_key_on_error(pool, "sk-key-1", error) is None


class TestFallbackStrategy:
    """Tests for FallbackStrategy."""

    @pytest.mark.asyncio
    async def test_select_key_returns_first_key(self, pool, tenant_id):
        """select_key returns first key from pool."""
        strategy = FallbackStrategy()
        assert await strategy.select_key(pool, tenant_id) == "sk-key-1"

    @pytest.mark.asyncio
    async def test_select_key_always_returns_first(self, pool, tenant_id):
        """select_key always returns first key (no state)."""
        strategy = FallbackStrategy()
        key1 = await strategy.select_key(pool, tenant_id)
        key2 = await strategy.select_key(pool, tenant_id)
        assert key1 == "sk-key-1"
        assert key2 == "sk-key-1"  # Always first

    @pytest.mark.asyncio
    async def test_select_key_empty_pool_returns_empty(self, tenant_id):
        """select_key returns empty string for empty pool."""
        strategy = FallbackStrategy()
        assert await strategy.select_key([], tenant_id) == ""

    def test_next_key_on_error_429_returns_next_key(self, pool):
        """429 error triggers fallback to next key."""
        strategy = FallbackStrategy()
        error = httpx.HTTPStatusError("429", request=None, response=httpx.Response(429))
        assert strategy.next_key_on_error(pool, "sk-key-1", error) == "sk-key-2"

    def test_next_key_on_error_429_last_key_returns_none(self, pool):
        """429 on last key returns None."""
        strategy = FallbackStrategy()
        error = httpx.HTTPStatusError("429", request=None, response=httpx.Response(429))
        assert strategy.next_key_on_error(pool, "sk-key-3", error) is None

    def test_next_key_on_error_non_429_returns_none(self, pool):
        """Non-429 errors don't trigger fallback."""
        strategy = FallbackStrategy()
        error = httpx.HTTPStatusError("500", request=None, response=httpx.Response(500))
        assert strategy.next_key_on_error(pool, "sk-key-1", error) is None

    def test_next_key_on_error_other_exception_returns_none(self, pool):
        """Non-HTTPStatusError exceptions don't trigger fallback."""
        strategy = FallbackStrategy()
        error = ValueError("some error")
        assert strategy.next_key_on_error(pool, "sk-key-1", error) is None

    def test_next_key_on_error_key_not_in_pool_returns_none(self, pool):
        """Key not in pool returns None."""
        strategy = FallbackStrategy()
        error = httpx.HTTPStatusError("429", request=None, response=httpx.Response(429))
        assert strategy.next_key_on_error(pool, "sk-unknown", error) is None


class TestCreateApiKeyStrategy:
    """Tests for create_apikey_strategy factory."""

    def test_factory_creates_fallback_strategy(self, selector):
        """Factory with 'fallback' mode returns FallbackStrategy."""
        strategy = create_apikey_strategy("fallback", selector)
        assert isinstance(strategy, FallbackStrategy)

    def test_factory_creates_round_robin_strategy(self, selector):
        """Factory with 'round_robin' mode returns RoundRobinStrategy."""
        strategy = create_apikey_strategy("round_robin", selector)
        assert isinstance(strategy, RoundRobinStrategy)

    def test_factory_defaults_to_round_robin(self, selector):
        """Factory with None mode returns RoundRobinStrategy."""
        strategy = create_apikey_strategy(None, selector)
        assert isinstance(strategy, RoundRobinStrategy)

    def test_factory_unknown_mode_defaults_to_round_robin(self, selector):
        """Factory with unknown mode returns RoundRobinStrategy."""
        strategy = create_apikey_strategy("unknown", selector)
        assert isinstance(strategy, RoundRobinStrategy)


class TestStrategySelectionViaParameter:
    """Tests for strategy selection via parameter in ChatProxy."""

    @pytest.mark.asyncio
    async def test_chat_with_explicit_fallback_strategy(self):
        """chat() accepts strategy parameter."""
        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import ChatRequest, ChatMessage
        from mini_router.router.router import Router
        from mini_router.signal_layer.classifier import OpenAIClient

        mock_router = MagicMock(spec=Router)
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock(spec=OpenAIClient)

        async def mock_chat(model, messages, base_url, api_key, **kwargs):
            return {"id": "test", "choices": [{"message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}]}

        mock_client.chat_completion = mock_chat

        proxy = ChatProxy(mock_router, mock_client)

        from mini_router.tenant.types import TenantConfig

        tenant = TenantConfig(
            tenant_id="test",
            apikey="sk-mgmt",
            apikey_pool=["sk-1", "sk-2"],
            apikey_pool_mode="round_robin",  # Config says round_robin
            base_url_template="http://api.com/{model}/v1",
            enabled=True,
        )

        # But we pass fallback strategy explicitly
        strategy = FallbackStrategy()

        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False)

        response = await proxy.chat(request, tenant=tenant, strategy=strategy)

        assert response.choices[0].message.content == "Hello"

    @pytest.mark.asyncio
    async def test_backward_compatibility_with_tenant_config(self):
        """chat() uses tenant.apikey_pool_mode when strategy not provided."""
        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import ChatRequest, ChatMessage
        from mini_router.router.router import Router
        from mini_router.signal_layer.classifier import OpenAIClient

        mock_router = MagicMock(spec=Router)
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock(spec=OpenAIClient)

        used_keys = []

        async def mock_chat(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            return {"id": "test", "choices": [{"message": {"role": "assistant", "content": "Success"}, "finish_reason": "stop"}]}

        mock_client.chat_completion = mock_chat

        proxy = ChatProxy(mock_router, mock_client)

        from mini_router.tenant.types import TenantConfig

        # Tenant with fallback mode
        tenant = TenantConfig(
            tenant_id="test",
            apikey="sk-mgmt",
            apikey_pool=["sk-1", "sk-2"],
            apikey_pool_mode="fallback",
            base_url_template="http://api.com/{model}/v1",
            enabled=True,
        )

        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False)

        response = await proxy.chat(request, tenant=tenant)

        # Should use first key (fallback mode selects first)
        assert used_keys[0] == "sk-1"