# Multi-Tenant API Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-tenant support to mini-router with apikey-based authentication, tenant-specific routing rules, and apikey passthrough to upstream LLM APIs.

**Architecture:** Create a new `tenant` module with `TenantConfig` types and `TenantManager` for CRUD operations. Modify `OpenAIClient` to accept dynamic `base_url` and `api_key` per request. Modify `Router` and `ChatProxy` to use tenant-specific configurations. Add authentication middleware and tenant management API endpoints.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, YAML for persistence

---

## File Structure

```
mini_router/
├── tenant/
│   ├── __init__.py           # Exports
│   ├── types.py              # TenantConfig, TenantCreateRequest, etc.
│   └── manager.py            # TenantManager class
├── config/
│   └── tenants.yaml          # Tenant configuration file (new)
├── client/
│   └── openai_client.py      # Modified: dynamic base_url/api_key
├── router/
│   └── router.py             # Modified: accept tenant decisions
├── proxy/
│   └── chat_proxy.py         # Modified: tenant auth & routing
└── server.py                 # Modified: auth middleware + tenant API

tests/unit/
├── test_tenant_manager.py    # New: TenantManager tests
├── test_tenant_api.py        # New: tenant API endpoint tests
└── test_chat_proxy.py        # Modified: tenant auth tests
```

---

## Task 1: Create Tenant Types

**Files:**
- Create: `mini_router/tenant/__init__.py`
- Create: `mini_router/tenant/types.py`

- [ ] **Step 1: Create tenant module directory**

```bash
mkdir -p mini_router/tenant
```

- [ ] **Step 2: Create `mini_router/tenant/types.py`**

```python
"""Tenant configuration types."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from mini_router.config.config import Decision


class TenantConfig(BaseModel):
    """Configuration for a single tenant."""

    tenant_id: str = Field(..., description="Unique tenant identifier")
    apikey: str = Field(..., description="API key for authentication")
    name: str | None = Field(None, description="Human-readable tenant name")
    enabled: bool = Field(True, description="Whether tenant is enabled")
    base_url_template: str = Field(
        ...,
        description="URL template with {model} placeholder, e.g., http://api.com/llm/{model}/v1"
    )
    timeout: float = Field(120.0, description="Request timeout in seconds")
    decisions: list[Decision] = Field(
        default_factory=list,
        description="Tenant-specific routing decisions"
    )
    created_at: datetime | None = Field(None, description="Creation timestamp")
    updated_at: datetime | None = Field(None, description="Last update timestamp")


class TenantCreateRequest(BaseModel):
    """Request body for creating a tenant."""

    tenant_id: str
    apikey: str
    name: str | None = None
    enabled: bool = True
    base_url_template: str
    timeout: float = 120.0
    decisions: list[Decision] = Field(default_factory=list)


class TenantUpdateRequest(BaseModel):
    """Request body for updating a tenant (partial update)."""

    apikey: str | None = None
    name: str | None = None
    enabled: bool | None = None
    base_url_template: str | None = None
    timeout: float | None = None
    decisions: list[Decision] | None = None


class TenantResponse(BaseModel):
    """Response model for tenant API."""

    tenant_id: str
    apikey: str  # Will be masked in response
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

    error: dict[str, Any] = Field(
        ...,
        description="Error details with type, message, code"
    )


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
```

- [ ] **Step 3: Create `mini_router/tenant/__init__.py`**

```python
"""Tenant management module."""

from mini_router.tenant.types import (
    TenantConfig,
    TenantCreateRequest,
    TenantResponse,
    TenantUpdateRequest,
    build_base_url,
)

__all__ = [
    "TenantConfig",
    "TenantCreateRequest",
    "TenantResponse",
    "TenantUpdateRequest",
    "build_base_url",
]
```

- [ ] **Step 4: Commit**

```bash
git add mini_router/tenant/
git commit -m "feat: add tenant types module"
```

---

## Task 2: Create TenantManager

**Files:**
- Create: `mini_router/tenant/manager.py`
- Create: `config/tenants.yaml` (initial empty file)
- Create: `tests/unit/test_tenant_manager.py`

- [ ] **Step 1: Write failing tests for TenantManager**

Create `tests/unit/test_tenant_manager.py`:

