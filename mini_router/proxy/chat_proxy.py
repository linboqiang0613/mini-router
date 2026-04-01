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
from mini_router.signal_layer.classifier import OpenAIClient

logger = structlog.get_logger()


class ChatProxy:
    """Proxy service that routes chat requests and forwards to selected models."""

    def __init__(self, router: Router, client: OpenAIClient) -> None:
        """Initialize the chat proxy.

        Args:
            router: The router instance for routing decisions
            client: The OpenAI client for making API calls
        """
        self.router = router
        self.client = client

    async def chat_stream(
        self,
        request: ChatRequest,
    ) -> AsyncGenerator[ChatChunk, None]:
        """Process a streaming chat request.

        Yields ChatChunk objects for SSE streaming.

        Flow:
        1. Extract query from messages
        2. Route to select model (if not specified)
        3. Forward request to selected model
        4. Stream response back
        5. Record latency automatically
        """
        import time

        # Extract query from last user message
        query = self._extract_query(request.messages)

        # Route if model not specified
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
                )
            )
            selected_model = routing_result.selected_model
            decision_name = routing_result.decision_name
            confidence = routing_result.confidence

            if not selected_model:
                # Return error chunk
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

            # Stream from selected model
            messages = [msg.model_dump() for msg in request.messages]

            async for chunk in self.client.chat_completion_stream(
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
                error=str(e),
                error_type=type(e).__name__,
            )
            # Yield error chunk
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

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Process a non-streaming chat request.

        Returns a complete ChatResponse.
        """
        import time

        # Extract query from last user message
        query = self._extract_query(request.messages)

        # Route if model not specified
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
                )
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

            # Call API (non-streaming)
            messages = [msg.model_dump() for msg in request.messages]

            response = await self.client.chat_completion(
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