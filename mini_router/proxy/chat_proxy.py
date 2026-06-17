"""Chat proxy service - routes and forwards chat requests."""

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import structlog

from mini_router.logging_utils import RequestTrace
from mini_router.proxy.apikey_selector import ApiKeyPoolSelector
from mini_router.proxy.request_pipeline import (
    AuthenticationError,
    TenantDisabledError,
    authenticate_tenant,
    build_routing_context,
    content_to_str,
    extract_apikey,
    extract_query,
)
from mini_router.proxy.strategies import (
    DEFAULT_RETRYABLE_STATUS_CODES,
    ApiKeyStrategy,
    create_apikey_strategy,
)
from mini_router.proxy.types import (
    ChatChoice,
    ChatMessage,
    ChatUsage,
    PreparedChatStreamResponse,
    ChatRequest,
    ChatResponse,
)
from mini_router.request_log_context import with_request_log_context
from mini_router.router.router import Router
from mini_router.client.openai_client import OpenAIClient
from mini_router.tenant.types import TenantConfig, build_base_url

logger = structlog.get_logger()
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


class _TransparentStreamObserver:
    """Best-effort observer for transparently forwarded SSE traffic."""

    def __init__(self) -> None:
        self.first_token_time: float | None = None
        self.chunk_count = 0
        self.finish_reason: str | None = None
        self.usage: ChatUsage | None = None
        self.metric_provenance = "unavailable"
        self._buffer = b""

    def observe(self, chunk: bytes) -> None:
        """Inspect streamed bytes without mutating them."""
        try:
            self._buffer += chunk
            while True:
                separator = self._find_event_separator(self._buffer)
                if separator is None:
                    return
                event, self._buffer = self._buffer[:separator], self._buffer[separator:]
                self._buffer = self._trim_separator_prefix(self._buffer)
                self._process_event(event)
        except Exception:
            # Observer failures must never affect passthrough behavior.
            return

    @staticmethod
    def _find_event_separator(buffer: bytes) -> int | None:
        for marker in (b"\r\n\r\n", b"\n\n"):
            index = buffer.find(marker)
            if index != -1:
                return index
        return None

    @staticmethod
    def _trim_separator_prefix(buffer: bytes) -> bytes:
        if buffer.startswith(b"\r\n\r\n"):
            return buffer[4:]
        if buffer.startswith(b"\n\n"):
            return buffer[2:]
        return buffer

    def _process_event(self, event: bytes) -> None:
        text = event.decode("utf-8", errors="ignore")
        data_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if not data_lines:
            return

        data = "\n".join(data_lines)
        if data == "[DONE]":
            self.finish_reason = self.finish_reason or "stream_completed"
            return

        payload = json.loads(data)
        usage = payload.get("usage")
        if usage:
            self.usage = ChatUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )
            self.metric_provenance = "exact"

        for choice in payload.get("choices", []):
            delta = choice.get("delta") or {}
            content = delta.get("content")
            tool_calls = delta.get("tool_calls")
            if (content or tool_calls) and self.first_token_time is None:
                self.first_token_time = time.time()
            if content or tool_calls:
                self.chunk_count += 1
            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]


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
        return extract_apikey(authorization)

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
        return authenticate_tenant(tenant_manager, apikey)

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

    def _build_chat_kwargs(self, request: ChatRequest) -> dict[str, Any]:
        """Build shared chat completion kwargs from a chat request."""
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
        return kwargs

    @staticmethod
    def _split_response_headers(headers: httpx.Headers) -> tuple[str | None, dict[str, str]]:
        """Split upstream headers into media_type and forwardable headers."""
        media_type = headers.get("content-type")
        forward_headers: dict[str, str] = {}
        for key, value in headers.items():
            if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == "content-type":
                continue
            forward_headers[key] = value
        return media_type, forward_headers

    @staticmethod
    def _build_status_error(response: httpx.Response) -> httpx.HTTPStatusError:
        """Wrap a raw response as an HTTPStatusError for retry strategy checks."""
        return httpx.HTTPStatusError(
            message=f"{response.status_code} upstream response",
            request=response.request,
            response=response,
        )

    @staticmethod
    def _routing_error_body(message: str) -> bytes:
        """Serialize a router-generated pre-stream error body."""
        return json.dumps(
            {
                "error": {
                    "type": "routing_error",
                    "message": message,
                    "code": "no_model_selected",
                }
            }
        ).encode("utf-8")

    async def _record_stream_latency(
        self,
        start_time: float,
        first_token_time: float | None,
        chunk_count: int,
        model: str,
        tenant_id: str | None,
        decision_name: str | None,
    ) -> tuple[float, float | None, float | None]:
        """Record streaming latency metrics.

        Args:
            start_time: Request start time
            first_token_time: First token arrival time
            chunk_count: Number of streamed content chunks generated
            model: Model name
            tenant_id: Tenant ID (for logging)
            decision_name: Decision name (for logging)
        """
        end_time = time.time()
        total_latency = end_time - start_time
        ttft = first_token_time - start_time if first_token_time else None
        tpot = None
        if chunk_count > 0 and first_token_time:
            tpot = (end_time - first_token_time) / chunk_count

        await self.router.record_latency(
            model=model,
            latency_seconds=total_latency,
            tpot=tpot,
            ttft=ttft,
        )

        logger.info(
            "chat_proxy_stream_completed",
            **with_request_log_context(
                model=model,
                decision=decision_name,
                tenant_id=tenant_id,
                latency=total_latency,
                ttft=ttft,
                tpot=tpot,
                chunk_count=chunk_count,
            ),
        )
        return total_latency, ttft, tpot

    async def chat_stream(
        self,
        request: ChatRequest,
        tenant: TenantConfig | None = None,
        strategy: ApiKeyStrategy | None = None,
        trace: RequestTrace | None = None,
    ) -> PreparedChatStreamResponse:
        """Prepare a transparent streaming chat response.

        Args:
            request: The chat request to process
            tenant: Optional tenant configuration for tenant-specific routing
            strategy: Optional API key selection strategy. If None, uses tenant config.

        Returns a prepared response containing either a raw upstream stream
        or a pre-stream error body.
        """
        if request.model:
            logger.info(
                "requested_model_ignored",
                **with_request_log_context(
                    requested_model=request.model,
                    tenant_id=tenant.tenant_id if tenant else None,
                ),
            )

        _query, routing_result = await self._resolve_routing_state(
            request,
            tenant=tenant,
            trace=trace,
        )
        selected_model = routing_result.selected_model
        decision_name = routing_result.decision_name

        if not selected_model:
            if trace is not None:
                trace.record_completion(
                    status="error",
                    finish_reason="no_model_selected",
                    final_upstream_status=503,
                )
                logger.info("request_finished", **trace.finished_event())
            return PreparedChatStreamResponse(
                status_code=503,
                media_type="application/json",
                body=self._routing_error_body("No model selected for routing."),
                headers={"Cache-Control": "no-cache"},
            )

        start_time = time.time()
        kwargs = self._build_chat_kwargs(request)
        messages = [msg.model_dump() for msg in request.messages]
        base_url = build_base_url(tenant.base_url_template, selected_model) if tenant else None
        retryable_status_codes = list(DEFAULT_RETRYABLE_STATUS_CODES)

        try:
            current_key: str | None = None
            last_attempt_key: str | None = None
            pool: list[str] = []
            if tenant:
                if strategy is None:
                    strategy = create_apikey_strategy(
                        tenant.apikey_pool_mode,
                        self.apikey_selector,
                        retryable_status_codes=retryable_status_codes,
                    )
                pool = self._get_apikey_pool(tenant)
                current_key = await strategy.select_key(pool, tenant.tenant_id)

            attempt_count = 0
            while True:
                attempt_count += 1
                last_attempt_key = current_key
                raw_response = await self.client.open_chat_completion_stream(
                    model=selected_model,
                    messages=messages,
                    base_url=base_url,
                    api_key=current_key,
                    **kwargs,
                )
                status_code = raw_response.status_code

                if status_code < 200 or status_code >= 300:
                    status_error = self._build_status_error(raw_response.response)
                    next_key = (
                        strategy.next_key_on_error(pool, current_key or "", status_error)
                        if strategy is not None
                        else None
                    )
                    if next_key is not None:
                        await raw_response.aclose()
                        current_key = next_key
                        continue

                    body = await raw_response.aread_raw()
                    await raw_response.aclose()
                    media_type, headers = self._split_response_headers(raw_response.headers)
                    if trace is not None:
                        trace.record_completion(
                            status="error",
                            finish_reason="stream_error",
                            attempt_count=attempt_count,
                            final_upstream_status=status_code,
                            final_upstream_api_key=last_attempt_key,
                        )
                        logger.info("request_finished", **trace.finished_event())
                    return PreparedChatStreamResponse(
                        status_code=status_code,
                        headers=headers,
                        media_type=media_type,
                        body=body,
                    )

                media_type, headers = self._split_response_headers(raw_response.headers)

                async def forward_stream() -> AsyncGenerator[bytes, None]:
                    observer = _TransparentStreamObserver()
                    try:
                        async for chunk in raw_response.aiter_raw():
                            observer.observe(chunk)
                            yield chunk

                        total_latency, ttft, tpot = await self._record_stream_latency(
                            start_time,
                            observer.first_token_time,
                            observer.chunk_count,
                            selected_model,
                            tenant.tenant_id if tenant else None,
                            decision_name,
                        )
                        if trace is not None:
                            trace.record_completion(
                                status="completed",
                                finish_reason=observer.finish_reason or "stream_completed",
                                latency_seconds=total_latency,
                                ttft=ttft,
                                tpot=tpot,
                                chunk_count=observer.chunk_count,
                                usage=observer.usage,
                                metric_provenance=observer.metric_provenance,
                                attempt_count=attempt_count,
                                final_upstream_status=status_code,
                                final_upstream_api_key=last_attempt_key,
                            )
                            logger.info("request_finished", **trace.finished_event())
                    except Exception as e:
                        logger.error(
                            "chat_proxy_stream_error",
                            **with_request_log_context(
                                model=selected_model,
                                tenant_id=tenant.tenant_id if tenant else None,
                                error=str(e),
                                error_type=type(e).__name__,
                            ),
                        )
                        if trace is not None:
                            trace.record_completion(
                                status="error",
                                finish_reason="stream_error",
                                chunk_count=observer.chunk_count,
                                usage=observer.usage,
                                metric_provenance=observer.metric_provenance,
                                attempt_count=attempt_count,
                                final_upstream_status=status_code,
                                final_upstream_api_key=last_attempt_key,
                                error=e,
                            )
                            logger.info("request_finished", **trace.finished_event())
                        raise
                    finally:
                        await raw_response.aclose()

                return PreparedChatStreamResponse(
                    status_code=status_code,
                    headers=headers,
                    media_type=media_type,
                    stream=forward_stream(),
                )

        except Exception as e:
            logger.error(
                "chat_proxy_stream_error",
                **with_request_log_context(
                    model=selected_model,
                    tenant_id=tenant.tenant_id if tenant else None,
                    error=str(e),
                    error_type=type(e).__name__,
                ),
            )
            if trace is not None:
                trace.record_completion(
                    status="error",
                    finish_reason="stream_error",
                    final_upstream_api_key=last_attempt_key,
                    error=e,
                )
                logger.info("request_finished", **trace.finished_event())
            raise

    async def chat(
        self,
        request: ChatRequest,
        tenant: TenantConfig | None = None,
        strategy: ApiKeyStrategy | None = None,
        trace: RequestTrace | None = None,
    ) -> ChatResponse:
        """Process a non-streaming chat request.

        Args:
            request: The chat request to process
            tenant: Optional tenant configuration for tenant-specific routing
            strategy: Optional API key selection strategy. If None, uses tenant config.

        Returns a complete ChatResponse.
        """
        if request.model:
            logger.info(
                "requested_model_ignored",
                **with_request_log_context(
                    requested_model=request.model,
                    tenant_id=tenant.tenant_id if tenant else None,
                ),
            )

        _query, routing_result = await self._resolve_routing_state(
            request,
            tenant=tenant,
            trace=trace,
        )
        selected_model = routing_result.selected_model
        decision_name = routing_result.decision_name

        if not selected_model:
            if trace is not None:
                trace.record_completion(
                    status="error",
                    finish_reason="no_model_selected",
                )
                logger.info("request_finished", **trace.finished_event())
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
        last_attempt_key: str | None = None

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
                        tenant.apikey_pool_mode,
                        self.apikey_selector,
                        retryable_status_codes=list(DEFAULT_RETRYABLE_STATUS_CODES),
                    )
                pool = self._get_apikey_pool(tenant)

                # Unified key selection via strategy
                current_key = await strategy.select_key(pool, tenant.tenant_id)

                # Unified call with strategy-based retry
                while current_key:
                    try:
                        last_attempt_key = current_key
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
                **with_request_log_context(
                    model=selected_model,
                    decision=decision_name,
                    tenant_id=tenant.tenant_id if tenant else None,
                    latency=total_latency,
                    tokens=usage.completion_tokens if usage else None,
                ),
            )
            if trace is not None:
                trace.record_completion(
                    status="completed",
                    finish_reason="chat_completed",
                    latency_seconds=total_latency,
                    usage=usage,
                    final_upstream_api_key=last_attempt_key,
                )
                logger.info("request_finished", **trace.finished_event())

            return ChatResponse(
                id=response.get("id", f"chatcmpl-{selected_model}") if response else f"chatcmpl-{selected_model}",
                model=selected_model,
                choices=choices,
                usage=usage,
            )

        except Exception as e:
            logger.error(
                "chat_proxy_error",
                **with_request_log_context(
                    model=selected_model,
                    tenant_id=tenant.tenant_id if tenant else None,
                    error=str(e),
                    error_type=type(e).__name__,
                ),
            )
            if trace is not None:
                trace.record_completion(
                    status="error",
                    finish_reason="chat_error",
                    final_upstream_api_key=last_attempt_key,
                    error=e,
                )
                logger.info("request_finished", **trace.finished_event())
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
        return extract_query(messages)

    def _content_to_str(self, content: str | list[dict[str, Any]] | None) -> str:
        """Convert content to string for routing.

        Supports text and image_url content types per OpenAI API format.

        Args:
            content: Either a string or array of content blocks.

        Returns:
            String representation of content.
        """
        return content_to_str(content)

    async def _resolve_routing_state(
        self,
        request: ChatRequest,
        *,
        tenant: TenantConfig | None = None,
        trace: RequestTrace | None = None,
    ) -> tuple[str, Any]:
        """Resolve routing once, reusing a pre-populated trace when available."""
        if trace is not None and trace.routing_result is not None:
            return trace.query, trace.routing_result

        context = await build_routing_context(
            self.router,
            query=self._extract_query(request.messages),
            user_id=request.user,
            metadata=request.metadata,
            tenant=tenant,
            trace=trace,
        )
        return context.query, context.routing_result
