"""Tests for chat proxy."""

import httpx
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from mini_router.proxy.types import (
    ChatChunk,
    ChatChoice,
    ChatChoiceDelta,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)
from mini_router.logging_utils import RequestTrace


class TestChatTypes:
    """Tests for chat proxy types."""

    def test_chat_message(self) -> None:
        """Test ChatMessage model."""
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_chat_request(self) -> None:
        """Test ChatRequest model."""
        request = ChatRequest(
            messages=[
                ChatMessage(role="user", content="Hello"),
            ],
            stream=True,
        )
        assert len(request.messages) == 1
        assert request.stream is True
        assert request.model is None
        assert request.temperature is None

    def test_chat_request_with_model(self) -> None:
        """Test ChatRequest with explicit model."""
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="Hello"),
            ],
        )
        assert request.model == "gpt-4"

    def test_chat_choice_delta(self) -> None:
        """Test ChatChoiceDelta model."""
        delta = ChatChoiceDelta(role="assistant", content="Hello")
        assert delta.role == "assistant"
        assert delta.content == "Hello"

    def test_chat_choice(self) -> None:
        """Test ChatChoice model."""
        choice = ChatChoice(
            index=0,
            delta=ChatChoiceDelta(content="test"),
            finish_reason="stop",
        )
        assert choice.index == 0
        assert choice.delta.content == "test"
        assert choice.finish_reason == "stop"

    def test_chat_chunk(self) -> None:
        """Test ChatChunk model."""
        chunk = ChatChunk(
            model="gpt-4",
            choices=[
                ChatChoice(
                    delta=ChatChoiceDelta(content="Hello"),
                )
            ],
        )
        assert chunk.model == "gpt-4"
        assert len(chunk.choices) == 1
        assert chunk.choices[0].delta.content == "Hello"

    def test_chat_chunk_to_sse(self) -> None:
        """Test ChatChunk SSE serialization."""
        chunk = ChatChunk(
            id="test-123",
            model="gpt-4",
            choices=[
                ChatChoice(
                    delta=ChatChoiceDelta(content="Hello"),
                )
            ],
        )
        sse = chunk.to_sse()
        assert sse.startswith("data: ")
        assert "test-123" in sse
        assert "Hello" in sse
        assert sse.endswith("\n\n")

    def test_chat_response(self) -> None:
        """Test ChatResponse model."""
        response = ChatResponse(
            model="gpt-4",
            choices=[
                ChatChoice(
                    message=ChatMessage(role="assistant", content="Hello"),
                    finish_reason="stop",
                )
            ],
        )
        assert response.model == "gpt-4"
        assert response.choices[0].message.content == "Hello"


