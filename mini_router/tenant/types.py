"""Tenant configuration types."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from mini_router.config.config import Decision


class TenantConfig(BaseModel):
    """Configuration for a single tenant."""

    tenant_id: str = Field(..., description="Unique tenant identifier")
    apikey: str = Field(..., description="API key for authentication")
    apikey_pool: list[str] = Field(
        default_factory=list,
        description="Pool of API keys for calling LLM services (rotated per request)",
    )
    apikey_pool_mode: str = Field(
        "round_robin",
        description="API key selection mode: 'round_robin' (rotate per request) or 'fallback' (switch on 429)",
    )
    name: str | None = Field(None, description="Human-readable tenant name")
    enabled: bool = Field(True, description="Whether tenant is enabled")
    base_url_template: str = Field(
        ...,
        description="URL template with {model} placeholder, e.g., http://api.com/llm/{model}/v1",
    )
    timeout: float = Field(120.0, description="Request timeout in seconds")
    decisions: list[Decision] = Field(
        default_factory=list, description="Tenant-specific routing decisions"
    )
    created_at: datetime | None = Field(None, description="Creation timestamp")
    updated_at: datetime | None = Field(None, description="Last update timestamp")


class TenantCreateRequest(BaseModel):
    """Request body for creating a tenant."""

    tenant_id: str
    apikey: str
    apikey_pool: list[str] = Field(default_factory=list)
    apikey_pool_mode: str = "round_robin"
    name: str | None = None
    enabled: bool = True
    base_url_template: str
    timeout: float = 120.0
    decisions: list[Decision] = Field(default_factory=list)


class TenantUpdateRequest(BaseModel):
    """Request body for updating a tenant (partial update)."""

    apikey: str | None = None
    apikey_pool: list[str] | None = None
    apikey_pool_mode: str | None = None
    name: str | None = None
    enabled: bool | None = None
    base_url_template: str | None = None
    timeout: float | None = None
    decisions: list[Decision] | None = None


class TenantResponse(BaseModel):
    """Response model for tenant API."""

    tenant_id: str
    apikey: str  # Will be masked in response
    apikey_pool_size: int  # Number of keys in pool (not the actual keys)
    apikey_pool_mode: str  # API key selection mode
    name: str | None
    enabled: bool
    base_url_template: str
    timeout: float
    decisions: list[Decision]
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_config(cls, config: TenantConfig, mask_apikey: bool = True) -> "TenantResponse":
        """Create response from TenantConfig with optional apikey masking."""
        apikey = config.apikey
        if mask_apikey and len(apikey) > 6:
            apikey = apikey[:6] + "***"

        return cls(
            tenant_id=config.tenant_id,
            apikey=apikey,
            apikey_pool_size=len(config.apikey_pool),
            apikey_pool_mode=config.apikey_pool_mode,
            name=config.name,
            enabled=config.enabled,
            base_url_template=config.base_url_template,
            timeout=config.timeout,
            decisions=config.decisions,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: dict[str, Any] = Field(..., description="Error details with type, message, code")


def build_base_url(template: str, model: str) -> str:
    """Build actual URL from template and model name.

    Args:
        template: URL template with {model} placeholder
        model: Model name to substitute

    Returns:
        Actual URL with model substituted

    Example:
        >>> build_base_url("http://api.com/llm/{model}/v1", "gpt-4")
        'http://api.com/llm/gpt-4/v1'
    """
    return template.replace("{model}", model)
