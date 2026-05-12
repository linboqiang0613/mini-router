"""API Key Pool Selector for round-robin key selection."""

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mini_router.tenant.types import TenantConfig


class ApiKeyPoolSelector:
    """Manages round-robin selection of API keys from tenant pools.

    Maintains an in-memory index per tenant for round-robin selection.
    Thread-safe using asyncio locks.
    """

    def __init__(self) -> None:
        """Initialize the selector with empty state."""
        self._indices: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, tenant_id: str) -> asyncio.Lock:
        """Get or create a lock for the given tenant."""
        if tenant_id not in self._locks:
            self._locks[tenant_id] = asyncio.Lock()
        return self._locks[tenant_id]

    async def get_next_apikey(self, tenant: "TenantConfig") -> str:
        """Get the next API key from the tenant's pool using round-robin.

        If the pool is empty, falls back to the tenant's management apikey.

        Args:
            tenant: The tenant configuration with apikey_pool

        Returns:
            The selected API key for calling LLM services
        """
        # Fallback to management apikey if pool is empty
        if not tenant.apikey_pool:
            return tenant.apikey

        tenant_id = tenant.tenant_id
        lock = self._get_lock(tenant_id)

        async with lock:
            current_index = self._indices.get(tenant_id, 0)
            selected_key = tenant.apikey_pool[current_index]

            # Update index for next call (round-robin)
            next_index = (current_index + 1) % len(tenant.apikey_pool)
            self._indices[tenant_id] = next_index

            return selected_key

    def reset_index(self, tenant_id: str) -> None:
        """Reset the round-robin index for a tenant.

        Useful for testing or manual reset scenarios.

        Args:
            tenant_id: The tenant to reset
        """
        self._indices.pop(tenant_id, None)

    def get_current_index(self, tenant_id: str) -> int:
        """Get the current index for a tenant (for testing/monitoring).

        Args:
            tenant_id: The tenant to check

        Returns:
            The current index in the pool
        """
        return self._indices.get(tenant_id, 0)

    def get_first_apikey(self, tenant: "TenantConfig") -> str:
        """Get the first API key from the pool (for fallback mode).

        Does not modify the round-robin index. If pool is empty,
        falls back to the tenant's management apikey.

        Args:
            tenant: The tenant configuration with apikey_pool

        Returns:
            The first API key for calling LLM services
        """
        if not tenant.apikey_pool:
            return tenant.apikey
        return tenant.apikey_pool[0]

    def get_apikey_at(self, tenant: "TenantConfig", index: int) -> str | None:
        """Get API key at specific index from the pool.

        Args:
            tenant: The tenant configuration with apikey_pool
            index: The index in the pool

        Returns:
            The API key at the index, or None if index is out of bounds
        """
        if not tenant.apikey_pool:
            return tenant.apikey if index == 0 else None
        if 0 <= index < len(tenant.apikey_pool):
            return tenant.apikey_pool[index]
        return None