```python
"""Tests for TenantManager."""

import tempfile
from pathlib import Path

import pytest

from mini_router.config.config import Decision, ModelRef, RuleNode, RuleType
from mini_router.tenant.manager import TenantManager
from mini_router.tenant.types import TenantConfig


@pytest.fixture
def temp_tenants_file():
    """Create a temporary tenants.yaml file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("tenants: []\n")
        yield f.name
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def sample_tenant():
    """Create a sample tenant config."""
    return TenantConfig(
        tenant_id="test-tenant",
        apikey="sk-test-123",
        name="Test Tenant",
        enabled=True,
        base_url_template="http://api.example.com/llm/{model}/v1",
        timeout=60.0,
        decisions=[
            Decision(
                name="default_route",
                priority=0,
                rules=RuleNode(type=RuleType.OR, children=[]),
                model_refs=[ModelRef(model="gpt-4", weight=1.0)],
            )
        ],
    )


class TestTenantManagerLoadSave:
    def test_load_empty_file(self, temp_tenants_file):
        """Test loading an empty tenants file."""
        manager = TenantManager(temp_tenants_file)
        manager.load()
        assert manager.list_all() == []

    def test_save_and_load(self, temp_tenants_file, sample_tenant):
        """Test saving and loading tenants."""
        manager = TenantManager(temp_tenants_file)
        manager.create(sample_tenant)

        # Create new manager to test persistence
        manager2 = TenantManager(temp_tenants_file)
        manager2.load()
        tenants = manager2.list_all()
        assert len(tenants) == 1
        assert tenants[0].tenant_id == "test-tenant"


class TestTenantManagerCRUD:
    def test_create_tenant(self, temp_tenants_file, sample_tenant):
        """Test creating a tenant."""
        manager = TenantManager(temp_tenants_file)
        manager.create(sample_tenant)
        assert manager.get_by_id("test-tenant") is not None

    def test_get_by_apikey(self, temp_tenants_file, sample_tenant):
        """Test getting tenant by apikey."""
        manager = TenantManager(temp_tenants_file)
        manager.create(sample_tenant)
        tenant = manager.get_by_apikey("sk-test-123")
        assert tenant is not None
        assert tenant.tenant_id == "test-tenant"

    def test_get_by_apikey_not_found(self, temp_tenants_file):
        """Test getting non-existent apikey."""
        manager = TenantManager(temp_tenants_file)
        manager.load()
        assert manager.get_by_apikey("invalid-key") is None

    def test_update_tenant(self, temp_tenants_file, sample_tenant):
        """Test updating a tenant."""
        manager = TenantManager(temp_tenants_file)
        manager.create(sample_tenant)

        updated = manager.update("test-tenant", {"name": "Updated Name", "timeout": 30.0})
        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.timeout == 30.0

    def test_update_tenant_apikey(self, temp_tenants_file, sample_tenant):
        """Test updating tenant apikey updates index."""
        manager = TenantManager(temp_tenants_file)
        manager.create(sample_tenant)

        manager.update("test-tenant", {"apikey": "sk-new-key"})
        assert manager.get_by_apikey("sk-test-123") is None
        assert manager.get_by_apikey("sk-new-key") is not None

    def test_update_nonexistent_tenant(self, temp_tenants_file):
        """Test updating non-existent tenant."""
        manager = TenantManager(temp_tenants_file)
        manager.load()
        assert manager.update("nonexistent", {"name": "Test"}) is None

    def test_delete_tenant(self, temp_tenants_file, sample_tenant):
        """Test deleting a tenant."""
        manager = TenantManager(temp_tenants_file)
        manager.create(sample_tenant)
        assert manager.delete("test-tenant") is True
        assert manager.get_by_id("test-tenant") is None
        assert manager.get_by_apikey("sk-test-123") is None

    def test_delete_nonexistent_tenant(self, temp_tenants_file):
        """Test deleting non-existent tenant."""
        manager = TenantManager(temp_tenants_file)
        manager.load()
        assert manager.delete("nonexistent") is False


class TestTenantManagerDuplicate:
    def test_create_duplicate_tenant_id(self, temp_tenants_file, sample_tenant):
        """Test creating tenant with duplicate ID raises error."""
        manager = TenantManager(temp_tenants_file)
        manager.create(sample_tenant)
        with pytest.raises(ValueError, match="already exists"):
            manager.create(sample_tenant)

    def test_create_duplicate_apikey(self, temp_tenants_file, sample_tenant):
        """Test creating tenant with duplicate apikey raises error."""
        manager = TenantManager(temp_tenants_file)
        manager.create(sample_tenant)

        duplicate = TenantConfig(
            tenant_id="other-tenant",
            apikey="sk-test-123",  # Same apikey
            base_url_template="http://other.com/llm/{model}/v1",
        )
        with pytest.raises(ValueError, match="apikey.*already in use"):
            manager.create(duplicate)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/test_tenant_manager.py -v
```

Expected: Import errors and test failures

- [ ] **Step 3: Create `mini_router/tenant/manager.py`**

