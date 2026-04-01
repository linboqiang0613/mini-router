"""Types for chat proxy."""

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str
    content: str
    name: str | None = None


class ChatRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str | None = None  # Optional - router will select if not provided
    messages: list[ChatMessage]
    stream: bool = True
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    n: int | None = None
    stop: str | list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    user: str | None = None
    # Additional parameters
    metadata: dict[str, Any] | None = None


class ChatChoiceDelta(BaseModel):
    """Delta content in a streaming choice."""

    role: str | None = None
    content: str | None = None


class ChatChoice(BaseModel):
    """A choice in chat completion."""

    index: int = 0
    delta: ChatChoiceDelta | None = None
    message: ChatMessage | None = None
    finish_reason: str | None = None


class ChatUsage(BaseModel):
    """Token usage information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatChunk(BaseModel):
    """A streaming chat completion chunk."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:8]}")
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatChoice]

    def to_sse(self) -> str:
        """Convert to SSE format."""
        return f"data: {self.model_dump_json()}\n\n"


class ChatResponse(BaseModel):
    """A complete (non-streaming) chat completion response."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:8]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatChoice]
    usage: ChatUsage | None = None


class ChatProxyResult(BaseModel):
    """Result of a chat proxy operation."""

    selected_model: str
    decision_name: str | None = None
    confidence: float = 1.0
    latency_seconds: float = 0.0
    ttft: float | None = None  # Time to first token
    tokens_generated: int = 0
    success: bool = True
    error: str | None = None