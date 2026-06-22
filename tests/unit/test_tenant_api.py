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


def tenant_payload(**overrides):
    """Build a valid tenant payload for API tests."""
    payload = {
        "tenant_id": "test-tenant",
        "apikey": "sk-test-key",
        "name": "Test Tenant",
        "enabled": True,
        "base_url_template": "http://api.example.com/{model}/v1",
        "timeout": 60.0,
        "selection": {"strategy": "static"},
        "decisions": [],
    }
    payload.update(overrides)
    return payload


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
def isolated_manager(temp_config_file, monkeypatch):
    """Create an isolated tenant manager for each test."""
    # Reset global state before each test
    mini_router.server._tenant_manager = None
    mini_router.server._router = None
    mini_router.server._chat_proxy = None

    # Create fresh tenant manager
    manager = TenantManager(config_path=temp_config_file)
    manager.load()

    mock_config = MagicMock()
    mock_router = MagicMock()
    mock_router.client = MagicMock()
    mock_router.route = AsyncMock(
        return_value=MagicMock(
            selected_model="tenant-model",
            decision_name="tenant-decision",
            matched_rules=["rule-1"],
            confidence=0.9,
            cache_hit=False,
            cache_response=None,
            action=MagicMock(value="route"),
            reject_message=None,
            signals=None,
        )
    )

    monkeypatch.setattr(mini_router.server, "load_yaml_config", MagicMock(return_value=mock_config))
    monkeypatch.setattr(mini_router.server, "TenantManager", MagicMock(return_value=manager))
    monkeypatch.setattr(mini_router.server, "Router", MagicMock(return_value=mock_router))
    mini_router.server.app.state.config_path = "test-config.yaml"
    mini_router.server.app.state.env = "dev"

    yield manager

    # Clean up after test
    mini_router.server._tenant_manager = None
    mini_router.server._router = None
    mini_router.server._chat_proxy = None
    mini_router.server.app.state.config_path = None