class TestChatProxy:
    """Tests for ChatProxy service."""

    def test_extract_query(self) -> None:
        """Test query extraction from messages."""
        from mini_router.proxy.chat_proxy import ChatProxy

        # Create a mock router and client
        class MockRouter:
            pass

        class MockClient:
            pass

        proxy = ChatProxy(MockRouter(), MockClient())

        messages = [
            ChatMessage(role="system", content="You are helpful"),
            ChatMessage(role="user", content="Hello world"),
        ]

        query = proxy._extract_query(messages)
        assert query == "Hello world"

    def test_extract_query_no_user(self) -> None:
        """Test query extraction with no user message."""
        from mini_router.proxy.chat_proxy import ChatProxy

        class MockRouter:
            pass

        class MockClient:
            pass

        proxy = ChatProxy(MockRouter(), MockClient())

        messages = [
            ChatMessage(role="system", content="You are helpful"),
            ChatMessage(role="assistant", content="Hi there"),
        ]

        query = proxy._extract_query(messages)
        assert "You are helpful" in query
        assert "Hi there" in query

    @pytest.mark.asyncio
    async def test_chat_records_request_finished_trace(self) -> None:
        """Non-streaming chat should populate and emit completion trace data."""
        from mini_router.proxy.chat_proxy import ChatProxy

        mock_router = MagicMock()
        mock_router.route = AsyncMock(
            return_value=MagicMock(
                selected_model="gpt-4",
                decision_name="route-test",
                matched_rules=["code_related"],
                confidence=0.9,
                cache_hit=False,
                cache_response=None,
                action=MagicMock(value="route"),
                reject_message=None,
                signals=None,
                candidate_models=["gpt-4", "gpt-4o"],
                filtered_candidate_models=["gpt-4"],
                selection_strategy="static",
                selection_metadata={"source": "test"},
            )
        )
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_client.chat_completion = AsyncMock(
            return_value={
                "id": "test-123",
                "choices": [
                    {"message": {"role": "assistant", "content": "Hello"}}
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 3,
                    "total_tokens": 13,
                },
            }
        )

        proxy = ChatProxy(mock_router, mock_client)
        trace = RequestTrace(
            path="/v1/chat/completions",
            method="POST",
            tenant_id="tenant-1",
            query="Hello router",
            stream=False,
        )

        with patch("mini_router.proxy.chat_proxy.logger.info") as mock_info:
            response = await proxy.chat(
                ChatRequest(messages=[ChatMessage(role="user", content="Hello router")], stream=False),
                trace=trace,
            )

        assert response.model == "gpt-4"
        assert trace.status == "completed"
        assert trace.finish_reason == "chat_completed"
        assert trace.selection_strategy == "static"
        assert trace.candidate_models == ["gpt-4", "gpt-4o"]
        assert trace.filtered_candidate_models == ["gpt-4"]
        assert trace.usage.total_tokens == 13
        assert any(call.args[0] == "request_finished" for call in mock_info.call_args_list)

    @pytest.mark.asyncio
    async def test_chat_reuses_precomputed_routing_trace(self) -> None:
        """Chat should reuse a pre-routed trace instead of routing twice."""
        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.tenant.types import TenantConfig

        precomputed_result = MagicMock(
            selected_model="gpt-4",
            decision_name="route-test",
            matched_rules=["code_related"],
            confidence=0.9,
            cache_hit=False,
            cache_response=None,
            action=MagicMock(value="route"),
            reject_message=None,
            signals=None,
            candidate_models=["gpt-4"],
            filtered_candidate_models=["gpt-4"],
            selection_strategy="static",
            selection_metadata={"source": "shared-pipeline"},
        )

        mock_router = MagicMock()
        mock_router.route = AsyncMock()
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_client.chat_completion = AsyncMock(
            return_value={
                "id": "test-123",
                "choices": [
                    {"message": {"role": "assistant", "content": "Hello"}}
                ],
            }
        )

        proxy = ChatProxy(mock_router, mock_client)
        trace = RequestTrace(
            path="/v1/chat/completions",
            method="POST",
            tenant_id="tenant-1",
            query="Hello router",
            stream=False,
        )
        trace.apply_routing_result(precomputed_result)

        tenant = TenantConfig(
            tenant_id="tenant-1",
            apikey="tenant-apikey",
            name="Test Tenant",
            enabled=True,
            base_url_template="http://tenant-api.com/llm/{model}/v1",
        )

        response = await proxy.chat(
            ChatRequest(messages=[ChatMessage(role="user", content="Hello router")], stream=False),
            tenant=tenant,
            trace=trace,
        )

        assert response.model == "gpt-4"
        mock_router.route.assert_not_called()

    @pytest.mark.asyncio
    async def test_chat_stream_records_chunk_count_on_completion(self) -> None:
        """Transparent streaming should emit request_finished after stream completion."""
        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.client.openai_client import RawStreamResponse

        mock_router = MagicMock()
        mock_router.route = AsyncMock(
            return_value=MagicMock(
                selected_model="gpt-4",
                decision_name="route-test",
                matched_rules=["code_related"],
                confidence=0.9,
                cache_hit=False,
                cache_response=None,
                action=MagicMock(value="route"),
                reject_message=None,
                signals=None,
                candidate_models=["gpt-4"],
                filtered_candidate_models=["gpt-4"],
                selection_strategy="static",
                selection_metadata={},
            )
        )
        mock_router.record_latency = AsyncMock()

        async def mock_aiter_raw():
            yield b"data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}\n\n"
            yield b"data: {\"choices\": [{\"delta\": {\"content\": \" world\"}}]}\n\n"
            yield b"data: [DONE]\n\n"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/event-stream"}
        mock_response.request = httpx.Request("POST", "http://api.example.com/v1/chat/completions")
        mock_response.aiter_raw = mock_aiter_raw
        mock_response.aclose = AsyncMock()

        mock_client = MagicMock()
        mock_client.open_chat_completion_stream = AsyncMock(
            return_value=RawStreamResponse(response=mock_response)
        )

        proxy = ChatProxy(mock_router, mock_client)
        trace = RequestTrace(
            path="/v1/chat/completions",
            method="POST",
            tenant_id="tenant-1",
            query="Hello router",
            stream=True,
        )

        with patch("mini_router.proxy.chat_proxy.logger.info") as mock_info:
            prepared = await proxy.chat_stream(
                ChatRequest(messages=[ChatMessage(role="user", content="Hello router")], stream=True),
                trace=trace,
            )
            chunks = [chunk async for chunk in prepared.stream]

        assert prepared.status_code == 200
        assert b"".join(chunks).endswith(b"data: [DONE]\n\n")
        assert trace.status == "completed"
        assert trace.finish_reason == "stream_completed"
        assert trace.chunk_count == 2
        assert any(call.args[0] == "request_finished" for call in mock_info.call_args_list)


