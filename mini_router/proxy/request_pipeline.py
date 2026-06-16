"""Shared routing pipeline for routing-capable endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from mini_router.logging_utils import RequestTrace
from mini_router.proxy.types import ChatMessage, ChatRequest
from mini_router.router.router import Router, RoutingRequest, RoutingResult
from mini_router.tenant.types import TenantConfig

logger = structlog.get_logger()


class AuthenticationError(Exception):
    """Raised when API key is missing or invalid."""

    pass


class TenantDisabledError(Exception):
    """Raised when tenant is disabled."""

    pass


class RoutingPipelineError(Exception):
    """Raised when shared pipeline routing fails after request start."""

    def __init__(self, trace: RequestTrace, cause: Exception) -> None:
        super().__init__(str(cause))
        self.trace = trace
        self.cause = cause


@dataclass
class RoutingPipelineContext:
    """Shared routing context passed to endpoint adapters."""

    query: str
    routing_request: RoutingRequest
    routing_result: RoutingResult
    tenant: TenantConfig | None = None
    trace: RequestTrace | None = None


def extract_apikey(authorization: str | None) -> str | None:
    """Extract API key from Authorization header."""
    if not authorization:
        return None

    if not authorization.startswith("Bearer "):
        return None

    apikey = authorization[7:].strip()
    if not apikey:
        return None

    return apikey


def authenticate_tenant(tenant_manager: Any, apikey: str) -> TenantConfig:
    """Authenticate a tenant by API key."""
    tenant = tenant_manager.get_by_apikey(apikey)

    if tenant is None:
        raise AuthenticationError("Invalid API key: tenant not found")

    if not tenant.enabled:
        raise TenantDisabledError(f"Tenant '{tenant.tenant_id}' is disabled")

    return tenant


def content_to_str(content: str | list[dict[str, Any]] | None) -> str:
    """Convert message content to a string suitable for routing."""
    if content is None:
        return ""

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


def extract_query(messages: list[ChatMessage]) -> str:
    """Extract the routed query from chat messages."""
    for msg in reversed(messages):
        if msg.role == "user":
            return content_to_str(msg.content)

    return " ".join(content_to_str(msg.content) for msg in messages if msg.content)


async def build_routing_context(
    router: Router,
    *,
    query: str,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tenant: TenantConfig | None = None,
    trace: RequestTrace | None = None,
) -> RoutingPipelineContext:
    """Build shared routing state for any routing-capable request."""
    routing_request = RoutingRequest(
        query=query,
        user_id=user_id,
        metadata=metadata or {},
    )
    decisions = tenant.decisions if tenant else None
    selection = tenant.selection if tenant else None
    routing_result = await router.route(
        routing_request,
        decisions=decisions,
        selection=selection,
    )

    if trace is not None:
        trace.apply_routing_result(routing_result)

    return RoutingPipelineContext(
        query=query,
        routing_request=routing_request,
        routing_result=routing_result,
        tenant=tenant,
        trace=trace,
    )


async def build_authenticated_routing_context(
    router: Router,
    tenant_manager: Any,
    authorization: str | None,
    *,
    event_logger: Any = logger,
    path: str,
    query: str,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    stream: bool | None = None,
) -> RoutingPipelineContext:
    """Authenticate a tenant and execute the shared routing pipeline."""
    apikey = extract_apikey(authorization)
    if apikey is None:
        raise AuthenticationError("Missing or invalid Authorization header")

    tenant = authenticate_tenant(tenant_manager, apikey)
    trace = RequestTrace(
        path=path,
        method="POST",
        tenant_id=tenant.tenant_id,
        query=query,
        stream=stream,
        user=user_id,
    )
    event_logger.info("request_started", **trace.started_event())

    try:
        return await build_routing_context(
            router,
            query=query,
            user_id=user_id,
            metadata=metadata,
            tenant=tenant,
            trace=trace,
        )
    except Exception as exc:
        raise RoutingPipelineError(trace, exc) from exc


async def build_authenticated_chat_context(
    router: Router,
    tenant_manager: Any,
    authorization: str | None,
    request: ChatRequest,
    *,
    event_logger: Any = logger,
    path: str = "/v1/chat/completions",
    stream: bool | None = None,
) -> RoutingPipelineContext:
    """Authenticate and route a chat request through the shared pipeline."""
    query = extract_query(request.messages)
    return await build_authenticated_routing_context(
        router,
        tenant_manager,
        authorization,
        event_logger=event_logger,
        path=path,
        query=query,
        user_id=request.user,
        metadata=request.metadata,
        stream=request.stream if stream is None else stream,
    )
