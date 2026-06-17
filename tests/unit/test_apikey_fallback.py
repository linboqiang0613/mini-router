"""Unit tests for API key pool fallback mode."""

import gzip
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from mini_router.logging_utils import RequestTrace
from mini_router.proxy.chat_proxy import ChatProxy
from mini_router.client.openai_client import RawStreamResponse
from mini_router.proxy.types import ChatRequest, ChatMessage, ChatChunk, ChatChoice, ChatChoiceDelta
from mini_router.tenant.types import TenantConfig
from mini_router.config.config import RouterConfig


@pytest.fixture
def tenant_fallback():
    """Tenant with fallback mode configured."""
    return TenantConfig(
        tenant_id="test-fallback",
        apikey="sk-management-key",
        apikey_pool=["sk-key-1", "sk-key-2", "sk-key-3"],
        apikey_pool_mode="fallback",
        base_url_template="http://api.example.com/{model}/v1",
        enabled=True,
    )


@pytest.fixture
def tenant_round_robin():
    """Tenant with round_robin mode configured."""
    return TenantConfig(
        tenant_id="test-round-robin",
        apikey="sk-management-key",
        apikey_pool=["sk-key-1", "sk-key-2", "sk-key-3"],
        apikey_pool_mode="round_robin",
        base_url_template="http://api.example.com/{model}/v1",
        enabled=True,
    )


@pytest.fixture
def tenant_empty_pool():
    """Tenant with empty pool (uses management key)."""
    return TenantConfig(
        tenant_id="test-empty-pool",
        apikey="sk-management-key",
        apikey_pool=[],
        apikey_pool_mode="fallback",
        base_url_template="http://api.example.com/{model}/v1",
        enabled=True,
    )


@pytest.fixture
def tenant_no_mode():
    """Tenant without apikey_pool_mode (should default to round_robin)."""
    return TenantConfig(
        tenant_id="test-no-mode",
        apikey="sk-management-key",
        apikey_pool=["sk-key-1", "sk-key-2"],
        base_url_template="http://api.example.com/{model}/v1",
        enabled=True,
    )


class TestApiKeyPoolModeConfig:
    """Tests for apikey_pool_mode configuration field."""

    def test_default_mode_is_round_robin(self, tenant_no_mode):
        """Tenant without apikey_pool_mode should default to round_robin."""
        assert tenant_no_mode.apikey_pool_mode == "round_robin"

    def test_fallback_mode_config(self, tenant_fallback):
        """Tenant can be configured with fallback mode."""
        assert tenant_fallback.apikey_pool_mode == "fallback"

    def test_round_robin_mode_config(self, tenant_round_robin):
        """Tenant can be configured with round_robin mode."""
        assert tenant_round_robin.apikey_pool_mode == "round_robin"


