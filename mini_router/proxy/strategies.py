"""API Key selection strategies.

This module provides strategy pattern implementation for API key selection.
Strategies are responsible only for key selection and retry decisions.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from mini_router.proxy.apikey_selector import ApiKeyPoolSelector


class ApiKeyStrategy(ABC):
    """API Key selection strategy - only responsible for key selection.

    Strategies decide:
    1. Which key to use from the pool (select_key)
    2. Whether to try another key after error (next_key_on_error)

    Strategies do NOT:
    - Make API calls
    - Handle streaming/chunk processing
    - Know about client implementation
    """

    @abstractmethod
    async def select_key(self, pool: list[str], tenant_id: str) -> str:
        """Select an API key from the pool.

        Args:
            pool: List of available API keys
            tenant_id: Tenant ID for state management (round-robin)

        Returns:
            The selected API key
        """
        pass

    @abstractmethod
    def next_key_on_error(
        self, pool: list[str], current_key: str, error: Exception
    ) -> str | None:
        """Return next key to try after error, or None to stop.

        Args:
            pool: List of available API keys
            current_key: The key that failed
            error: The exception that occurred

        Returns:
            Next key to try, or None if should not retry.
        """
        pass


class RoundRobinStrategy(ApiKeyStrategy):
    """Round-robin: rotate keys per request, no retry on error.

    Uses ApiKeyPoolSelector to maintain rotation state across requests.
    On any error, returns None (does not retry with another key).
    """

    def __init__(self, selector: "ApiKeyPoolSelector") -> None:
        """Initialize with selector for round-robin state management.

        Args:
            selector: The ApiKeyPoolSelector instance that tracks rotation state
        """
        self._selector = selector

    async def select_key(self, pool: list[str], tenant_id: str) -> str:
        """Select next key in round-robin sequence using selector state.

        Uses selector.get_next_apikey() to maintain stateful rotation.

        Args:
            pool: List of available API keys
            tenant_id: Tenant ID for state management

        Returns:
            The next key in round-robin sequence
        """
        if not pool:
            return ""

        # Use selector's state management to get next key
        # Note: We need to build a minimal TenantConfig-like object for selector
        from mini_router.tenant.types import TenantConfig

        # Create a temporary tenant config for selector
        temp_tenant = TenantConfig(
            tenant_id=tenant_id,
            apikey="",  # Not used when pool is provided
            apikey_pool=pool,
            apikey_pool_mode="round_robin",
            base_url_template="",  # Not used
            enabled=True,
        )

        return await self._selector.get_next_apikey(temp_tenant)

    def next_key_on_error(
        self, pool: list[str], current_key: str, error: Exception
    ) -> str | None:
        """Round-robin does not retry on error.

        Returns None immediately, allowing caller to raise the error.
        """
        return None


class FallbackStrategy(ApiKeyStrategy):
    """Fallback: use first key, switch to next on 429.

    Always selects first key from pool. On 429 rate limit error,
    returns next key in sequence. On other errors, returns None.
    """

    def __init__(self) -> None:
        """Initialize fallback strategy (no state needed)."""
        pass

    async def select_key(self, pool: list[str], tenant_id: str) -> str:
        """Select first key from pool.

        Args:
            pool: List of available API keys
            tenant_id: Tenant ID (not used by fallback strategy)

        Returns:
            The first API key
        """
        return pool[0] if pool else ""

    def next_key_on_error(
        self, pool: list[str], current_key: str, error: Exception
    ) -> str | None:
        """Return next key only on 429 rate limit error.

        Args:
            pool: List of available API keys
            current_key: The key that was rate limited
            error: The exception (checked for 429 status)

        Returns:
            Next key in pool after current_key if 429, else None
        """
        # Only handle HTTP 429 rate limit errors
        if isinstance(error, httpx.HTTPStatusError):
            if error.response.status_code == 429:
                try:
                    current_idx = pool.index(current_key)
                    if current_idx < len(pool) - 1:
                        return pool[current_idx + 1]
                except ValueError:
                    # Key not in pool (shouldn't happen)
                    pass
        return None


def create_apikey_strategy(
    mode: str | None, selector: "ApiKeyPoolSelector"
) -> ApiKeyStrategy:
    """Factory function to create appropriate strategy based on mode.

    Args:
        mode: Strategy mode name ("round_robin", "fallback", or None)
        selector: ApiKeyPoolSelector instance for round-robin state

    Returns:
        ApiKeyStrategy instance (RoundRobinStrategy or FallbackStrategy)
    """
    if mode == "fallback":
        return FallbackStrategy()
    # Default to round_robin (including None)
    return RoundRobinStrategy(selector)