class TestDynamicClient:
    """Tests for OpenAIClient with dynamic base_url and api_key."""

    @pytest.mark.asyncio
    async def test_chat_completion_with_dynamic_params(self) -> None:
        """Test chat_completion accepts dynamic base_url and api_key."""
        from unittest.mock import AsyncMock, patch, MagicMock

        # Mock httpx.AsyncClient to avoid proxy issues
        mock_httpx_client = MagicMock()
        mock_httpx_client.post = AsyncMock()

        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            from mini_router.client.openai_client import OpenAIClient

            client = OpenAIClient(timeout=60.0)

            result = await client.chat_completion(
                model="gpt-4",
                messages=[{"role": "user", "content": "Hello"}],
                base_url="http://dynamic-api.com/v1",
                api_key="dynamic-key",
            )

            # Verify the call was made with correct URL
            call_args = mock_httpx_client.post.call_args
            assert call_args[0][0] == "http://dynamic-api.com/v1/chat/completions"
            assert "Bearer dynamic-key" in call_args[1]["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_chat_completion_without_api_key(self) -> None:
        """Test chat_completion works without api_key."""
        from unittest.mock import AsyncMock, patch, MagicMock

        # Mock httpx.AsyncClient to avoid proxy issues
        mock_httpx_client = MagicMock()
        mock_httpx_client.post = AsyncMock()

        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            from mini_router.client.openai_client import OpenAIClient

            client = OpenAIClient(timeout=60.0)

            result = await client.chat_completion(
                model="gpt-4",
                messages=[{"role": "user", "content": "Hello"}],
                base_url="http://api.com/v1",
                api_key="",  # Empty api_key
            )

            # Verify no Authorization header when api_key is empty
            call_args = mock_httpx_client.post.call_args
            assert "Authorization" not in call_args[1]["headers"]

    @pytest.mark.asyncio
    async def test_chat_completion_stream_with_dynamic_params(self) -> None:
        """Test chat_completion_stream accepts dynamic base_url and api_key."""
        from unittest.mock import AsyncMock, patch, MagicMock

        # Mock httpx.AsyncClient to avoid proxy issues
        mock_httpx_client = MagicMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aclose = AsyncMock()
        mock_response.request = httpx.Request(
            "POST",
            "http://dynamic-api.com/v1/chat/completions",
        )

        # Simulate SSE lines
        async def mock_aiter_lines():
            yield "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}"
            yield "data: [DONE]"

        mock_response.aiter_lines = mock_aiter_lines
        mock_httpx_client.build_request.return_value = mock_response.request
        mock_httpx_client.send = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            from mini_router.client.openai_client import OpenAIClient

            client = OpenAIClient(timeout=60.0)

            chunks = []
            async for chunk in client.chat_completion_stream(
                model="gpt-4",
                messages=[{"role": "user", "content": "Hello"}],
                base_url="http://dynamic-api.com/v1",
                api_key="dynamic-key",
            ):
                chunks.append(chunk)

            # Verify we got chunks
            assert len(chunks) == 1
            assert chunks[0]["choices"][0]["delta"]["content"] == "Hello"

            # Verify the call was made with correct URL
            build_call = mock_httpx_client.build_request.call_args
            assert build_call[0][1] == "http://dynamic-api.com/v1/chat/completions"
            assert "Bearer dynamic-key" in build_call[1]["headers"]["Authorization"]
            mock_httpx_client.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_completion_backward_compatibility(self) -> None:
        """Test chat_completion uses constructor params when per-request params not provided."""
        from unittest.mock import AsyncMock, patch, MagicMock

        # Mock httpx.AsyncClient to avoid proxy issues
        mock_httpx_client = MagicMock()
        mock_httpx_client.post = AsyncMock()

        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            from mini_router.client.openai_client import OpenAIClient

            # Create client with constructor params (backward compatibility)
            client = OpenAIClient(
                timeout=60.0,
                base_url="http://constructor-api.com/v1",
                api_key="constructor-key",
            )

            # Call without per-request base_url/api_key
            result = await client.chat_completion(
                model="gpt-4",
                messages=[{"role": "user", "content": "Hello"}],
            )

            # Verify constructor params were used
            call_args = mock_httpx_client.post.call_args
            assert call_args[0][0] == "http://constructor-api.com/v1/chat/completions"
            assert "Bearer constructor-key" in call_args[1]["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_chat_completion_per_request_overrides_constructor(self) -> None:
        """Test per-request params override constructor params."""
        from unittest.mock import AsyncMock, patch, MagicMock

        # Mock httpx.AsyncClient to avoid proxy issues
        mock_httpx_client = MagicMock()
        mock_httpx_client.post = AsyncMock()

        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            from mini_router.client.openai_client import OpenAIClient

            # Create client with constructor params
            client = OpenAIClient(
                timeout=60.0,
                base_url="http://constructor-api.com/v1",
                api_key="constructor-key",
            )

            # Call with per-request params (should override constructor)
            result = await client.chat_completion(
                model="gpt-4",
                messages=[{"role": "user", "content": "Hello"}],
                base_url="http://per-request-api.com/v1",
                api_key="per-request-key",
            )

            # Verify per-request params were used (not constructor)
            call_args = mock_httpx_client.post.call_args
            assert call_args[0][0] == "http://per-request-api.com/v1/chat/completions"
            assert "Bearer per-request-key" in call_args[1]["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_chat_completion_raises_when_no_base_url(self) -> None:
        """Test ValueError raised when base_url not provided anywhere."""
        from unittest.mock import patch, MagicMock
        from mini_router.client.openai_client import OpenAIClient

        mock_httpx_client = MagicMock()
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            client = OpenAIClient(timeout=60.0)  # No base_url in constructor

            # Call without base_url - should raise ValueError
            with pytest.raises(ValueError, match="base_url is required"):
                await client.chat_completion(
                    model="gpt-4",
                    messages=[{"role": "user", "content": "Hello"}],
                )


class TestTenantAuthentication:
    """Tests for tenant authentication in ChatProxy."""

    def test_extract_apikey_valid(self) -> None:
        """Test extract_apikey with valid Bearer token."""
        from mini_router.proxy.chat_proxy import ChatProxy

        apikey = ChatProxy.extract_apikey("Bearer sk-test-123")
        assert apikey == "sk-test-123"

    def test_extract_apikey_with_extra_spaces(self) -> None:
        """Test extract_apikey handles extra spaces."""
        from mini_router.proxy.chat_proxy import ChatProxy

        apikey = ChatProxy.extract_apikey("Bearer   sk-test-123  ")
        assert apikey == "sk-test-123"

    def test_extract_apikey_none_header(self) -> None:
        """Test extract_apikey with None header."""
        from mini_router.proxy.chat_proxy import ChatProxy

        apikey = ChatProxy.extract_apikey(None)
        assert apikey is None

    def test_extract_apikey_empty_header(self) -> None:
        """Test extract_apikey with empty header."""
        from mini_router.proxy.chat_proxy import ChatProxy

        apikey = ChatProxy.extract_apikey("")
        assert apikey is None

    def test_extract_apikey_no_bearer_prefix(self) -> None:
        """Test extract_apikey without Bearer prefix."""
        from mini_router.proxy.chat_proxy import ChatProxy

        apikey = ChatProxy.extract_apikey("sk-test-123")
        assert apikey is None

    def test_extract_apikey_bearer_only(self) -> None:
        """Test extract_apikey with Bearer prefix only."""
        from mini_router.proxy.chat_proxy import ChatProxy

        apikey = ChatProxy.extract_apikey("Bearer ")
        assert apikey is None

    def test_authenticate_tenant_success(self) -> None:
        """Test authenticate_tenant with valid tenant."""
        from unittest.mock import MagicMock
        from mini_router.proxy.chat_proxy import ChatProxy, AuthenticationError, TenantDisabledError
        from mini_router.tenant.types import TenantConfig

        # Create mock tenant manager
        tenant = TenantConfig(
            tenant_id="tenant-1",
            apikey="sk-test-123",
            name="Test Tenant",
            enabled=True,
            base_url_template="http://api.com/llm/{model}/v1",
        )

        mock_manager = MagicMock()
        mock_manager.get_by_apikey.return_value = tenant

        # Authenticate
        result = ChatProxy.authenticate_tenant(mock_manager, "sk-test-123")
        assert result.tenant_id == "tenant-1"
        assert result.enabled is True

    def test_authenticate_tenant_not_found(self) -> None:
        """Test authenticate_tenant with invalid apikey."""
        from unittest.mock import MagicMock
        from mini_router.proxy.chat_proxy import ChatProxy, AuthenticationError

        mock_manager = MagicMock()
        mock_manager.get_by_apikey.return_value = None

        # Should raise AuthenticationError
        with pytest.raises(AuthenticationError, match="Invalid API key"):
            ChatProxy.authenticate_tenant(mock_manager, "sk-invalid")

    def test_authenticate_tenant_disabled(self) -> None:
        """Test authenticate_tenant with disabled tenant."""
        from unittest.mock import MagicMock
        from mini_router.proxy.chat_proxy import ChatProxy, TenantDisabledError
        from mini_router.tenant.types import TenantConfig

        tenant = TenantConfig(
            tenant_id="tenant-1",
            apikey="sk-test-123",
            name="Test Tenant",
            enabled=False,
            base_url_template="http://api.com/llm/{model}/v1",
        )

        mock_manager = MagicMock()
        mock_manager.get_by_apikey.return_value = tenant

        # Should raise TenantDisabledError
        with pytest.raises(TenantDisabledError, match="disabled"):
            ChatProxy.authenticate_tenant(mock_manager, "sk-test-123")

    @pytest.mark.asyncio
    async def test_chat_with_tenant(self) -> None:
        """Test chat method uses tenant decisions and base_url."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import ChatRequest, ChatMessage
        from mini_router.tenant.types import TenantConfig
        from mini_router.config.config import Decision, RuleNode, RuleType, ModelRef

        # Create mock router
        mock_router = MagicMock()
        mock_router.route = AsyncMock()
        mock_router.route.return_value = MagicMock(
            selected_model="gpt-4",
            decision_name="tenant-decision",
            confidence=0.9,
        )
        mock_router.record_latency = AsyncMock()

        # Create mock client
        mock_client = MagicMock()
        mock_client.chat_completion = AsyncMock()
        mock_client.chat_completion.return_value = {
            "id": "test-123",
            "choices": [
                {"message": {"role": "assistant", "content": "Hello"}}
            ],
        }

        # Create tenant with decisions
        tenant = TenantConfig(
            tenant_id="tenant-1",
            apikey="tenant-apikey",
            name="Test Tenant",
            enabled=True,
            base_url_template="http://tenant-api.com/llm/{model}/v1",
            decisions=[
                Decision(
                    name="tenant-rule",
                    priority=1,
                    rules=RuleNode(type=RuleType.KEYWORD, value="test"),
                    model_refs=[ModelRef(model="gpt-4", weight=1.0)],
                )
            ],
        )

        # Create proxy and call chat
        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
        )

        response = await proxy.chat(request, tenant=tenant)

        # Verify router was called with tenant decisions
        mock_router.route.assert_called_once()
        call_args = mock_router.route.call_args
        assert call_args[1]["decisions"] == tenant.decisions

        # Verify client was called with tenant base_url and api_key
        mock_client.chat_completion.assert_called_once()
        client_call_args = mock_client.chat_completion.call_args
        assert client_call_args[1]["base_url"] == "http://tenant-api.com/llm/gpt-4/v1"
        assert client_call_args[1]["api_key"] == "tenant-apikey"

    @pytest.mark.asyncio
    async def test_chat_ignores_requested_model_and_routes(self) -> None:
        """Chat should ignore request.model and still route through tenant policy."""
        from unittest.mock import AsyncMock, MagicMock
        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import ChatRequest, ChatMessage
        from mini_router.tenant.types import TenantConfig

        mock_router = MagicMock()
        mock_router.route = AsyncMock(
            return_value=MagicMock(
                selected_model="tenant-selected-model",
                decision_name="tenant-decision",
                confidence=0.9,
            )
        )
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_client.chat_completion = AsyncMock(
            return_value={
                "id": "test-123",
                "choices": [
                    {"message": {"role": "assistant", "content": "Hello"}}
                ],
            }
        )

        tenant = TenantConfig(
            tenant_id="tenant-1",
            apikey="tenant-apikey",
            name="Test Tenant",
            enabled=True,
            base_url_template="http://tenant-api.com/llm/{model}/v1",
        )

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(
            model="caller-requested-model",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
        )

        response = await proxy.chat(request, tenant=tenant)

        mock_router.route.assert_called_once()
        assert response.model == "tenant-selected-model"
        client_call_args = mock_client.chat_completion.call_args
        assert client_call_args[1]["model"] == "tenant-selected-model"

    @pytest.mark.asyncio
    async def test_chat_without_tenant(self) -> None:
        """Test chat method works without tenant (backward compatibility)."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from mini_router.proxy.chat_proxy import ChatProxy
        from mini_router.proxy.types import ChatRequest, ChatMessage

        # Create mock router
        mock_router = MagicMock()
        mock_router.route = AsyncMock()
        mock_router.route.return_value = MagicMock(
            selected_model="gpt-4",
            decision_name="default-decision",
            confidence=0.9,
        )
        mock_router.record_latency = AsyncMock()

        # Create mock client
        mock_client = MagicMock()
        mock_client.chat_completion = AsyncMock()
        mock_client.chat_completion.return_value = {
            "id": "test-123",
            "choices": [
                {"message": {"role": "assistant", "content": "Hello"}}
            ],
        }

        # Create proxy and call chat without tenant
        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
        )

        response = await proxy.chat(request)

        # Verify router was called without decisions
        mock_router.route.assert_called_once()
        call_args = mock_router.route.call_args
        assert call_args[1]["decisions"] is None

        # Verify client was called without base_url and api_key
        mock_client.chat_completion.assert_called_once()
        client_call_args = mock_client.chat_completion.call_args
        assert client_call_args[1]["base_url"] is None
        assert client_call_args[1]["api_key"] is None
