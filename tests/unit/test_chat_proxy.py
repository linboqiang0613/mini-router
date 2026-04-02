"""Tests for chat proxy."""

import pytest

from mini_router.proxy.types import (
    ChatChunk,
    ChatChoice,
    ChatChoiceDelta,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)


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

        # Mock the stream response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        # Simulate SSE lines
        async def mock_aiter_lines():
            yield "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}"
            yield "data: [DONE]"

        mock_response.aiter_lines = mock_aiter_lines

        # Mock the stream method to return an async context manager
        mock_stream_context = MagicMock()
        mock_stream_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_context.__aexit__ = AsyncMock(return_value=None)
        mock_httpx_client.stream = MagicMock(return_value=mock_stream_context)

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
            call_args = mock_httpx_client.stream.call_args
            # stream is called with ("POST", url, headers=headers, json=payload)
            assert call_args[0][1] == "http://dynamic-api.com/v1/chat/completions"
            assert "Bearer dynamic-key" in call_args[1]["headers"]["Authorization"]

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