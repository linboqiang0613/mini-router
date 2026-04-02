"""HTTP API server for mini-router."""

import argparse
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mini_router.config.config import RouterConfig
from mini_router.proxy import ChatProxy, ChatRequest
from mini_router.proxy.chat_proxy import AuthenticationError, TenantDisabledError
from mini_router.router.router import Router, RoutingRequest
from mini_router.tenant import (
    TenantConfig,
    TenantCreateRequest,
    TenantResponse,
    TenantUpdateRequest,
)
from mini_router.tenant.manager import TenantManager

logger = structlog.get_logger()


# === API Models ===


class RouteRequest(BaseModel):
    """Request model for routing."""

    query: str
    user_id: str | None = None
    metadata: dict[str, Any] | None = None


class RouteResponse(BaseModel):
    """Response model for routing."""

    selected_model: str | None
    decision_name: str | None
    matched_rules: list[str]
    confidence: float
    cache_hit: bool
    cache_response: str | None = None
    action: str
    reject_message: str | None = None
    complexity: str | None = None


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str
    version: str = "0.1.0"


class CacheSetRequest(BaseModel):
    """Request model for setting cache."""

    query: str
    response: str
    metadata: dict[str, Any] | None = None


class CacheSetResponse(BaseModel):
    """Response model for setting cache."""

    success: bool


class FeedbackRequest(BaseModel):
    """Request model for recording latency feedback."""

    model: str
    latency_seconds: float
    tpot: float | None = None  # Time Per Output Token
    ttft: float | None = None  # Time To First Token
    success: bool = True
    tokens_generated: int | None = None


class FeedbackResponse(BaseModel):
    """Response model for feedback."""

    status: str
    model: str


class LatencyStatsResponse(BaseModel):
    """Response model for latency statistics."""

    models: dict[str, dict[str, Any]]


# === Global State ===

_router: Router | None = None
_config: RouterConfig | None = None
_chat_proxy: ChatProxy | None = None
_tenant_manager: TenantManager | None = None


def get_router() -> Router:
    """Get or create the router instance."""
    global _router, _config
    if _router is None:
        if _config is None:
            _config = create_default_config()
        _router = Router(_config)
    return _router


def get_chat_proxy() -> ChatProxy:
    """Get or create the chat proxy instance."""
    global _chat_proxy, _router
    if _chat_proxy is None:
        router = get_router()
        _chat_proxy = ChatProxy(router, router.client)
    return _chat_proxy


def get_tenant_manager() -> TenantManager:
    """Get or create the tenant manager instance."""
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = TenantManager()
        _tenant_manager.load()
    return _tenant_manager


