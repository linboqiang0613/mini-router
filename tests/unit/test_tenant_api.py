"""Tests for Tenant API endpoints."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

import mini_router.server
from mini_router.server import app
from mini_router.tenant.manager import TenantManager
from mini_router.tenant.types import TenantConfig


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for tenant storage."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("")
        f.flush()
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def isolated_manager(temp_config_file):
    """Create an isolated tenant manager for each test."""
    # Reset global state before each test
    mini_router.server._tenant_manager = None
    mini_router.server._router = None
    mini_router.server._chat_proxy = None

    # Create fresh tenant manager
    manager = TenantManager(config_path=temp_config_file)
    manager.load()

    # Set global state directly (since endpoints don't use Depends())
    mini_router.server._tenant_manager = manager

    yield manager

    # Clean up after test
    mini_router.server._tenant_manager = None
    mini_router.server._router = None
    mini_router.server._chat_proxy = None


class TestTenantAPI:
    """Tests for Tenant CRUD API endpoints."""

    def test_create_tenant(self, isolated_manager) -> None:
        """Test POST /v1/tenants returns 201."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "test-tenant-1",
                    "apikey": "sk-test-key-001",
                    "name": "Test Tenant",
                    "enabled": True,
                    "base_url_template": "http://api.example.com/{model}/v1",
                    "timeout": 60.0,
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["tenant_id"] == "test-tenant-1"
            assert data["name"] == "Test Tenant"
            assert data["enabled"] is True
            # Masking uses first 6 characters: "sk-tes" + "***"
            assert data["apikey"] == "sk-tes***"

            # Verify tenant exists in manager
            tenant = manager.get_by_id("test-tenant-1")
            assert tenant is not None
            assert tenant.apikey == "sk-test-key-001"

    def test_create_duplicate_tenant(self, isolated_manager) -> None:
        """Test creating duplicate tenant returns 400."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create first tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "duplicate-test",
                    "apikey": "sk-unique-key-001",
                    "name": "First Tenant",
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            # Try to create duplicate with same tenant_id
            response = client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "duplicate-test",
                    "apikey": "sk-unique-key-002",
                    "name": "Second Tenant",
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            assert response.status_code == 400
            assert "tenant_id" in response.json()["detail"]

    def test_create_duplicate_apikey(self, isolated_manager) -> None:
        """Test creating tenant with duplicate apikey returns 400."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create first tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "tenant-a",
                    "apikey": "sk-same-key-123",
                    "name": "Tenant A",
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            # Try to create with duplicate apikey
            response = client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "tenant-b",
                    "apikey": "sk-same-key-123",  # Duplicate apikey
                    "name": "Tenant B",
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            assert response.status_code == 400
            assert "apikey" in response.json()["detail"]

    def test_list_tenants(self, isolated_manager) -> None:
        """Test GET /v1/tenants lists all tenants."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create multiple tenants
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "tenant-list-1",
                    "apikey": "sk-list-key-001",
                    "name": "List Tenant 1",
                    "base_url_template": "http://api1.example.com/{model}/v1",
                },
            )
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "tenant-list-2",
                    "apikey": "sk-list-key-002",
                    "name": "List Tenant 2",
                    "base_url_template": "http://api2.example.com/{model}/v1",
                },
            )

            response = client.get("/v1/tenants")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2

            # Check tenant IDs are present
            tenant_ids = [t["tenant_id"] for t in data]
            assert "tenant-list-1" in tenant_ids
            assert "tenant-list-2" in tenant_ids

    def test_list_tenants_empty(self, isolated_manager) -> None:
        """Test GET /v1/tenants returns empty list when no tenants."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.get("/v1/tenants")

            assert response.status_code == 200
            assert response.json() == []

    def test_get_tenant(self, isolated_manager) -> None:
        """Test GET /v1/tenants/{tenant_id} returns tenant."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create a tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "get-test-tenant",
                    "apikey": "sk-get-key-123",
                    "name": "Get Test Tenant",
                    "enabled": True,
                    "base_url_template": "http://api.example.com/{model}/v1",
                    "timeout": 90.0,
                },
            )

            response = client.get("/v1/tenants/get-test-tenant")

            assert response.status_code == 200
            data = response.json()
            assert data["tenant_id"] == "get-test-tenant"
            assert data["name"] == "Get Test Tenant"
            assert data["enabled"] is True
            assert data["timeout"] == 90.0
            # First 6 chars: "sk-get" + "***"
            assert data["apikey"] == "sk-get***"

    def test_get_nonexistent_tenant(self, isolated_manager) -> None:
        """Test GET /v1/tenants/{tenant_id} returns 404 for nonexistent."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.get("/v1/tenants/nonexistent-tenant-id")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    def test_update_tenant(self, isolated_manager) -> None:
        """Test PUT /v1/tenants/{tenant_id} updates tenant."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create a tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "update-test-tenant",
                    "apikey": "sk-update-key-123",
                    "name": "Original Name",
                    "enabled": True,
                    "base_url_template": "http://api.example.com/{model}/v1",
                    "timeout": 60.0,
                },
            )

            # Update the tenant
            response = client.put(
                "/v1/tenants/update-test-tenant",
                json={
                    "name": "Updated Name",
                    "timeout": 120.0,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Updated Name"
            assert data["timeout"] == 120.0
            assert data["enabled"] is True  # Unchanged

            # Verify update persisted
            tenant = manager.get_by_id("update-test-tenant")
            assert tenant is not None
            assert tenant.name == "Updated Name"
            assert tenant.timeout == 120.0

    def test_update_tenant_apikey(self, isolated_manager) -> None:
        """Test updating tenant's apikey updates the index."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create a tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "apikey-update-test",
                    "apikey": "sk-old-apikey",
                    "name": "API Key Update Test",
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            # Update the apikey
            response = client.put(
                "/v1/tenants/apikey-update-test",
                json={"apikey": "sk-new-apikey"},
            )

            assert response.status_code == 200

            # Old apikey should not find tenant
            assert manager.get_by_apikey("sk-old-apikey") is None

            # New apikey should find tenant
            tenant = manager.get_by_apikey("sk-new-apikey")
            assert tenant is not None
            assert tenant.tenant_id == "apikey-update-test"

    def test_update_nonexistent_tenant(self, isolated_manager) -> None:
        """Test PUT /v1/tenants/{tenant_id} returns 404 for nonexistent."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.put(
                "/v1/tenants/nonexistent-tenant-id",
                json={"name": "New Name"},
            )

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    def test_update_tenant_empty_update(self, isolated_manager) -> None:
        """Test PUT with empty update returns current tenant."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create a tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "empty-update-test",
                    "apikey": "sk-empty-update",
                    "name": "Empty Update Test",
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            # Update with empty body (all None values)
            response = client.put(
                "/v1/tenants/empty-update-test",
                json={},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["tenant_id"] == "empty-update-test"
            assert data["name"] == "Empty Update Test"

    def test_delete_tenant(self, isolated_manager) -> None:
        """Test DELETE /v1/tenants/{tenant_id} deletes tenant."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create a tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "delete-test-tenant",
                    "apikey": "sk-delete-key-123",
                    "name": "Delete Test Tenant",
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            # Delete the tenant
            response = client.delete("/v1/tenants/delete-test-tenant")

            assert response.status_code == 200
            assert response.json()["status"] == "deleted"

            # Verify tenant is gone
            assert manager.get_by_id("delete-test-tenant") is None
            assert manager.get_by_apikey("sk-delete-key-123") is None

    def test_delete_nonexistent_tenant(self, isolated_manager) -> None:
        """Test DELETE /v1/tenants/{tenant_id} returns 404 for nonexistent."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.delete("/v1/tenants/nonexistent-tenant-id")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()


class TestChatWithTenantAuth:
    """Tests for chat completions with tenant authentication."""

    def test_chat_without_auth_returns_401(self, isolated_manager) -> None:
        """Test chat completions without Authorization header returns 401."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

            assert response.status_code == 401
            assert "Authorization" in response.json()["detail"]

    def test_chat_with_invalid_apikey_returns_401(self, isolated_manager) -> None:
        """Test chat completions with invalid API key returns 401."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create a tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "auth-test-tenant",
                    "apikey": "sk-valid-key-123",
                    "name": "Auth Test Tenant",
                    "enabled": True,
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                headers={"Authorization": "Bearer sk-invalid-key"},
            )

            assert response.status_code == 401
            assert "Invalid API key" in response.json()["detail"]

    def test_chat_with_disabled_tenant_returns_403(self, isolated_manager) -> None:
        """Test chat completions with disabled tenant returns 403."""
        manager = isolated_manager

        with TestClient(app) as client:
            # Create a disabled tenant
            client.post(
                "/v1/tenants",
                json={
                    "tenant_id": "disabled-tenant",
                    "apikey": "sk-disabled-key-123",
                    "name": "Disabled Tenant",
                    "enabled": False,
                    "base_url_template": "http://api.example.com/{model}/v1",
                },
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                headers={"Authorization": "Bearer sk-disabled-key-123"},
            )

            assert response.status_code == 403
            assert "disabled" in response.json()["detail"].lower()

    def test_chat_with_valid_tenant_calls_proxy(self, isolated_manager) -> None:
        """Test chat completions with valid tenant calls proxy with tenant."""
        manager = isolated_manager

        # Create a tenant directly in manager
        tenant = TenantConfig(
            tenant_id="valid-tenant",
            apikey="sk-valid-key-456",
            name="Valid Tenant",
            enabled=True,
            base_url_template="http://api.example.com/{model}/v1",
        )
        manager.create(tenant)

        # Mock the ChatProxy.chat method
        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import ChatResponse, ChatChoice, ChatMessage

        original_chat = ChatProxy.chat

        # Track if chat was called with correct tenant
        chat_call_kwargs = {}

        async def mock_chat(self, request, tenant=None):
            chat_call_kwargs["request"] = request
            chat_call_kwargs["tenant"] = tenant
            return ChatResponse(
                model="gpt-4",
                choices=[
                    ChatChoice(
                        message=ChatMessage(role="assistant", content="Hello!"),
                        finish_reason="stop",
                    )
                ],
            )

        # Patch ChatProxy.chat
        with patch.object(ChatProxy, "chat", mock_chat):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-4",
                        "messages": [{"role": "user", "content": "Hello"}],
                        "stream": False,
                    },
                    headers={"Authorization": "Bearer sk-valid-key-456"},
                )

                assert response.status_code == 200
                data = response.json()
                assert data["model"] == "gpt-4"
                assert data["choices"][0]["message"]["content"] == "Hello!"

                # Verify chat was called with tenant
                assert chat_call_kwargs.get("tenant") is not None
                assert chat_call_kwargs["tenant"].tenant_id == "valid-tenant"

    def test_chat_with_invalid_auth_format_returns_401(self, isolated_manager) -> None:
        """Test chat completions with invalid Authorization format returns 401."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                headers={"Authorization": "InvalidFormat sk-format-key"},
            )

            assert response.status_code == 401
            assert "Authorization" in response.json()["detail"]

    def test_chat_with_empty_bearer_returns_401(self, isolated_manager) -> None:
        """Test chat completions with empty Bearer token returns 401."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                headers={"Authorization": "Bearer "},
            )

            assert response.status_code == 401