```python
"""Tenant management - CRUD operations and persistence."""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from mini_router.tenant.types import TenantConfig


class TenantManager:
    """Manages tenant configurations with CRUD operations and file persistence."""

    def __init__(self, config_path: str = "config/tenants.yaml") -> None:
        """Initialize TenantManager.

        Args:
            config_path: Path to tenants.yaml file
        """
        self.config_path = config_path
        self._tenants: dict[str, TenantConfig] = {}  # tenant_id -> TenantConfig
        self._apikey_index: dict[str, str] = {}  # apikey -> tenant_id

    def load(self) -> None:
        """Load tenants from YAML file."""
        path = Path(self.config_path)
        if not path.exists():
            # Create empty file
            path.parent.mkdir(parents=True, exist_ok=True)
            self.save()
            return

        with path.open() as f:
            data = yaml.safe_load(f) or {}

        tenants_data = data.get("tenants", [])
        self._tenants.clear()
        self._apikey_index.clear()

        for tenant_data in tenants_data:
            tenant = TenantConfig(**tenant_data)
            self._tenants[tenant.tenant_id] = tenant
            self._apikey_index[tenant.apikey] = tenant.tenant_id

    def save(self) -> None:
        """Save tenants to YAML file."""
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "tenants": [
                tenant.model_dump(mode="json")
                for tenant in self._tenants.values()
            ]
        }

        with path.open("w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def get_by_apikey(self, apikey: str) -> TenantConfig | None:
        """Get tenant by API key.

        Args:
            apikey: The API key to look up

        Returns:
            TenantConfig if found, None otherwise
        """
        tenant_id = self._apikey_index.get(apikey)
        if tenant_id is None:
            return None
        return self._tenants.get(tenant_id)

    def get_by_id(self, tenant_id: str) -> TenantConfig | None:
        """Get tenant by ID.

        Args:
            tenant_id: The tenant identifier

        Returns:
            TenantConfig if found, None otherwise
        """
        return self._tenants.get(tenant_id)

    def list_all(self) -> list[TenantConfig]:
        """List all tenants.

        Returns:
            List of all TenantConfig objects
        """
        return list(self._tenants.values())

    def create(self, tenant: TenantConfig) -> TenantConfig:
        """Create a new tenant.

        Args:
            tenant: Tenant configuration to create

        Returns:
            Created TenantConfig with timestamps

        Raises:
            ValueError: If tenant_id or apikey already exists
        """
        if tenant.tenant_id in self._tenants:
            raise ValueError(f"Tenant '{tenant.tenant_id}' already exists")

        if tenant.apikey in self._apikey_index:
            raise ValueError(f"apikey '{tenant.apikey}' already in use by tenant '{self._apikey_index[tenant.apikey]}'")

        # Set timestamps
        now = datetime.utcnow()
        tenant.created_at = now
        tenant.updated_at = now

        self._tenants[tenant.tenant_id] = tenant
        self._apikey_index[tenant.apikey] = tenant.tenant_id
        self.save()

        return tenant

    def update(self, tenant_id: str, updates: dict[str, Any]) -> TenantConfig | None:
        """Partially update a tenant.

        Args:
            tenant_id: The tenant identifier
            updates: Dictionary of fields to update

        Returns:
            Updated TenantConfig if found, None otherwise
        """
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return None

        # Handle apikey update: update index
        if "apikey" in updates:
            old_apikey = tenant.apikey
            new_apikey = updates["apikey"]

            # Check if new apikey is already used by another tenant
            existing_tenant = self._apikey_index.get(new_apikey)
            if existing_tenant and existing_tenant != tenant_id:
                raise ValueError(f"apikey '{new_apikey}' already in use by tenant '{existing_tenant}'")

            # Update index
            self._apikey_index.pop(old_apikey, None)
            self._apikey_index[new_apikey] = tenant_id

        # Merge updates
        update_data = tenant.model_dump()
        update_data.update(updates)

        # Validate and create updated config
        updated_tenant = TenantConfig(**update_data)
        updated_tenant.updated_at = datetime.utcnow()

        self._tenants[tenant_id] = updated_tenant
        self.save()

        return updated_tenant

    def delete(self, tenant_id: str) -> bool:
        """Delete a tenant.

        Args:
            tenant_id: The tenant identifier

        Returns:
            True if deleted, False if not found
        """
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return False

        # Remove from index
        self._apikey_index.pop(tenant.apikey, None)
        # Remove from tenants
        del self._tenants[tenant_id]
        self.save()

        return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_tenant_manager.py -v
```

Expected: All tests pass

- [ ] **Step 5: Create initial `config/tenants.yaml`**

```yaml
# Tenant configurations
# Managed by TenantManager - do not edit manually
tenants: []
```

- [ ] **Step 6: Commit**

```bash
git add mini_router/tenant/manager.py config/tenants.yaml tests/unit/test_tenant_manager.py
git commit -m "feat: add TenantManager with CRUD and persistence"
```

---

## Task 3: Modify OpenAIClient for Dynamic base_url and api_key

**Files:**
- Modify: `mini_router/client/openai_client.py`
- Modify: `mini_router/client/__init__.py`
- Modify: `tests/unit/test_chat_proxy.py` (update mocks if needed)

- [ ] **Step 1: Write failing test for dynamic client**

Add to `tests/unit/test_chat_proxy.py` or create new test:

```python
# This test verifies the client accepts dynamic base_url/api_key
import pytest
from unittest.mock import AsyncMock, patch

from mini_router.client.openai_client import OpenAIClient


class TestDynamicClient:
    @pytest.mark.asyncio
    async def test_chat_completion_with_dynamic_params(self):
        """Test chat_completion accepts dynamic base_url and api_key."""
        client = OpenAIClient(timeout=60.0)

        with patch.object(client.client, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.json.return_value = {"choices": [{"message": {"content": "test"}}]}
            mock_response.raise_for_status = AsyncMock()
            mock_post.return_value = mock_response

            result = await client.chat_completion(
                base_url="http://dynamic-api.com/v1",
                api_key="dynamic-key",
                model="gpt-4",
                messages=[{"role": "user", "content": "Hello"}],
            )

            # Verify the call was made with correct URL
            call_args = mock_post.call_args
            assert call_args[0][0] == "http://dynamic-api.com/v1/chat/completions"
            assert "Bearer dynamic-key" in call_args[1]["headers"]["Authorization"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_chat_proxy.py::TestDynamicClient -v
```

Expected: Test fails due to missing parameters

- [ ] **Step 3: Modify `mini_router/client/openai_client.py`**

Replace the entire file with:

