"""Request lifecycle logging helpers."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mini_router.algorithm.types import SelectionResult
from mini_router.signal_layer.types import SignalMatches

if TYPE_CHECKING:
    from mini_router.proxy.types import ChatUsage


def normalize_query_preview(query: str, limit: int = 20) -> tuple[str, int]:
    """Build a bounded query preview for lifecycle logs."""
    normalized = query.strip()
    return normalized[:limit], len(normalized)


def serialize_signals(signals: SignalMatches | None) -> dict[str, Any] | None:
    """Convert signal matches into log-friendly structured data."""
    if signals is None:
        return None

    return {
        "keyword_rules": signals.keyword_rules,
        "embedding_rules": signals.embedding_rules,
        "intent": signals.get_intent_label(),
        "pii": signals.pii.label if signals.pii else None,
        "security": signals.security.label if signals.security else None,
        "complexity": signals.get_complexity_level() if signals.complexity else None,
        "context_length": {
            "label": signals.context_length.label,
            "token_count": signals.get_context_length(),
        } if signals.context_length else None,
    }


def serialize_chat_usage(usage: ChatUsage | None) -> dict[str, int] | None:
    """Convert chat usage into a plain dict."""
    if usage is None:
        return None

    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def serialize_routing_result(result: Any | None) -> dict[str, Any] | None:
    """Convert routing result into log-friendly structured data."""
    if result is None:
        return None

    return {
        "selected_model": result.selected_model,
        "decision_name": result.decision_name,
        "matched_rules": result.matched_rules,
        "confidence": result.confidence,
        "cache_hit": result.cache_hit,
        "action": result.action.value,
        "reject_message": result.reject_message,
        "signals": serialize_signals(result.signals),
    }


def serialize_selection_result(result: SelectionResult | None) -> dict[str, Any] | None:
    """Convert model selection result into log-friendly structured data."""
    if result is None:
        return None

    return {
        "selected_model": result.selected_model,
        "confidence": result.confidence,
        "metadata": result.metadata or None,
    }


@dataclass
class RequestTrace:
    """Request-scoped lifecycle logging data."""

    path: str
    method: str
    tenant_id: str | None
    query: str
    stream: bool | None = None
    user: str | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    query_preview: str = field(init=False)
    query_length: int = field(init=False)
    routing_result: Any | None = None
    selection_result: SelectionResult | None = None
    candidate_models: list[str] = field(default_factory=list)
    filtered_candidate_models: list[str] = field(default_factory=list)
    selection_strategy: str | None = None
    latency_seconds: float | None = None
    ttft: float | None = None
    tpot: float | None = None
    chunk_count: int | None = None
    usage: ChatUsage | None = None
    metric_provenance: str | None = None
    attempt_count: int | None = None
    final_upstream_status: int | None = None
    status: str = "started"
    error_type: str | None = None
    error_message: str | None = None
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        self.query_preview, self.query_length = normalize_query_preview(self.query)

    def apply_routing_result(self, routing_result: Any) -> None:
        """Attach routing diagnostics to the trace."""
        self.routing_result = routing_result
        self.candidate_models = getattr(routing_result, "candidate_models", [])
        self.filtered_candidate_models = getattr(
            routing_result, "filtered_candidate_models", []
        )
        self.selection_strategy = getattr(routing_result, "selection_strategy", None)

        if getattr(routing_result, "selected_model", None):
            self.selection_result = SelectionResult(
                selected_model=routing_result.selected_model,
                confidence=routing_result.confidence,
                metadata=getattr(routing_result, "selection_metadata", {}),
                filtered_candidates=getattr(
                    routing_result, "filtered_candidate_models", []
                ),
            )

    def record_completion(
        self,
        *,
        status: str,
        finish_reason: str | None = None,
        latency_seconds: float | None = None,
        ttft: float | None = None,
        tpot: float | None = None,
        chunk_count: int | None = None,
        usage: ChatUsage | None = None,
        metric_provenance: str | None = None,
        attempt_count: int | None = None,
        final_upstream_status: int | None = None,
        error: Exception | None = None,
    ) -> None:
        """Attach completion data to the trace."""
        self.status = status
        self.finish_reason = finish_reason
        self.latency_seconds = latency_seconds
        self.ttft = ttft
        self.tpot = tpot
        self.chunk_count = chunk_count
        self.usage = usage
        self.metric_provenance = metric_provenance
        self.attempt_count = attempt_count
        self.final_upstream_status = final_upstream_status
        if error is not None:
            self.error_type = type(error).__name__
            self.error_message = str(error)

    def started_event(self) -> dict[str, Any]:
        """Build the request_started event payload."""
        return {
            "request_id": self.request_id,
            "path": self.path,
            "method": self.method,
            "tenant_id": self.tenant_id,
            "stream": self.stream,
            "user": self.user,
            "query_preview": self.query_preview,
            "query_length": self.query_length,
            "timestamp": self.started_at,
        }

    def finished_event(self) -> dict[str, Any]:
        """Build the request_finished event payload."""
        return {
            "request_id": self.request_id,
            "path": self.path,
            "method": self.method,
            "tenant_id": self.tenant_id,
            "stream": self.stream,
            "query_preview": self.query_preview,
            "query_length": self.query_length,
            "duration_ms": int((time.time() - self.started_at) * 1000),
            "status": self.status,
            "routing": serialize_routing_result(self.routing_result),
            "selection": {
                "strategy": self.selection_strategy,
                "candidate_models": self.candidate_models or None,
                "filtered_candidate_models": self.filtered_candidate_models or None,
                "result": serialize_selection_result(self.selection_result),
            },
            "stats": {
                "latency_seconds": self.latency_seconds,
                "ttft": self.ttft,
                "tpot": self.tpot,
                "chunk_count": self.chunk_count,
                "usage": serialize_chat_usage(self.usage),
                "metric_provenance": self.metric_provenance,
            },
            "result": {
                "finish_reason": self.finish_reason,
                "error_type": self.error_type,
                "error_message": self.error_message,
                "attempt_count": self.attempt_count,
                "final_upstream_status": self.final_upstream_status,
            },
        }