class TestTenantAPI:
    """Tests for Tenant CRUD API endpoints."""

    def test_create_tenant(self, isolated_manager) -> None:
        """Test POST /v1/tenants returns 201."""
        manager = isolated_manager

        with TestClient(app) as client:
            response = client.post(
                "/v1/tenants",
                json=tenant_payload(
                    tenant_id="test-tenant-1",
                    apikey="sk-test-key-001",
                ),
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
                json=tenant_payload(
                    tenant_id="duplicate-test",
                    apikey="sk-unique-key-001",
                    name="First Tenant",
                ),
            )

            # Try to create duplicate with same tenant_id
            response = client.post(
                "/v1/tenants",
                json=tenant_payload(
                    tenant_id="duplicate-test",
                    apikey="sk-unique-key-002",
                    name="Second Tenant",
                ),
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
                json=tenant_payload(
                    tenant_id="tenant-a",
                    apikey="sk-same-key-123",
                    name="Tenant A",
                ),
            )

            # Try to create with duplicate apikey
            response = client.post(
                "/v1/tenants",
                json=tenant_payload(
                    tenant_id="tenant-b",
                    apikey="sk-same-key-123",
                    name="Tenant B",
                ),
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
                json=tenant_payload(
                    tenant_id="tenant-list-1",
                    apikey="sk-list-key-001",
                    name="List Tenant 1",
                    base_url_template="http://api1.example.com/{model}/v1",
                ),
            )
            client.post(
                "/v1/tenants",
                json=tenant_payload(
                    tenant_id="tenant-list-2",
                    apikey="sk-list-key-002",
                    name="List Tenant 2",
                    base_url_template="http://api2.example.com/{model}/v1",
                ),
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
                json=tenant_payload(
                    tenant_id="get-test-tenant",
                    apikey="sk-get-key-123",
                    name="Get Test Tenant",
                    timeout=90.0,
                ),
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
                json=tenant_payload(
                    tenant_id="update-test-tenant",
                    apikey="sk-update-key-123",
                    name="Original Name",
                    timeout=60.0,
                ),
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
                json=tenant_payload(
                    tenant_id="apikey-update-test",
                    apikey="sk-old-apikey",
                    name="API Key Update Test",
                ),
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
                json=tenant_payload(
                    tenant_id="empty-update-test",
                    apikey="sk-empty-update",
                    name="Empty Update Test",
                ),
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
                json=tenant_payload(
                    tenant_id="delete-test-tenant",
                    apikey="sk-delete-key-123",
                    name="Delete Test Tenant",
                ),
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
                json=tenant_payload(
                    tenant_id="auth-test-tenant",
                    apikey="sk-valid-key-123",
                    name="Auth Test Tenant",
                ),
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
                json=tenant_payload(
                    tenant_id="disabled-tenant",
                    apikey="sk-disabled-key-123",
                    name="Disabled Tenant",
                    enabled=False,
                ),
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

        async def mock_chat(self, request, tenant=None, trace=None):
            chat_call_kwargs["request"] = request
            chat_call_kwargs["tenant"] = tenant
            chat_call_kwargs["trace"] = trace
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
                assert chat_call_kwargs["trace"] is not None

    def test_chat_request_lifecycle_logs(self, isolated_manager) -> None:
        """Chat endpoint should emit request_started and request_finished."""
        manager = isolated_manager

        tenant = TenantConfig(
            tenant_id="log-tenant",
            apikey="sk-log-key",
            name="Log Tenant",
            enabled=True,
            base_url_template="http://api.example.com/{model}/v1",
        )
        manager.create(tenant)

        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import ChatResponse, ChatChoice, ChatMessage

        async def mock_chat(self, request, tenant=None, trace=None):
            assert trace is not None
            trace.record_completion(status="completed", finish_reason="chat_completed")
            mini_router.server.logger.info("request_finished", **trace.finished_event())
            return ChatResponse(
                model="gpt-4",
                choices=[
                    ChatChoice(
                        message=ChatMessage(role="assistant", content="Hello!"),
                        finish_reason="stop",
                    )
                ],
            )

        with patch.object(ChatProxy, "chat", mock_chat):
            with patch("mini_router.server.logger.info") as mock_log_info:
                with TestClient(app) as client:
                    response = client.post(
                        "/v1/chat/completions",
                        json={
                            "messages": [{"role": "user", "content": "Hello this is a long request preview"}],
                            "stream": False,
                        },
                        headers={"Authorization": "Bearer sk-log-key"},
                    )

        assert response.status_code == 200
        event_names = [call.args[0] for call in mock_log_info.call_args_list]
        assert "request_started" in event_names
        assert "request_finished" in event_names

    def test_streaming_chat_passthroughs_prepared_upstream_error(self, isolated_manager) -> None:
        """Streaming chat should return pre-stream upstream errors without wrapping them."""
        manager = isolated_manager

        tenant = TenantConfig(
            tenant_id="stream-error-tenant",
            apikey="sk-stream-error-key",
            name="Stream Error Tenant",
            enabled=True,
            base_url_template="http://api.example.com/{model}/v1",
        )
        manager.create(tenant)

        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import PreparedChatStreamResponse

        async def mock_chat_stream(self, request, tenant=None, trace=None):
            return PreparedChatStreamResponse(
                status_code=429,
                media_type="application/json",
                headers={"x-upstream": "rate-limit"},
                body=b'{"error":"rate limited"}',
            )

        with patch.object(ChatProxy, "chat_stream", mock_chat_stream):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": "Hello"}],
                        "stream": True,
                    },
                    headers={"Authorization": "Bearer sk-stream-error-key"},
                )

        assert response.status_code == 429
        assert response.headers["x-upstream"] == "rate-limit"
        assert response.text == '{"error":"rate limited"}'

    def test_streaming_chat_passthroughs_raw_sse_bytes(self, isolated_manager) -> None:
        """Streaming chat should forward raw SSE bytes without router-added framing."""
        manager = isolated_manager

        tenant = TenantConfig(
            tenant_id="stream-success-tenant",
            apikey="sk-stream-success-key",
            name="Stream Success Tenant",
            enabled=True,
            base_url_template="http://api.example.com/{model}/v1",
        )
        manager.create(tenant)

        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import PreparedChatStreamResponse

        async def raw_stream():
            yield b"event: message\nid: 1\ndata: hello\n\n"
            yield b": keepalive\n\n"
            yield b"data: [DONE]\n\n"

        async def mock_chat_stream(self, request, tenant=None, trace=None):
            return PreparedChatStreamResponse(
                status_code=200,
                media_type="text/event-stream",
                headers={"x-upstream": "stream"},
                stream=raw_stream(),
            )

        with patch.object(ChatProxy, "chat_stream", mock_chat_stream):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": "Hello"}],
                        "stream": True,
                    },
                    headers={"Authorization": "Bearer sk-stream-success-key"},
                )

        assert response.status_code == 200
        assert response.headers["x-upstream"] == "stream"
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.text == "event: message\nid: 1\ndata: hello\n\n: keepalive\n\ndata: [DONE]\n\n"

    def test_route_request_lifecycle_logs(self, isolated_manager) -> None:
        """Route endpoint should emit request_started and request_finished with bounded preview."""
        manager = isolated_manager
        manager.create(
            TenantConfig(
                tenant_id="route-log-tenant",
                apikey="sk-route-log-key",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
            )
        )

        with patch("mini_router.server.logger.info") as mock_log_info:
            client = TestClient(app)
            response = client.post(
                "/v1/route",
                json={"messages": [{"role": "user", "content": "01234567890123456789EXTRA"}]},
                headers={"Authorization": "Bearer sk-route-log-key"},
            )

        assert response.status_code == 200
        started_call = next(
            call for call in mock_log_info.call_args_list if call.args[0] == "request_started"
        )
        finished_call = next(
            call for call in mock_log_info.call_args_list if call.args[0] == "request_finished"
        )
        assert started_call.kwargs["query_preview"] == "01234567890123456789EXTRA"
        assert finished_call.kwargs["query_preview"] == "01234567890123456789EXTRA"
        assert finished_call.kwargs["status"] == "completed"

    def test_chat_request_lifecycle_logs_use_50_char_preview(self, isolated_manager) -> None:
        """Chat lifecycle logs should keep a bounded 50-character preview."""
        manager = isolated_manager
        tenant = TenantConfig(
            tenant_id="chat-log-tenant",
            apikey="sk-chat-log-key",
            name="Chat Log Tenant",
            enabled=True,
            base_url_template="http://api.example.com/{model}/v1",
        )
        manager.create(tenant)

        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import ChatResponse, ChatChoice, ChatMessage

        long_query = "0123456789" * 7

        async def mock_chat(self, request, tenant=None, trace=None):
            assert trace is not None
            trace.record_completion(status="completed", finish_reason="chat_completed")
            mini_router.server.logger.info("request_finished", **trace.finished_event())
            return ChatResponse(
                model="gpt-4",
                choices=[
                    ChatChoice(
                        message=ChatMessage(role="assistant", content="Hello!"),
                        finish_reason="stop",
                    )
                ],
            )

        with patch.object(ChatProxy, "chat", mock_chat):
            with patch("mini_router.server.logger.info") as mock_log_info:
                with TestClient(app) as client:
                    response = client.post(
                        "/v1/chat/completions",
                        json={
                            "messages": [{"role": "user", "content": long_query}],
                            "stream": False,
                        },
                        headers={"Authorization": "Bearer sk-chat-log-key"},
                    )

        assert response.status_code == 200
        started_call = next(
            call for call in mock_log_info.call_args_list if call.args[0] == "request_started"
        )
        finished_call = next(
            call for call in mock_log_info.call_args_list if call.args[0] == "request_finished"
        )
        assert started_call.kwargs["query_preview"] == long_query[:50]
        assert finished_call.kwargs["query_preview"] == long_query[:50]

    def test_route_request_logs_no_match_status(self, isolated_manager) -> None:
        """Route endpoint should not label unmatched routing as completed."""
        manager = isolated_manager
        manager.create(
            TenantConfig(
                tenant_id="route-no-match-tenant",
                apikey="sk-route-no-match-key",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
            )
        )
        with patch("mini_router.server.logger.info") as mock_log_info:
            with TestClient(app) as client:
                mini_router.server.get_router().route.return_value = MagicMock(
                    selected_model=None,
                    decision_name=None,
                    matched_rules=[],
                    confidence=0.0,
                    cache_hit=False,
                    cache_response=None,
                    action=MagicMock(value="route"),
                    reject_message=None,
                    signals=None,
                    candidate_models=[],
                    filtered_candidate_models=[],
                    selection_strategy="static",
                    selection_metadata={},
                )
                response = client.post(
                    "/v1/route",
                    json={"messages": [{"role": "user", "content": "unmatched query"}]},
                    headers={"Authorization": "Bearer sk-route-no-match-key"},
                )

        assert response.status_code == 200
        finished_call = next(
            call for call in mock_log_info.call_args_list if call.args[0] == "request_finished"
        )
        assert finished_call.kwargs["status"] == "no_match"
        assert finished_call.kwargs["result"]["finish_reason"] == "no_model_selected"

    def test_route_request_logs_finished_on_error(self, isolated_manager) -> None:
        """Route endpoint should emit request_finished when routing raises."""
        manager = isolated_manager
        manager.create(
            TenantConfig(
                tenant_id="route-error-tenant",
                apikey="sk-route-error-key",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
            )
        )
        with patch("mini_router.server.logger.info") as mock_log_info:
            with TestClient(app, raise_server_exceptions=False) as client:
                mini_router.server.get_router().route.side_effect = RuntimeError("route boom")
                response = client.post(
                    "/v1/route",
                    json={"messages": [{"role": "user", "content": "boom"}]},
                    headers={"Authorization": "Bearer sk-route-error-key"},
                )

        assert response.status_code == 500
        finished_call = next(
            call for call in mock_log_info.call_args_list if call.args[0] == "request_finished"
        )
        assert finished_call.kwargs["status"] == "error"
        assert finished_call.kwargs["result"]["finish_reason"] == "route_error"
        assert finished_call.kwargs["result"]["error_type"] == "RuntimeError"

    def test_route_request_logs_selection_fields(self, isolated_manager) -> None:
        """Route endpoint should preserve selection diagnostics in request_finished."""
        manager = isolated_manager
        manager.create(
            TenantConfig(
                tenant_id="route-selection-tenant",
                apikey="sk-route-selection-key",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
            )
        )
        with patch("mini_router.server.logger.info") as mock_log_info:
            with TestClient(app) as client:
                mini_router.server.get_router().route.return_value = MagicMock(
                    selected_model="tenant-model",
                    decision_name="tenant-decision",
                    matched_rules=["rule-1"],
                    confidence=0.9,
                    cache_hit=False,
                    cache_response=None,
                    action=MagicMock(value="route"),
                    reject_message=None,
                    signals=None,
                    candidate_models=["tenant-model", "tenant-fallback"],
                    filtered_candidate_models=["tenant-model"],
                    selection_strategy="static",
                    selection_metadata={"source": "shared-pipeline"},
                )
                response = client.post(
                    "/v1/route",
                    json={"messages": [{"role": "user", "content": "route selection query"}]},
                    headers={"Authorization": "Bearer sk-route-selection-key"},
                )

        assert response.status_code == 200
        finished_call = next(
            call for call in mock_log_info.call_args_list if call.args[0] == "request_finished"
        )
        assert finished_call.kwargs["selection"]["strategy"] == "static"
        assert finished_call.kwargs["selection"]["candidate_models"] == [
            "tenant-model",
            "tenant-fallback",
        ]
        assert finished_call.kwargs["selection"]["filtered_candidate_models"] == [
            "tenant-model",
        ]

    def test_chat_request_logs_finished_on_error(self, isolated_manager) -> None:
        """Chat endpoint should emit request_finished when routing raises."""
        manager = isolated_manager
        manager.create(
            TenantConfig(
                tenant_id="chat-error-tenant",
                apikey="sk-chat-error-key",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
            )
        )
        with patch("mini_router.server.logger.info") as mock_log_info:
            with TestClient(app, raise_server_exceptions=False) as client:
                mini_router.server.get_router().route.side_effect = RuntimeError("chat route boom")
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": "Hello"}],
                        "stream": False,
                    },
                    headers={"Authorization": "Bearer sk-chat-error-key"},
                )

        assert response.status_code == 500
        finished_call = next(
            call for call in mock_log_info.call_args_list if call.args[0] == "request_finished"
        )
        assert finished_call.kwargs["status"] == "error"
        assert finished_call.kwargs["result"]["finish_reason"] == "chat_request_error"
        assert finished_call.kwargs["result"]["error_type"] == "RuntimeError"

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


class TestRouteWithTenantAuth:
    """Tests for routing endpoint authentication."""

    def test_route_without_auth_returns_401(self, isolated_manager) -> None:
        """Route endpoint should reject missing auth."""
        client = TestClient(app)
        response = client.post(
            "/v1/route",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )

        assert response.status_code == 401
        assert "Authorization" in response.json()["detail"]

    def test_route_with_disabled_tenant_returns_403(self, isolated_manager) -> None:
        """Route endpoint should reject disabled tenant."""
        manager = isolated_manager
        manager.create(
            TenantConfig(
                tenant_id="disabled-route-tenant",
                apikey="sk-disabled-route",
                enabled=False,
                base_url_template="http://api.example.com/{model}/v1",
            )
        )

        client = TestClient(app)
        response = client.post(
            "/v1/route",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": "Bearer sk-disabled-route"},
        )

        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()