```python
"""OpenAI-compatible API client."""

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


class OpenAIClient:
    """Client for OpenAI-compatible API with dynamic base_url and api_key."""

    def __init__(self, timeout: float = 60.0) -> None:
        """Initialize the OpenAI client.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=timeout,
                write=10.0,
                pool=10.0,
            )
        )

    async def chat_completion(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call chat completion API (non-streaming).

        Args:
            base_url: Base URL for the API (e.g., "http://api.com/v1")
            api_key: API key for authentication
            model: Model name
            messages: List of chat messages
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            API response as dictionary
        """
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": messages,
            **kwargs,
        }

        url = f"{base_url.rstrip('/')}/chat/completions"
        logger.info("api_call_start", url=url, model=model, timeout=self.timeout)

        try:
            response = await self.client.post(
                url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            logger.info("api_call_success", url=url, model=model)
            return result
        except httpx.HTTPStatusError as e:
            logger.error(
                "api_http_error",
                url=url,
                model=model,
                status_code=e.response.status_code,
                response_text=e.response.text[:500] if e.response.text else None,
            )
            raise
        except httpx.TimeoutException as e:
            logger.error(
                "api_timeout_error",
                url=url,
                model=model,
                timeout=self.timeout,
                error_type=type(e).__name__,
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "api_request_error",
                url=url,
                model=model,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def chat_completion_stream(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream chat completion with SSE.

        Args:
            base_url: Base URL for the API
            api_key: API key for authentication
            model: Model name
            messages: List of chat messages
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Yields:
            Parsed JSON chunks from the streaming response.
        """
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs,
        }

        url = f"{base_url.rstrip('/')}/chat/completions"
        logger.info("stream_api_call_start", url=url, model=model)

        try:
            async with self.client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    # SSE format: "data: {...}"
                    if line.startswith("data: "):
                        data = line[6:]  # Remove "data: " prefix

                        if data == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data)
                            yield chunk
                        except json.JSONDecodeError:
                            logger.warning(
                                "stream_json_decode_error",
                                line=line[:100],
                            )
                            continue

        except httpx.HTTPStatusError as e:
            logger.error(
                "stream_http_error",
                url=url,
                model=model,
                status_code=e.response.status_code,
            )
            raise
        except httpx.TimeoutException as e:
            logger.error(
                "stream_timeout_error",
                url=url,
                model=model,
                timeout=self.timeout,
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "stream_request_error",
                url=url,
                model=model,
                error=str(e),
            )
            raise

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
```

- [ ] **Step 4: Update `mini_router/client/__init__.py`**

```python
"""OpenAI-compatible client module."""

from mini_router.client.openai_client import OpenAIClient

__all__ = ["OpenAIClient"]
```

- [ ] **Step 5: Run tests to verify**

```bash
python -m pytest tests/unit/test_chat_proxy.py -v
```

- [ ] **Step 6: Commit**

```bash
git add mini_router/client/
git commit -m "refactor: OpenAIClient accepts dynamic base_url and api_key"
```

---

## Task 4: Modify Router to Accept Tenant Decisions

**Files:**
- Modify: `mini_router/router/router.py`

- [ ] **Step 1: Write failing test for tenant decisions**

Add to `tests/unit/test_router.py`:

```python
class TestRouterWithTenantDecisions:
    def test_route_with_tenant_decisions(self, basic_config):
        """Test routing with tenant-specific decisions."""
        from mini_router.config.config import Decision, ModelRef, RuleNode, RuleType
        from mini_router.router.router import Router, RoutingRequest

        router = Router(basic_config)

        # Create tenant-specific decision
        tenant_decision = Decision(
            name="tenant_specific_route",
            priority=100,
            rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
            model_refs=[ModelRef(model="tenant-model", weight=1.0)],
        )

        # Route with tenant decisions
        result = asyncio.run(router.route(
            RoutingRequest(query="How do I debug this code?"),
            decisions=[tenant_decision],
        ))

        assert result.selected_model == "tenant-model"
        assert result.decision_name == "tenant_specific_route"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_router.py::TestRouterWithTenantDecisions -v
```

Expected: Test fails due to unexpected keyword argument

- [ ] **Step 3: Modify `mini_router/router/router.py` route method**

Find the `route` method and add the `decisions` parameter:

```python
async def route(
    self,
    request: RoutingRequest,
    decisions: list[Decision] | None = None,
) -> RoutingResult:
    """
    Route a query through all layers.

    Flow:
    1. Check cache
    2. Extract signals (classify)
    3. Evaluate decisions
    4. Select model
    5. Return result

    Args:
        request: The routing request
        decisions: Optional tenant-specific decisions. If None, uses config decisions.
    """
    # Use provided decisions or fall back to config decisions
    effective_decisions = decisions if decisions is not None else self.config.decisions

    # 1. Check cache
    if isinstance(self.cache, SemanticCache):
        cache_entry = await self.cache.get_similar(request.query)
    else:
        cache_entry = self.cache.get(request.query)

    if cache_entry:
        logger.info(
            "cache_hit",
            query=request.query[:50],
            similarity=cache_entry.metadata.get("similarity"),
        )
        return RoutingResult(
            cache_hit=True,
            cache_response=cache_entry.response,
        )

    # 2. Extract signals
    signals = await self.classifier.classify(request.query)

    logger.debug(
        "signals_extracted",
        query=request.query[:50],
        keyword_matches=signals.keyword_rules,
        intent=signals.get_intent_label(),
        has_pii=signals.has_pii(),
        complexity=signals.get_complexity_level(),
    )

    # 3. Evaluate decisions - create temporary engine with effective decisions
    if decisions is not None:
        decision_engine = Engine(
            decisions=effective_decisions,
            strategy=self.config.selection.strategy.value,
        )
        decision_result = decision_engine.evaluate(signals)
    else:
        decision_result = self.decision_engine.evaluate(signals)

    if decision_result is None:
        logger.warning("no_matching_decision", query=request.query[:50])
        return RoutingResult(
            signals=signals,
            confidence=0.0,
        )

    # Check action
    if decision_result.decision.action == DecisionAction.REJECT:
        logger.info(
            "request_rejected",
            decision=decision_result.decision.name,
            reason=decision_result.decision.reject_message,
        )
        return RoutingResult(
            decision_name=decision_result.decision.name,
            matched_rules=decision_result.matched_rules,
            signals=signals,
            action=DecisionAction.REJECT,
            reject_message=decision_result.decision.reject_message,
        )

    # 4. Select model
    if not decision_result.decision.model_refs:
        logger.warning("no_models_configured", decision=decision_result.decision.name)
        return RoutingResult(
            decision_name=decision_result.decision.name,
            matched_rules=decision_result.matched_rules,
            signals=signals,
            confidence=decision_result.confidence,
        )

    # Get latency-aware configuration
    latency_config = self.config.selection.latency_aware

    selection_context = SelectionContext(
        query=request.query,
        candidate_models=decision_result.decision.model_refs,
        user_id=request.user_id,
        metadata={"decision_name": decision_result.decision.name},
        latency_percentile=latency_config.latency_percentile,
        tpot_percentile=latency_config.tpot_percentile,
        ttft_percentile=latency_config.ttft_percentile,
        min_observations=latency_config.min_observations,
        fallback_to_weight=latency_config.fallback_to_weight,
        weight_blend=latency_config.weight_blend,
    )

    selection_result = await self.selector_registry.select(
        self.config.selection.strategy, selection_context
    )

    logger.info(
        "request_routed",
        query=request.query[:50],
        model=selection_result.selected_model,
        decision=decision_result.decision.name,
        confidence=selection_result.confidence,
    )

    return RoutingResult(
        selected_model=selection_result.selected_model,
        decision_name=decision_result.decision.name,
        matched_rules=decision_result.matched_rules,
        confidence=min(decision_result.confidence, selection_result.confidence),
        signals=signals,
    )
```

