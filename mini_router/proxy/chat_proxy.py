"""Chat proxy service - routes and forwards chat requests."""

import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import structlog

from mini_router.proxy.apikey_selector import ApiKeyPoolSelector
from mini_router.proxy.strategies import ApiKeyStrategy, create_apikey_strategy
from mini_router.proxy.types import (
    ChatChoice,
    ChatChoiceDelta,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatUsage,
)
from mini_router.router.router import Router, RoutingRequest
from mini_router.signal_layer.classifier import OpenAIClient
from mini_router.tenant.types import TenantConfig, build_base_url

logger = structlog.get_logger()


class AuthenticationError(Exception):
    """Raised when API key is missing or invalid."""

    pass


class TenantDisabledError(Exception):
    """Raised when tenant is disabled."""

    pass


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
        self.apikey_selector = ApiKeyPoolSelector()

    @staticmethod
    def extract_apikey(authorization: str | None) -> str | None:
        """Extract API key from Authorization header.

        Args:
            authorization: The Authorization header value (e.g., "Bearer apikey")

        Returns:
            The extracted API key, or None if not found/invalid format.
        """
        if not authorization:
            return None

        # Check for Bearer token format
        if not authorization.startswith("Bearer "):
            return None

        # Extract the token after "Bearer "
        apikey = authorization[7:].strip()
        if not apikey:
            return None

        return apikey

    @staticmethod
    def authenticate_tenant(
        tenant_manager: Any,
        apikey: str,
    ) -> TenantConfig:
        """Authenticate a tenant by API key.

        Args:
            tenant_manager: The TenantManager instance for lookup
            apikey: The API key to authenticate

        Returns:
            The authenticated TenantConfig

        Raises:
            AuthenticationError: If API key is invalid or tenant not found
            TenantDisabledError: If tenant is disabled
        """
        tenant = tenant_manager.get_by_apikey(apikey)

        if tenant is None:
            raise AuthenticationError("Invalid API key: tenant not found")

        if not tenant.enabled:
            raise TenantDisabledError(f"Tenant '{tenant.tenant_id}' is disabled")

        return tenant

    def _get_apikey_pool(self, tenant: TenantConfig) -> list[str]:
        """Get the API key pool for a tenant.

        Returns the pool if available, otherwise returns a single-item list
        with the management apikey.

        Args:
            tenant: The tenant configuration

        Returns:
            List of API keys to try
        """
        if tenant.apikey_pool:
            return tenant.apikey_pool
        return [tenant.apikey]

    def _process_stream_chunk(
        self, chunk: dict[str, Any], selected_model: str
    ) -> ChatChunk:
        """Process a streaming chunk into ChatChunk format.

        Args:
            chunk: Raw chunk from API
            selected_model: Model name

        Returns:
            Formatted ChatChunk
        """
        choices = chunk.get("choices", [])
        chat_choices = []

        for choice in choices:
            delta = choice.get("delta", {})
            chat_choices.append(
                ChatChoice(
                    index=choice.get("index", 0),
                    delta=ChatChoiceDelta(
                        role=delta.get("role"),
                        content=delta.get("content") if delta.get("content") else None,
                        tool_calls=delta.get("tool_calls"),
                    ),
                    finish_reason=choice.get("finish_reason"),
                )
            )

        return ChatChunk(
            id=chunk.get("id", f"chatcmpl-{selected_model}"),
            model=selected_model,
            choices=chat_choices,
        )

    async def _record_stream_latency(
        self,
        start_time: float,
        first_token_time: float | None,
        token_count: int,
        model: str,
        tenant_id: str | None,
        decision_name: str | None,
    ) -> None:
        """Record streaming latency metrics.

        Args:
            start_time: Request start time
            first_token_time: First token arrival time
            token_count: Number of tokens generated
            model: Model name
            tenant_id: Tenant ID (for logging)
            decision_name: Decision name (for logging)
        """
        end_time = time.time()
        total_latency = end_time - start_time
        ttft = first_token_time - start_time if first_token_time else None
        tpot = None
        if token_count > 0 and first_token_time:
            tpot = (end_time - first_token_time) / token_count

        await self.router.record_latency(
            model=model,
            latency_seconds=total_latency,
            tpot=tpot,
            ttft=ttft,
        )

        logger.info(
            "chat_proxy_stream_completed",
            model=model,
            decision=decision_name,
            tenant_id=tenant_id,
            latency=total_latency,
            ttft=ttft,
            tpot=tpot,
            tokens=token_count,
        )

    async def chat_stream(
        self,
        request: ChatRequest,
        tenant: TenantConfig | None = None,
        strategy: ApiKeyStrategy | None = None,
    ) -> AsyncGenerator[ChatChunk, None]:
        """Process a streaming chat request.

        Args:
            request: The chat request to process
            tenant: Optional tenant configuration for tenant-specific routing
            strategy: Optional API key selection strategy. If None, uses tenant config.

        Yields ChatChunk objects for SSE streaming.

        Flow:
        1. Extract query from messages
        2. Route to select model (if not specified)
        3. Forward request to selected model
        4. Stream response back
        5. Record latency automatically
        """
        # Extract query from last user message
        query = self._extract_query(request.messages)

        # Route if model not specified
        if request.model:
            selected_model = request.model
            decision_name = None
        else:
            # Use tenant decisions if provided
            decisions = tenant.decisions if tenant else None
            routing_result = await self.router.route(
                RoutingRequest(
                    query=query,
                    user_id=request.user,
                    metadata=request.metadata or {},
                ),
                decisions=decisions,
            )
            selected_model = routing_result.selected_model
            decision_name = routing_result.decision_name

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
            if request.chat_template_kwargs is not None:
                kwargs["chat_template_kwargs"] = request.chat_template_kwargs
            if request.tools is not None:
                kwargs["tools"] = request.tools
            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice

            messages = [msg.model_dump() for msg in request.messages]

            # Build base_url from tenant template or use default
            base_url = None
            if tenant:
                base_url = build_base_url(tenant.base_url_template, selected_model)

            # Get strategy and pool
            if tenant:
                if strategy is None:
                    strategy = create_apikey_strategy(
                        tenant.apikey_pool_mode, self.apikey_selector
                    )
                pool = self._get_apikey_pool(tenant)

                # Unified key selection via strategy
                current_key = await strategy.select_key(pool, tenant.tenant_id)

                # Unified streaming with strategy-based retry
                while current_key:
                    try:
                        async for chunk in self.client.chat_completion_stream(
                            model=selected_model,
                            messages=messages,
                            base_url=base_url,
                            api_key=current_key,
                            **kwargs,
                        ):
                            if first_token_time is None:
                                first_token_time = time.time()

                            # Count tokens
                            choices = chunk.get("choices", [])
                            for choice in choices:
                                delta = choice.get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    token_count += 1

                            yield self._process_stream_chunk(chunk, selected_model)

                        # Success - record latency and exit
                        await self._record_stream_latency(
                            start_time,
                            first_token_time,
                            token_count,
                            selected_model,
                            tenant.tenant_id,
                            decision_name,
                        )
                        return

                    except Exception as e:
                        next_key = strategy.next_key_on_error(pool, current_key, e)
                        if next_key is None:
                            raise  # No retry
                        current_key = next_key
                        # Reset timing for retry
                        first_token_time = None
                        token_count = 0
            else:
                # No tenant - direct stream without strategy
                async for chunk in self.client.chat_completion_stream(
                    model=selected_model,
                    messages=messages,
                    base_url=base_url,
                    api_key=None,
                    **kwargs,
                ):
                    if first_token_time is None:
                        first_token_time = time.time()

                    choices = chunk.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            token_count += 1

                    yield self._process_stream_chunk(chunk, selected_model)

                await self._record_stream_latency(
                    start_time,
                    first_token_time,
                    token_count,
                    selected_model,
                    None,
                    decision_name,
                )

        except Exception as e:
            logger.error(
                "chat_proxy_stream_error",
                model=selected_model,
                tenant_id=tenant.tenant_id if tenant else None,
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

    async def chat(
        self,
        request: ChatRequest,
        tenant: TenantConfig | None = None,
        strategy: ApiKeyStrategy | None = None,
    ) -> ChatResponse:
        """Process a non-streaming chat request.

        Args:
            request: The chat request to process
            tenant: Optional tenant configuration for tenant-specific routing
            strategy: Optional API key selection strategy. If None, uses tenant config.

        Returns a complete ChatResponse.
        """
        # Extract query from last user message
        query = self._extract_query(request.messages)

        # Route if model not specified
        if request.model:
            selected_model = request.model
            decision_name = None
        else:
            decisions = tenant.decisions if tenant else None
            routing_result = await self.router.route(
                RoutingRequest(
                    query=query,
                    user_id=request.user,
                    metadata=request.metadata or {},
                ),
                decisions=decisions,
            )
            selected_model = routing_result.selected_model
            decision_name = routing_result.decision_name

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
            if request.chat_template_kwargs is not None:
                kwargs["chat_template_kwargs"] = request.chat_template_kwargs
            if request.tools is not None:
                kwargs["tools"] = request.tools
            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice

            messages = [msg.model_dump() for msg in request.messages]

            base_url = None
            if tenant:
                base_url = build_base_url(tenant.base_url_template, selected_model)

            # Get strategy and pool
            response = None
            if tenant:
                if strategy is None:
                    strategy = create_apikey_strategy(
                        tenant.apikey_pool_mode, self.apikey_selector
                    )
                pool = self._get_apikey_pool(tenant)

                # Unified key selection via strategy
                current_key = await strategy.select_key(pool, tenant.tenant_id)

                # Unified call with strategy-based retry
                while current_key:
                    try:
                        response = await self.client.chat_completion(
                            model=selected_model,
                            messages=messages,
                            base_url=base_url,
                            api_key=current_key,
                            **kwargs,
                        )
                        break  # Success
                    except Exception as e:
                        next_key = strategy.next_key_on_error(pool, current_key, e)
                        if next_key is None:
                            raise
                        current_key = next_key
            else:
                # No tenant - direct call
                response = await self.client.chat_completion(
                    model=selected_model,
                    messages=messages,
                    base_url=base_url,
                    api_key=None,
                    **kwargs,
                )

            # Record latency
            end_time = time.time()
            total_latency = end_time - start_time

            usage = None
            if response and "usage" in response:
                usage = ChatUsage(
                    prompt_tokens=response["usage"].get("prompt_tokens", 0),
                    completion_tokens=response["usage"].get("completion_tokens", 0),
                    total_tokens=response["usage"].get("total_tokens", 0),
                )

            await self.router.record_latency(
                model=selected_model,
                latency_seconds=total_latency,
            )

            # Build response
            choices = []
            if response:
                for choice in response.get("choices", []):
                    message = choice.get("message", {})
                    choices.append(
                        ChatChoice(
                            index=choice.get("index", 0),
                            message=ChatMessage(
                                role=message.get("role", "assistant"),
                                content=message.get("content"),
                                tool_calls=message.get("tool_calls"),
                            ),
                            finish_reason=choice.get("finish_reason"),
                        )
                    )

            logger.info(
                "chat_proxy_completed",
                model=selected_model,
                decision=decision_name,
                tenant_id=tenant.tenant_id if tenant else None,
                latency=total_latency,
                tokens=usage.completion_tokens if usage else None,
            )

            return ChatResponse(
                id=response.get("id", f"chatcmpl-{selected_model}") if response else f"chatcmpl-{selected_model}",
                model=selected_model,
                choices=choices,
                usage=usage,
            )

        except Exception as e:
            logger.error(
                "chat_proxy_error",
                model=selected_model,
                tenant_id=tenant.tenant_id if tenant else None,
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
        Handles both string content and array content format.
        """
        for msg in reversed(messages):
            if msg.role == "user":
                return self._content_to_str(msg.content)

        # Fallback: join all message content
        return " ".join(self._content_to_str(msg.content) for msg in messages if msg.content)

    def _content_to_str(self, content: str | list[dict[str, Any]]) -> str:
        """Convert content to string for routing.

        Supports text and image_url content types per OpenAI API format.

        Args:
            content: Either a string or array of content blocks.

        Returns:
            String representation of content.
        """
        if isinstance(content, str):
            return content

        text_parts = []
        has_image = False
        for block in content:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "image_url":
                has_image = True

        if has_image:
            text_parts.append("[图片]")

        return " ".join(text_parts)