class TestFallbackMode:
    """Tests for fallback mode behavior."""

    @pytest.mark.asyncio
    async def test_first_key_success(self, tenant_fallback):
        """Fallback mode should use first key by default."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_response = {"id": "test", "choices": [{"message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}]}

        # Track which key was used
        used_keys = []
        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            return mock_response

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False)

        response = await proxy.chat(request, tenant=tenant_fallback)

        assert used_keys == ["sk-key-1"]  # Should use first key
        assert response.choices[0].message.content == "Hello"

    @pytest.mark.asyncio
    async def test_429_triggers_fallback(self, tenant_fallback):
        """429 on first key should trigger fallback to second key."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_response = {"id": "test", "choices": [{"message": {"role": "assistant", "content": "Success"}, "finish_reason": "stop"}]}

        used_keys = []
        call_count = [0]  # Use list to avoid closure issues

        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            current_count = call_count[0]
            call_count[0] += 1

            if current_count == 0:
                # First call with first key - return 429
                response = httpx.Response(429, text="Rate limited")
                raise httpx.HTTPStatusError("429", request=None, response=response)
            else:
                # Second call with second key - success
                return mock_response

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False)

        response = await proxy.chat(request, tenant=tenant_fallback)

        assert used_keys == ["sk-key-1", "sk-key-2"]  # Tried first, then second
        assert response.choices[0].message.content == "Success"

    @pytest.mark.asyncio
    async def test_all_keys_429_returns_error(self, tenant_fallback):
        """All keys returning 429 should raise the error."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()

        used_keys = []

        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            response = httpx.Response(429, text="Rate limited")
            raise httpx.HTTPStatusError("429", request=None, response=response)

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False)

        response = await proxy.chat(request, tenant=tenant_fallback)

        # Should have tried all keys
        assert used_keys == ["sk-key-1", "sk-key-2", "sk-key-3"]
        # Should return error response
        assert response.choices[0].finish_reason == "error"
        assert "429" in response.choices[0].message.content

    @pytest.mark.asyncio
    async def test_non_429_error_no_fallback(self, tenant_fallback):
        """Non-429 errors should not trigger fallback."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()

        used_keys = []

        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            response = httpx.Response(500, text="Internal server error")
            raise httpx.HTTPStatusError("500", request=None, response=response)

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False)

        response = await proxy.chat(request, tenant=tenant_fallback)

        # Should only try first key
        assert used_keys == ["sk-key-1"]
        assert response.choices[0].finish_reason == "error"
        assert "500" in response.choices[0].message.content

    @pytest.mark.asyncio
    async def test_final_upstream_key_is_masked_after_fallback_success(self, tenant_fallback):
        """Finished trace should record the masked final upstream key after fallback."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_response = {
            "id": "test",
            "choices": [{"message": {"role": "assistant", "content": "Success"}, "finish_reason": "stop"}],
        }

        call_count = [0]

        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            current_count = call_count[0]
            call_count[0] += 1
            if current_count == 0:
                response = httpx.Response(429, text="Rate limited")
                raise httpx.HTTPStatusError("429", request=None, response=response)
            return mock_response

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)
        trace = RequestTrace(
            path="/v1/chat/completions",
            method="POST",
            tenant_id=tenant_fallback.tenant_id,
            query="Hi",
            stream=False,
        )

        await proxy.chat(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False),
            tenant=tenant_fallback,
            trace=trace,
        )

        assert trace.finished_event()["result"]["final_upstream_apikey_masked"] == "sk-*****"

    @pytest.mark.asyncio
    async def test_final_upstream_key_is_masked_after_fallback_exhaustion(self, tenant_fallback):
        """Finished trace should record the masked final upstream key after fallback exhaustion."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()

        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            response = httpx.Response(429, text="Rate limited")
            raise httpx.HTTPStatusError("429", request=None, response=response)

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)
        trace = RequestTrace(
            path="/v1/chat/completions",
            method="POST",
            tenant_id=tenant_fallback.tenant_id,
            query="Hi",
            stream=False,
        )

        await proxy.chat(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False),
            tenant=tenant_fallback,
            trace=trace,
        )

        assert trace.finished_event()["result"]["final_upstream_apikey_masked"] == "sk-*****"

    @pytest.mark.asyncio
    async def test_empty_pool_uses_management_key(self, tenant_empty_pool):
        """Empty pool should fallback to management apikey."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_response = {"id": "test", "choices": [{"message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}]}

        used_keys = []
        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            return mock_response

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False)

        response = await proxy.chat(request, tenant=tenant_empty_pool)

        assert used_keys == ["sk-management-key"]

    @pytest.mark.asyncio
    async def test_new_request_starts_from_first_key(self, tenant_fallback):
        """Each new request should start from first key (no state persistence)."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_response = {"id": "test", "choices": [{"message": {"role": "assistant", "content": "Success"}, "finish_reason": "stop"}]}

        used_keys_request1 = []
        used_keys_request2 = []

        async def mock_chat_completion_request1(model, messages, base_url, api_key, **kwargs):
            used_keys_request1.append(api_key)
            return mock_response

        mock_client.chat_completion = mock_chat_completion_request1

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(messages=[ChatMessage(role="user", content="Request 1")], stream=False)

        await proxy.chat(request, tenant=tenant_fallback)

        # Second request - should still start from first key
        async def mock_chat_completion_request2(model, messages, base_url, api_key, **kwargs):
            used_keys_request2.append(api_key)
            return mock_response

        mock_client.chat_completion = mock_chat_completion_request2

        request2 = ChatRequest(messages=[ChatMessage(role="user", content="Request 2")], stream=False)
        await proxy.chat(request2, tenant=tenant_fallback)

        # Both requests should start from first key
        assert used_keys_request1 == ["sk-key-1"]
        assert used_keys_request2 == ["sk-key-1"]