- [ ] **Step 4: Run tests to verify**

```bash
python -m pytest tests/unit/test_router.py -v
```

- [ ] **Step 5: Commit**

```bash
git add mini_router/router/router.py tests/unit/test_router.py
git commit -m "feat: Router accepts tenant-specific decisions"
```

---

## Task 5: Modify ChatProxy for Tenant Authentication

**Files:**
- Modify: `mini_router/proxy/chat_proxy.py`

- [ ] **Step 1: Write tests for tenant-aware ChatProxy**

Add tests to verify tenant authentication flow.

- [ ] **Step 2: Modify `mini_router/proxy/chat_proxy.py`**

Replace with:

```python
"""Chat proxy service - routes and forwards chat requests."""

from collections.abc import AsyncGenerator
from typing import Any

import structlog

from mini_router.proxy.types import (
    ChatChoice,
    ChatChoiceDelta,
    ChatChunk,
    ChatMessage,
    ChatProxyResult,
    ChatRequest,
    ChatResponse,
    ChatUsage,
)
from mini_router.router.router import Router, RoutingRequest
from mini_router.tenant.types import TenantConfig, build_base_url

logger = structlog.get_logger()


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    def __init__(self, message: str, code: str = "authentication_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class TenantDisabledError(Exception):
    """Raised when tenant is disabled."""

    def __init__(self, message: str, code: str = "permission_denied"):
        self.message = message
        self.code = code
        super().__init__(message)


class ChatProxy:
    """Proxy service that routes chat requests and forwards to selected models."""

    def __init__(self, router: Router) -> None:
        """Initialize the chat proxy.

        Args:
            router: The router instance for routing decisions
        """
        self.router = router

    def extract_apikey(self, authorization: str | None) -> str | None:
        """Extract apikey from Authorization header.

        Args:
            authorization: The Authorization header value

        Returns:
            The apikey or None if not found
        """
        if not authorization:
            return None

        if authorization.startswith("Bearer "):
            return authorization[7:]

        return None

    async def authenticate_tenant(
        self,
        tenant_manager: Any,
        apikey: str | None,
    ) -> TenantConfig:
        """Authenticate and return tenant.

        Args:
            tenant_manager: The TenantManager instance
            apikey: The apikey from request

        Returns:
            TenantConfig if authenticated

        Raises:
            AuthenticationError: If apikey is missing or invalid
            TenantDisabledError: If tenant is disabled
        """
        if not apikey:
            raise AuthenticationError(
                "Missing Authorization header",
                code="missing_api_key"
            )

        tenant = tenant_manager.get_by_apikey(apikey)
        if tenant is None:
            raise AuthenticationError(
                "Invalid API key",
                code="invalid_api_key"
            )

        if not tenant.enabled:
            raise TenantDisabledError(
                "Tenant is disabled",
                code="tenant_disabled"
            )

        return tenant

    async def chat_stream(
        self,
        request: ChatRequest,
        tenant: TenantConfig,
    ) -> AsyncGenerator[ChatChunk, None]:
        """Process a streaming chat request with tenant context.

        Yields ChatChunk objects for SSE streaming.

        Flow:
        1. Extract query from messages
        2. Route to select model using tenant's decisions
        3. Forward request to selected model
        4. Stream response back
        5. Record latency automatically
        """
        import time

        # Extract query from last user message
        query = self._extract_query(request.messages)

        # Route using tenant's decisions
        if request.model:
            selected_model = request.model
            decision_name = None
            confidence = 1.0
        else:
            routing_result = await self.router.route(
                RoutingRequest(
                    query=query,
                    user_id=request.user,
                    metadata=request.metadata or {},
                ),
                decisions=tenant.decisions,
            )
            selected_model = routing_result.selected_model
            decision_name = routing_result.decision_name
            confidence = routing_result.confidence

            if not selected_model:
                yield ChatChunk(
                    model="unknown",
                    choices=[
                        ChatChoice(
                            delta=ChatChoiceDelta(
                                role="assistant",
                                content="Error: No model selected for routing.",
                            ),
                            finish_reason="error",
                        )
                    ],
                )
                return

        # Build base URL from tenant template
        base_url = build_base_url(tenant.base_url_template, selected_model)

        # Record timing
        start_time = time.time()
        first_token_time: float | None = None
        token_count = 0
        total_content = ""

        try:
            # Build kwargs for API call
            kwargs: dict[str, Any] = {}
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.max_tokens is not None:
                kwargs["max_tokens"] = request.max_tokens
            if request.top_p is not None:
                kwargs["top_p"] = request.top_p
            if request.stop is not None:
                kwargs["stop"] = request.stop
            if request.presence_penalty is not None:
                kwargs["presence_penalty"] = request.presence_penalty
            if request.frequency_penalty is not None:
                kwargs["frequency_penalty"] = request.frequency_penalty

            # Stream from selected model using tenant's apikey
            messages = [msg.model_dump() for msg in request.messages]

            async for chunk in self.router.client.chat_completion_stream(
                base_url=base_url,
                api_key=tenant.apikey,
                model=selected_model,
                messages=messages,
                **kwargs,
            ):
                # Record first token time
                if first_token_time is None:
                    first_token_time = time.time()

                # Extract content from chunk
                choices = chunk.get("choices", [])
                chat_choices = []

                for choice in choices:
                    delta = choice.get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        total_content += content
                        token_count += 1

                    chat_choices.append(
                        ChatChoice(
                            index=choice.get("index", 0),
                            delta=ChatChoiceDelta(
                                role=delta.get("role"),
                                content=content if content else None,
                            ),
                            finish_reason=choice.get("finish_reason"),
                        )
                    )

                yield ChatChunk(
                    id=chunk.get("id", f"chatcmpl-{selected_model}"),
                    model=selected_model,
                    choices=chat_choices,
                )

            # Calculate and record latency
            end_time = time.time()
            total_latency = end_time - start_time
            ttft = first_token_time - start_time if first_token_time else None

            # Calculate TPOT (Time Per Output Token)
            tpot = None
            if token_count > 0 and first_token_time:
                tpot = (end_time - first_token_time) / token_count

            # Record latency
            await self.router.record_latency(
                model=selected_model,
                latency_seconds=total_latency,
                tpot=tpot,
                ttft=ttft,
            )

            logger.info(
                "chat_proxy_stream_completed",
                model=selected_model,
                tenant=tenant.tenant_id,
                decision=decision_name,
                latency=total_latency,
                ttft=ttft,
                tpot=tpot,
                tokens=token_count,
            )

        except Exception as e:
            logger.error(
                "chat_proxy_stream_error",
                model=selected_model,
                tenant=tenant.tenant_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            yield ChatChunk(
                model=selected_model or "unknown",
                choices=[
                    ChatChoice(
                        delta=ChatChoiceDelta(
                            role="assistant",
                            content=f"\n\n[Error: {str(e)}]",
                        ),
                        finish_reason="error",
                    )
                ],
            )

    async def chat(self, request: ChatRequest, tenant: TenantConfig) -> ChatResponse:
        """Process a non-streaming chat request with tenant context.

        Returns a complete ChatResponse.
        """
        import time

        # Extract query from last user message
        query = self._extract_query(request.messages)

        # Route using tenant's decisions
        if request.model:
            selected_model = request.model
            decision_name = None
            confidence = 1.0
        else:
            routing_result = await self.router.route(
                RoutingRequest(
                    query=query,
                    user_id=request.user,
                    metadata=request.metadata or {},
                ),
                decisions=tenant.decisions,
            )
            selected_model = routing_result.selected_model
            decision_name = routing_result.decision_name
            confidence = routing_result.confidence

            if not selected_model:
                return ChatResponse(
                    model="unknown",
                    choices=[
                        ChatChoice(
                            message=ChatMessage(
                                role="assistant",
                                content="Error: No model selected for routing.",
                            ),
                            finish_reason="error",
                        )
                    ],
                )

        # Build base URL from tenant template
        base_url = build_base_url(tenant.base_url_template, selected_model)

        # Record timing
        start_time = time.time()

        try:
            # Build kwargs for API call
            kwargs: dict[str, Any] = {}
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.max_tokens is not None:
                kwargs["max_tokens"] = request.max_tokens
            if request.top_p is not None:
                kwargs["top_p"] = request.top_p
            if request.stop is not None:
                kwargs["stop"] = request.stop
            if request.presence_penalty is not None:
                kwargs["presence_penalty"] = request.presence_penalty
            if request.frequency_penalty is not None:
                kwargs["frequency_penalty"] = request.frequency_penalty

            # Call API (non-streaming) with tenant's apikey
            messages = [msg.model_dump() for msg in request.messages]

            response = await self.router.client.chat_completion(
                base_url=base_url,
                api_key=tenant.apikey,
                model=selected_model,
                messages=messages,
                **kwargs,
            )

            # Calculate and record latency
            end_time = time.time()
            total_latency = end_time - start_time

            # Extract usage
            usage = None
            if "usage" in response:
                usage = ChatUsage(
                    prompt_tokens=response["usage"].get("prompt_tokens", 0),
                    completion_tokens=response["usage"].get("completion_tokens", 0),
                    total_tokens=response["usage"].get("total_tokens", 0),
                )

            # Record latency
            await self.router.record_latency(
                model=selected_model,
                latency_seconds=total_latency,
            )

            # Build response
            choices = []
            for choice in response.get("choices", []):
                message = choice.get("message", {})
                choices.append(
                    ChatChoice(
                        index=choice.get("index", 0),
                        message=ChatMessage(
                            role=message.get("role", "assistant"),
                            content=message.get("content", ""),
                        ),
                        finish_reason=choice.get("finish_reason"),
                    )
                )

            logger.info(
                "chat_proxy_completed",
                model=selected_model,
                tenant=tenant.tenant_id,
                decision=decision_name,
                latency=total_latency,
                tokens=usage.completion_tokens if usage else None,
            )

            return ChatResponse(
                id=response.get("id", f"chatcmpl-{selected_model}"),
                model=selected_model,
                choices=choices,
                usage=usage,
            )

        except Exception as e:
            logger.error(
                "chat_proxy_error",
                model=selected_model,
                tenant=tenant.tenant_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ChatResponse(
                model=selected_model or "unknown",
                choices=[
                    ChatChoice(
                        message=ChatMessage(
                            role="assistant",
                            content=f"Error: {str(e)}",
                        ),
                        finish_reason="error",
                    )
                ],
            )

    def _extract_query(self, messages: list[ChatMessage]) -> str:
        """Extract query from chat messages.

        Uses the last user message as the query for routing.
        """
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content

        # Fallback: join all message content
        return " ".join(msg.content for msg in messages if msg.content)
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/unit/test_chat_proxy.py -v
```

