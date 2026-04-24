"""Tests for ApiKeyPoolSelector."""

import asyncio

import pytest

from mini_router.proxy.apikey_selector import ApiKeyPoolSelector
from mini_router.tenant.types import TenantConfig


class TestApiKeyPoolSelector:
    """Test cases for ApiKeyPoolSelector."""

    @pytest.fixture
    def selector(self):
        """Create a fresh selector for each test."""
        return ApiKeyPoolSelector()

    @pytest.fixture
    def tenant_with_pool(self):
        """Create a tenant with apikey_pool."""
        return TenantConfig(
            tenant_id="test-tenant",
            apikey="mgmt-key",
            apikey_pool=["key-a", "key-b", "key-c"],
            base_url_template="http://api/{model}",
        )

    @pytest.fixture
    def tenant_without_pool(self):
        """Create a tenant without apikey_pool."""
        return TenantConfig(
            tenant_id="test-tenant-empty",
            apikey="mgmt-key-only",
            base_url_template="http://api/{model}",
        )

    @pytest.mark.asyncio
    async def test_get_next_apikey_round_robin(self, selector, tenant_with_pool):
        """Test round-robin selection from pool."""
        keys = []
        for _ in range(5):  # Request 5 keys from pool of 3
            key = await selector.get_next_apikey(tenant_with_pool)
            keys.append(key)

        # Should cycle: a, b, c, a, b
        assert keys == ["key-a", "key-b", "key-c", "key-a", "key-b"]

    @pytest.mark.asyncio
    async def test_get_next_apikey_fallback_when_empty(self, selector, tenant_without_pool):
        """Test fallback to management apikey when pool is empty."""
        key = await selector.get_next_apikey(tenant_without_pool)
        assert key == "mgmt-key-only"

    @pytest.mark.asyncio
    async def test_get_next_apikey_empty_pool_explicit(self, selector):
        """Test fallback when pool is explicitly empty list."""
        tenant = TenantConfig(
            tenant_id="test-empty",
            apikey="mgmt-key",
            apikey_pool=[],  # Explicitly empty
            base_url_template="http://api/{model}",
        )
        key = await selector.get_next_apikey(tenant)
        assert key == "mgmt-key"

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, selector):
        """Test that each tenant has independent round-robin index."""
        tenant_a = TenantConfig(
            tenant_id="tenant-a",
            apikey="mgmt-a",
            apikey_pool=["a1", "a2"],
            base_url_template="http://api/{model}",
        )
        tenant_b = TenantConfig(
            tenant_id="tenant-b",
            apikey="mgmt-b",
            apikey_pool=["b1", "b2", "b3"],
            base_url_template="http://api/{model}",
        )

        # Interleave requests
        a_keys = []
        b_keys = []
        for _ in range(4):
            a_keys.append(await selector.get_next_apikey(tenant_a))
            b_keys.append(await selector.get_next_apikey(tenant_b))

        # Tenant A: 2 keys cycle -> a1, a2, a1, a2
        assert a_keys == ["a1", "a2", "a1", "a2"]
        # Tenant B: 3 keys cycle -> b1, b2, b3, b1
        assert b_keys == ["b1", "b2", "b3", "b1"]

    @pytest.mark.asyncio
    async def test_concurrent_access(self, selector, tenant_with_pool):
        """Test thread-safe concurrent access."""
        async def get_keys(count):
            keys = []
            for _ in range(count):
                key = await selector.get_next_apikey(tenant_with_pool)
                keys.append(key)
            return keys

        # Run multiple concurrent tasks
        tasks = [get_keys(3) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # Flatten and check that keys are from pool
        all_keys = [key for result in results for key in result]
        assert all(key in ["key-a", "key-b", "key-c"] for key in all_keys)

        # Total keys = 5 tasks * 3 keys = 15
        assert len(all_keys) == 15

        # Verify distribution is roughly even (round-robin should distribute evenly)
        count_a = all_keys.count("key-a")
        count_b = all_keys.count("key-b")
        count_c = all_keys.count("key-c")
        assert count_a == 5  # Every 3rd key starting from 0
        assert count_b == 5  # Every 3rd key starting from 1
        assert count_c == 5  # Every 3rd key starting from 2

    def test_reset_index(self, selector, tenant_with_pool):
        """Test manual index reset."""
        # Set index by calling get_next_apikey
        asyncio.run(selector.get_next_apikey(tenant_with_pool))
        assert selector.get_current_index("test-tenant") == 1

        # Reset and verify
        selector.reset_index("test-tenant")
        assert selector.get_current_index("test-tenant") == 0

    def test_get_current_index_new_tenant(self, selector):
        """Test getting index for tenant that hasn't been accessed."""
        assert selector.get_current_index("new-tenant") == 0

    @pytest.mark.asyncio
    async def test_single_key_pool(self, selector):
        """Test pool with single key."""
        tenant = TenantConfig(
            tenant_id="single-key-tenant",
            apikey="mgmt-key",
            apikey_pool=["only-key"],
            base_url_template="http://api/{model}",
        )

        keys = []
        for _ in range(5):
            keys.append(await selector.get_next_apikey(tenant))

        # Should always return the same key
        assert all(key == "only-key" for key in keys)