class TestStreamingFallback:
    """Tests for streaming request fallback."""

    @pytest.mark.asyncio
    async def test_stream_start_429_triggers_fallback(self, tenant_fallback):
        """429 at stream start should trigger fallback."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()

        used_keys = []
        call_count = [0]  # Use list to avoid closure issues

        def build_raw_response(
            status_code: int,
            body: bytes | None = None,
            stream_chunks: list[bytes] | None = None,
        ) -> RawStreamResponse:
            response = MagicMock()
            response.status_code = status_code
            response.headers = {"content-type": "text/event-stream" if stream_chunks else "application/json"}
            response.request = httpx.Request("POST", "http://api.example.com/gpt-4/v1/chat/completions")
            response.aread = AsyncMock(return_value=body or b"")
            response.aclose = AsyncMock()

            async def mock_aiter_raw():
                for chunk in stream_chunks or []:
                    yield chunk

            response.aiter_raw = mock_aiter_raw
            return RawStreamResponse(response=response)

        async def mock_open_stream(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            current_count = call_count[0]
            call_count[0] += 1

            if current_count == 0:
                return build_raw_response(429, b'{"error":"rate limited"}')
            return build_raw_response(
                200,
                stream_chunks=[
                    b"event: message\nid: chunk-1\nretry: 1000\ndata: {\"choices\":[{\"delta\":{\"content\":\"Hello\"}}]}\n\n",
                    b": keepalive\n\n",
                    b"data: [DONE]\n\n",
                ],
            )

        mock_client.open_chat_completion_stream = mock_open_stream

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=True)

        prepared = await proxy.chat_stream(request, tenant=tenant_fallback)
        chunks = [chunk async for chunk in prepared.stream]

        assert used_keys == ["sk-key-1", "sk-key-2"]
        assert prepared.status_code == 200
        assert b"".join(chunks).startswith(b"event: message\nid: chunk-1\nretry: 1000\n")

    @pytest.mark.asyncio
    async def test_stream_retryable_status_codes_are_code_defined(self, tenant_fallback, monkeypatch):
        """Code-defined pre-stream retryable statuses should trigger fallback."""
        monkeypatch.setattr(
            "mini_router.proxy.strategies.DEFAULT_RETRYABLE_STATUS_CODES",
            frozenset({429, 503}),
        )
        monkeypatch.setattr(
            "mini_router.proxy.chat_proxy.DEFAULT_RETRYABLE_STATUS_CODES",
            frozenset({429, 503}),
        )
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        used_keys = []
        call_count = [0]

        def build_raw_response(status_code: int, stream_chunks: list[bytes] | None = None) -> RawStreamResponse:
            response = MagicMock()
            response.status_code = status_code
            response.headers = {"content-type": "text/event-stream" if stream_chunks else "application/json"}
            response.request = httpx.Request("POST", "http://api.example.com/gpt-4/v1/chat/completions")
            response.aread = AsyncMock(return_value=b'{"error":"upstream"}')
            response.aclose = AsyncMock()

            async def mock_aiter_raw():
                for chunk in stream_chunks or []:
                    yield chunk

            response.aiter_raw = mock_aiter_raw
            return RawStreamResponse(response=response)

        async def mock_open_stream(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            current = call_count[0]
            call_count[0] += 1
            if current == 0:
                return build_raw_response(503)
            return build_raw_response(200, [b"data: [DONE]\n\n"])

        mock_client.open_chat_completion_stream = mock_open_stream

        proxy = ChatProxy(mock_router, mock_client)
        prepared = await proxy.chat_stream(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=True),
            tenant=tenant_fallback,
        )

        assert prepared.status_code == 200
        assert used_keys == ["sk-key-1", "sk-key-2"]

    @pytest.mark.asyncio
    async def test_stream_pool_exhaustion_returns_final_upstream_error(self, tenant_fallback):
        """All retryable pre-stream failures should return the final upstream error unchanged."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        used_keys = []

        async def mock_open_stream(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            body = f'{{"error":"{api_key}"}}'.encode()
            response = MagicMock()
            response.status_code = 429
            response.headers = {"content-type": "application/json", "x-upstream": "retry"}
            response.request = httpx.Request("POST", "http://api.example.com/gpt-4/v1/chat/completions")
            response.aread = AsyncMock(return_value=body)
            response.aclose = AsyncMock()

            async def mock_aiter_raw():
                yield body

            response.aiter_raw = mock_aiter_raw
            return RawStreamResponse(response=response)

        mock_client.open_chat_completion_stream = mock_open_stream

        proxy = ChatProxy(mock_router, mock_client)
        prepared = await proxy.chat_stream(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=True),
            tenant=tenant_fallback,
        )

        assert used_keys == ["sk-key-1", "sk-key-2", "sk-key-3"]
        assert prepared.stream is None
        assert prepared.status_code == 429
        assert prepared.body == b'{"error":"sk-key-3"}'
        assert prepared.headers["x-upstream"] == "retry"

    @pytest.mark.asyncio
    async def test_stream_error_body_preserves_raw_compressed_bytes(self, tenant_fallback):
        """Pre-stream upstream errors should preserve compressed bodies and encoding headers."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        compressed_body = gzip.compress(b'{"error":"compressed"}')

        async def mock_open_stream(model, messages, base_url, api_key, **kwargs):
            response = MagicMock()
            response.status_code = 500
            response.headers = {
                "content-type": "application/json",
                "content-encoding": "gzip",
            }
            response.request = httpx.Request("POST", "http://api.example.com/gpt-4/v1/chat/completions")
            response.aread = AsyncMock(return_value=b'{"error":"decoded"}')
            response.aclose = AsyncMock()

            async def mock_aiter_raw():
                yield compressed_body[:8]
                yield compressed_body[8:]

            response.aiter_raw = mock_aiter_raw
            return RawStreamResponse(response=response)

        mock_client.open_chat_completion_stream = mock_open_stream

        proxy = ChatProxy(mock_router, mock_client)
        prepared = await proxy.chat_stream(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=True),
            tenant=tenant_fallback,
        )

        assert prepared.status_code == 500
        assert prepared.headers["content-encoding"] == "gzip"
        assert prepared.body == compressed_body

    @pytest.mark.asyncio
    async def test_stream_non_retryable_status_bypasses_fallback(self, tenant_fallback):
        """Non-retryable pre-stream statuses should not trigger fallback."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        used_keys = []

        async def mock_open_stream(model, messages, base_url, api_key, **kwargs):
            body = b'{"error":"server"}'
            used_keys.append(api_key)
            response = MagicMock()
            response.status_code = 500
            response.headers = {"content-type": "application/json"}
            response.request = httpx.Request("POST", "http://api.example.com/gpt-4/v1/chat/completions")
            response.aread = AsyncMock(return_value=body)
            response.aclose = AsyncMock()

            async def mock_aiter_raw():
                yield body

            response.aiter_raw = mock_aiter_raw
            return RawStreamResponse(response=response)

        mock_client.open_chat_completion_stream = mock_open_stream

        proxy = ChatProxy(mock_router, mock_client)
        prepared = await proxy.chat_stream(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=True),
            tenant=tenant_fallback,
        )

        assert used_keys == ["sk-key-1"]
        assert prepared.status_code == 500
        assert prepared.body == b'{"error":"server"}'

    @pytest.mark.asyncio
    async def test_stream_midstream_failure_does_not_retry(self, tenant_fallback):
        """Once downstream streaming starts, fallback must not switch keys."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        used_keys = []

        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "text/event-stream"}
        response.request = httpx.Request("POST", "http://api.example.com/gpt-4/v1/chat/completions")
        response.aread = AsyncMock(return_value=b"")
        response.aclose = AsyncMock()

        async def mock_aiter_raw():
            yield b"data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"}}]}\n\n"
            raise httpx.ReadError("stream dropped")

        response.aiter_raw = mock_aiter_raw

        async def mock_open_stream(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            return RawStreamResponse(response=response)

        mock_client.open_chat_completion_stream = mock_open_stream

        proxy = ChatProxy(mock_router, mock_client)
        prepared = await proxy.chat_stream(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=True),
            tenant=tenant_fallback,
        )

        stream = prepared.stream
        first_chunk = await anext(stream)
        assert first_chunk.startswith(b"data:")
        with pytest.raises(httpx.ReadError):
            await anext(stream)
        assert used_keys == ["sk-key-1"]


class TestRoundRobinMode:
    """Tests for round_robin mode (existing behavior)."""

    @pytest.mark.asyncio
    async def test_round_robin_rotates_keys(self, tenant_round_robin):
        """Round-robin mode should rotate keys per request."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()
        mock_response = {"id": "test", "choices": [{"message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}]}

        used_keys = []
        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            return mock_response

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)

        # First request
        request = ChatRequest(messages=[ChatMessage(role="user", content="Request 1")], stream=False)
        await proxy.chat(request, tenant=tenant_round_robin)

        # Second request
        request2 = ChatRequest(messages=[ChatMessage(role="user", content="Request 2")], stream=False)
        await proxy.chat(request2, tenant=tenant_round_robin)

        # Third request
        request3 = ChatRequest(messages=[ChatMessage(role="user", content="Request 3")], stream=False)
        await proxy.chat(request3, tenant=tenant_round_robin)

        # Should rotate: key1, key2, key3
        assert used_keys == ["sk-key-1", "sk-key-2", "sk-key-3"]

    @pytest.mark.asyncio
    async def test_round_robin_no_fallback_on_429(self, tenant_round_robin):
        """Round-robin mode should not fallback on 429."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=MagicMock(selected_model="gpt-4", decision_name="test"))
        mock_router.record_latency = AsyncMock()

        mock_client = MagicMock()

        used_keys = []

        async def mock_chat_completion(model, messages, base_url, api_key, **kwargs):
            used_keys.append(api_key)
            response = httpx.Response(429, text="Rate limited")
            raise httpx.HTTPStatusError("429", request=None, response=response)

        mock_client.chat_completion = mock_chat_completion

        proxy = ChatProxy(mock_router, mock_client)
        request = ChatRequest(messages=[ChatMessage(role="user", content="Hi")], stream=False)

        response = await proxy.chat(request, tenant=tenant_round_robin)

        # Should only try one key (no fallback)
        assert len(used_keys) == 1
        assert response.choices[0].finish_reason == "error"