- [ ] **Step 4: Commit**

```bash
git add mini_router/proxy/chat_proxy.py
git commit -m "feat: ChatProxy with tenant authentication and routing"
```

---

## Task 6: Add Tenant Management API Endpoints

**Files:**
- Modify: `mini_router/server.py`

- [ ] **Step 1: Add tenant API imports and models**

Add to `mini_router/server.py` imports section:

```python
from mini_router.tenant import (
    TenantConfig,
    TenantCreateRequest,
    TenantResponse,
    TenantUpdateRequest,
)
from mini_router.tenant.manager import TenantManager
from mini_router.proxy.chat_proxy import AuthenticationError, TenantDisabledError
```

- [ ] **Step 2: Add global tenant manager state**

Add after `_chat_proxy` global:

```python
_tenant_manager: TenantManager | None = None


def get_tenant_manager() -> TenantManager:
    """Get or create the tenant manager instance."""
    global _tenant_manager, _config
    if _tenant_manager is None:
        # Use tenants file path from config or default
        tenants_path = "config/tenants.yaml"
        _tenant_manager = TenantManager(tenants_path)
        _tenant_manager.load()
    return _tenant_manager
```

- [ ] **Step 3: Add tenant API endpoints**

Add before `# === Chat Completions ===`:

```python
# === Tenant Management ===


@app.get("/v1/tenants", response_model=list[TenantResponse])
async def list_tenants() -> list[TenantResponse]:
    """List all tenants."""
    manager = get_tenant_manager()
    return [TenantResponse.from_config(t) for t in manager.list_all()]


@app.get("/v1/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str) -> TenantResponse:
    """Get a single tenant by ID."""
    manager = get_tenant_manager()
    tenant = manager.get_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return TenantResponse.from_config(tenant)


@app.post("/v1/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(request: TenantCreateRequest) -> TenantResponse:
    """Create a new tenant."""
    manager = get_tenant_manager()
    tenant = TenantConfig(**request.model_dump())
    try:
        created = manager.create(tenant)
        return TenantResponse.from_config(created)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/v1/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: str, request: TenantUpdateRequest) -> TenantResponse:
    """Update a tenant (partial update)."""
    manager = get_tenant_manager()
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    try:
        updated = manager.update(tenant_id, updates)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
        return TenantResponse.from_config(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/v1/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str) -> dict[str, str]:
    """Delete a tenant."""
    manager = get_tenant_manager()
    deleted = manager.delete(tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return {"status": "deleted", "tenant_id": tenant_id}
```

