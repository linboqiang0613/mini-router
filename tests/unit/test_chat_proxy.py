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