def create_default_config() -> RouterConfig:
    """Create default configuration."""
    from mini_router.config.config import (
        ClassifierConfig,
        ClassifierModelConfig,
        Decision,
        KeywordRule,
        ModelRef,
        Operator,
        RuleNode,
        RuleType,
        SignalsConfig,
    )

    return RouterConfig(
        models={
            "base_url": "http://localhost:8000/v1",
            "classifier": ClassifierConfig(
                intent=ClassifierModelConfig(model="intent-classifier", enabled=True),
                pii=ClassifierModelConfig(model="pii-classifier", enabled=True),
                security=ClassifierModelConfig(model="security-classifier", enabled=True),
                complexity=ClassifierModelConfig(model="complexity-classifier", enabled=True),
            ),
        },
        signals=SignalsConfig(
            keyword_rules=[
                KeywordRule(
                    name="code_related",
                    keywords=["code", "programming", "function", "debug", "error"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
                KeywordRule(
                    name="math_related",
                    keywords=["calculate", "math", "equation", "solve"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
            ],
        ),
        decisions=[
            Decision(
                name="route_to_code_model",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[
                    ModelRef(model="codellama-70b", weight=1.0),
                    ModelRef(model="deepseek-coder", weight=0.8),
                ],
            ),
            Decision(
                name="route_to_math_model",
                priority=5,
                rules=RuleNode(type=RuleType.KEYWORD, name="math_related"),
                model_refs=[
                    ModelRef(model="llama-3-math", weight=1.0),
                ],
            ),
        ],
        cache={"enabled": True, "similarity_threshold": 0.95},
    )


# === Lifespan ===


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    router = get_router()
    logger.info("router_initialized", decisions=len(router.config.decisions))
    yield
    # Shutdown
    logger.info("router_shutdown")


# === App ===

app = FastAPI(
    title="Mini-Router API",
    description="Python implementation of vLLM Semantic Router",
    version="0.1.0",
    lifespan=lifespan,
)


# === Routes ===


@app.get("/healthz", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="healthy")


@app.get("/readyz", response_model=HealthResponse)
async def ready() -> HealthResponse:
    """Readiness check endpoint."""
    router = get_router()
    if router is None:
        raise HTTPException(status_code=503, detail="Router not initialized")
    return HealthResponse(status="ready")


@app.post("/v1/route", response_model=RouteResponse)
async def route(request: RouteRequest) -> RouteResponse:
    """
    Route a query to the appropriate model.

    This is the main endpoint that processes queries and returns routing decisions.
    """
    router = get_router()

    routing_request = RoutingRequest(
        query=request.query,
        user_id=request.user_id,
        metadata=request.metadata or {},
    )

    result = await router.route(routing_request)

    return RouteResponse(
        selected_model=result.selected_model,
        decision_name=result.decision_name,
        matched_rules=result.matched_rules,
        confidence=result.confidence,
        cache_hit=result.cache_hit,
        cache_response=result.cache_response,
        action=result.action.value,
        reject_message=result.reject_message,
        complexity=result.signals.get_complexity_level() if result.signals else None,
    )


@app.post("/v1/cache", response_model=CacheSetResponse)
async def set_cache(request: CacheSetRequest) -> CacheSetResponse:
    """Manually set a cache entry."""
    router = get_router()
    await router.set_cache(request.query, request.response)
    return CacheSetResponse(success=True)


@app.delete("/v1/cache")
async def clear_cache() -> dict[str, str]:
    """Clear all cache entries."""
    router = get_router()
    router.clear_cache()
    return {"status": "cleared"}


@app.get("/v1/config")
async def get_config() -> dict[str, Any]:
    """Get current router configuration."""
    router = get_router()
    return router.config.model_dump()


@app.post("/v1/feedback", response_model=FeedbackResponse)
async def record_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Record latency feedback after receiving model response.

    This endpoint should be called after a model response is received to
    update the latency statistics for latency-aware model selection.

    Example:
        ```json
        {
            "model": "codellama-70b",
            "latency_seconds": 1.5,
            "tpot": 0.05,
            "ttft": 0.3,
            "success": true,
            "tokens_generated": 100
        }
        ```
    """
    router = get_router()

    await router.record_latency(
        model=request.model,
        latency_seconds=request.latency_seconds,
        tpot=request.tpot,
        ttft=request.ttft,
    )

    logger.info(
        "feedback_recorded",
        model=request.model,
        latency=request.latency_seconds,
        tpot=request.tpot,
        ttft=request.ttft,
    )

    return FeedbackResponse(status="recorded", model=request.model)


@app.get("/v1/latency", response_model=LatencyStatsResponse)
async def get_latency_stats() -> LatencyStatsResponse:
    """Get latency statistics for all models."""
    router = get_router()
    stats = await router.get_latency_stats()
    return LatencyStatsResponse(models=stats)


@app.get("/v1/latency/{model}")
async def get_model_latency_stats(model: str) -> dict[str, Any]:
    """Get latency statistics for a specific model."""
    router = get_router()
    stats = await router.get_model_latency_stats(model)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"No latency data for model: {model}")
    return stats


# === Tenant Management ===


@app.get("/v1/tenants", response_model=list[TenantResponse])
async def list_tenants() -> list[TenantResponse]:
    """List all tenants."""
    manager = get_tenant_manager()
    tenants = manager.list_all()
    return [TenantResponse.from_config(tenant) for tenant in tenants]


@app.get("/v1/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str) -> TenantResponse:
    """Get a single tenant by ID."""
    manager = get_tenant_manager()
    tenant = manager.get_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return TenantResponse.from_config(tenant)


@app.post("/v1/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(request: TenantCreateRequest) -> TenantResponse:
    """Create a new tenant."""
    manager = get_tenant_manager()
    try:
        tenant = TenantConfig(**request.model_dump())
        created = manager.create(tenant)
        return TenantResponse.from_config(created)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/v1/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: str, request: TenantUpdateRequest) -> TenantResponse:
    """Update a tenant (partial update)."""
    manager = get_tenant_manager()
    # Only include non-None fields in the update
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        # No updates provided, just return current tenant
        tenant = manager.get_by_id(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
        return TenantResponse.from_config(tenant)

    try:
        updated = manager.update(tenant_id, updates)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
        return TenantResponse.from_config(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/v1/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str) -> dict[str, str]:
    """Delete a tenant."""
    manager = get_tenant_manager()
    deleted = manager.delete(tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return {"status": "deleted"}


# === Chat Completions ===


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> Any:
    """
    OpenAI-compatible chat completions endpoint.

    If `stream=true`, returns SSE streaming response.
    If `stream=false`, returns complete JSON response.

    The model will be automatically selected by the router if not specified.

    Requires tenant authentication via Authorization header (Bearer token).
    """
    proxy = get_chat_proxy()
    manager = get_tenant_manager()

    # Extract and validate API key
    apikey = proxy.extract_apikey(authorization)
    if apikey is None:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    # Authenticate tenant
    try:
        tenant = proxy.authenticate_tenant(manager, apikey)
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TenantDisabledError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if request.stream:
        # Return SSE streaming response
        async def generate_sse() -> AsyncGenerator[str, None]:
            async for chunk in proxy.chat_stream(request, tenant=tenant):
                yield chunk.to_sse()
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )
    else:
        # Return complete JSON response
        return await proxy.chat(request, tenant=tenant)


# === Main ===


def main():
    """Main entry point for the server."""
    parser = argparse.ArgumentParser(description="Mini-Router HTTP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument("--config", default="config.yaml", help="Path to config file (YAML)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    # Load config before starting server
    global _config
    config_path = Path(args.config)
    if config_path.exists():
        _config = RouterConfig.from_yaml(config_path)
        logger.info("config_loaded", path=str(config_path), decisions=len(_config.decisions))
    else:
        logger.warning("config_not_found", path=str(config_path), using="default")

    logger.info("starting_server", host=args.host, port=args.port)

    # Pass app object directly (not string) to preserve global state
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