- [ ] **Step 4: Update chat_completions endpoint for tenant auth**

Replace the `chat_completions` function with:

```python
@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest,
    authorization: str | None = None,
) -> Any:
    """
    OpenAI-compatible chat completions endpoint with tenant authentication.

    Requires Authorization header with Bearer token (tenant apikey).
    If `stream=true`, returns SSE streaming response.
    If `stream=false`, returns complete JSON response.
    """
    proxy = get_chat_proxy()
    tenant_manager = get_tenant_manager()

    # Extract apikey from Authorization header
    apikey = proxy.extract_apikey(authorization)

    try:
        # Authenticate tenant
        tenant = await proxy.authenticate_tenant(tenant_manager, apikey)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=401,
            detail={"error": {"type": "authentication_error", "message": e.message, "code": e.code}}
        )
    except TenantDisabledError as e:
        raise HTTPException(
            status_code=403,
            detail={"error": {"type": "permission_denied", "message": e.message, "code": e.code}}
        )

    if request.stream:
        # Return SSE streaming response
        async def generate_sse() -> AsyncGenerator[str, None]:
            async for chunk in proxy.chat_stream(request, tenant):
                yield chunk.to_sse()
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await proxy.chat(request, tenant)
```

- [ ] **Step 5: Add authorization dependency import**

Add to imports:

```python
from fastapi import Header
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/unit/ -v
```

- [ ] **Step 7: Commit**

```bash
git add mini_router/server.py
git commit -m "feat: add tenant management API endpoints"
```

---

## Task 7: Write Tenant API Tests

**Files:**
- Create: `tests/unit/test_tenant_api.py`

- [ ] **Step 1: Create test file**

```python
"""Tests for tenant management API endpoints."""

import pytest
from fastapi.testclient import TestClient

from mini_router.server import app
from mini_router.tenant.manager import TenantManager
from mini_router.tenant.types import TenantConfig


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def tenant_manager():
    """Get tenant manager and clear tenants."""
    from mini_router.server import get_tenant_manager
    manager = get_tenant_manager()
    # Clear existing tenants for test isolation
    for tenant in manager.list_all():
        manager.delete(tenant.tenant_id)
    yield manager
    # Cleanup after test
    for tenant in manager.list_all():
        manager.delete(tenant.tenant_id)


class TestTenantAPI:
    def test_create_tenant(self, client, tenant_manager):
        """Test creating a tenant via API."""
        response = client.post(
            "/v1/tenants",
            json={
                "tenant_id": "test-api",
                "apikey": "sk-test-api",
                "name": "Test API Tenant",
                "base_url_template": "http://api.test.com/llm/{model}/v1",
                "timeout": 60.0,
                "decisions": [],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["tenant_id"] == "test-api"
        assert data["apikey"] == "sk-tes***"  # Masked

    def test_create_duplicate_tenant(self, client, tenant_manager):
        """Test creating duplicate tenant fails."""
        client.post(
            "/v1/tenants",
            json={
                "tenant_id": "dup-test",
                "apikey": "sk-dup",
                "base_url_template": "http://test.com/{model}/v1",
            },
        )
        response = client.post(
            "/v1/tenants",
            json={
                "tenant_id": "dup-test",
                "apikey": "sk-dup2",
                "base_url_template": "http://test.com/{model}/v1",
            },
        )
        assert response.status_code == 400

    def test_list_tenants(self, client, tenant_manager):
        """Test listing tenants."""
        client.post(
            "/v1/tenants",
            json={
                "tenant_id": "list-test-1",
                "apikey": "sk-list-1",
                "base_url_template": "http://test.com/{model}/v1",
            },
        )
        client.post(
            "/v1/tenants",
            json={
                "tenant_id": "list-test-2",
                "apikey": "sk-list-2",
                "base_url_template": "http://test.com/{model}/v1",
            },
        )

        response = client.get("/v1/tenants")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2

    def test_get_tenant(self, client, tenant_manager):
        """Test getting a single tenant."""
        client.post(
            "/v1/tenants",
            json={
                "tenant_id": "get-test",
                "apikey": "sk-get",
                "name": "Get Test",
                "base_url_template": "http://test.com/{model}/v1",
            },
        )
        response = client.get("/v1/tenants/get-test")
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "get-test"
        assert data["name"] == "Get Test"

    def test_get_nonexistent_tenant(self, client, tenant_manager):
        """Test getting non-existent tenant returns 404."""
        response = client.get("/v1/tenants/nonexistent")
        assert response.status_code == 404

    def test_update_tenant(self, client, tenant_manager):
        """Test updating a tenant."""
        client.post(
            "/v1/tenants",
            json={
                "tenant_id": "update-test",
                "apikey": "sk-update",
                "base_url_template": "http://test.com/{model}/v1",
            },
        )
        response = client.put(
            "/v1/tenants/update-test",
            json={"name": "Updated Name", "timeout": 30.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["timeout"] == 30.0

    def test_update_nonexistent_tenant(self, client, tenant_manager):
        """Test updating non-existent tenant returns 404."""
        response = client.put(
            "/v1/tenants/nonexistent",
            json={"name": "Test"},
        )
        assert response.status_code == 404

    def test_delete_tenant(self, client, tenant_manager):
        """Test deleting a tenant."""
        client.post(
            "/v1/tenants",
            json={
                "tenant_id": "delete-test",
                "apikey": "sk-delete",
                "base_url_template": "http://test.com/{model}/v1",
            },
        )
        response = client.delete("/v1/tenants/delete-test")
        assert response.status_code == 200

        # Verify deleted
        response = client.get("/v1/tenants/delete-test")
        assert response.status_code == 404

    def test_delete_nonexistent_tenant(self, client, tenant_manager):
        """Test deleting non-existent tenant returns 404."""
        response = client.delete("/v1/tenants/nonexistent")
        assert response.status_code == 404


class TestChatWithTenantAuth:
    def test_chat_without_auth_returns_401(self, client, tenant_manager):
        """Test chat request without auth header returns 401."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            },
        )
        assert response.status_code == 401

    def test_chat_with_invalid_apikey_returns_401(self, client, tenant_manager):
        """Test chat request with invalid apikey returns 401."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            },
            headers={"Authorization": "Bearer invalid-key"},
        )
        assert response.status_code == 401
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/unit/test_tenant_api.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_tenant_api.py
git commit -m "test: add tenant API endpoint tests"
```

---

## Task 8: Final Integration and Documentation

**Files:**
- Update: `docs/superpowers/specs/2026-04-02-multi-tenant-apikey-design.md` (optional)
- Run: All tests

- [ ] **Step 1: Run all tests**

```bash
python -m pytest tests/unit/ -v
```

- [ ] **Step 2: Create example tenants.yaml**

Update `config/tenants.yaml` with example:

```yaml
# Tenant configurations
# Managed by TenantManager API - do not edit manually
tenants:
  - tenant_id: "example-tenant"
    apikey: "sk-example-123456"
    name: "Example Tenant"
    enabled: true
    base_url_template: "http://open-llm.com/llm/{model}/v1"
    timeout: 120.0
    decisions:
      - name: "default_route"
        priority: 0
        rules:
          type: "or"
          children: []
        model_refs:
          - model: "qwen3.5-plus"
            weight: 1.0
    created_at: "2026-04-02T00:00:00"
    updated_at: "2026-04-02T00:00:00"
```

- [ ] **Step 3: Final commit**

```bash
git add config/tenants.yaml
git commit -m "docs: add example tenant configuration"
```

- [ ] **Step 4: Run full test suite one more time**

```bash
python -m pytest tests/unit/ -v --tb=short
```

---

## Summary

The implementation adds:

1. **Tenant Types** (`mini_router/tenant/types.py`): `TenantConfig`, request/response models, and `build_base_url` utility

2. **TenantManager** (`mini_router/tenant/manager.py`): CRUD operations with YAML persistence

3. **OpenAIClient** (`mini_router/client/openai_client.py`): Accepts dynamic `base_url` and `api_key` per request

4. **Router** (`mini_router/router/router.py`): Accepts optional `decisions` parameter for tenant-specific routing

5. **ChatProxy** (`mini_router/proxy/chat_proxy.py`): Tenant authentication and URL building

6. **Server** (`mini_router/server.py`): Tenant management API endpoints and auth middleware