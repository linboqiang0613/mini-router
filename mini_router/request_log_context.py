"""Request-scoped logging context helpers."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_REQUEST_LOG_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "request_log_context",
    default=None,
)


def bind_request_log_context(**fields: Any) -> Token:
    """Bind request-scoped logging fields for the current async context."""
    merged = get_request_log_context()
    merged.update({key: value for key, value in fields.items() if value is not None})
    return _REQUEST_LOG_CONTEXT.set(merged)


def reset_request_log_context(token: Token) -> None:
    """Reset request-scoped logging fields to the previous context."""
    _REQUEST_LOG_CONTEXT.reset(token)


def get_request_log_context() -> dict[str, Any]:
    """Return a shallow copy of the current request-scoped log context."""
    context = _REQUEST_LOG_CONTEXT.get()
    return dict(context) if context is not None else {}


def with_request_log_context(**fields: Any) -> dict[str, Any]:
    """Merge explicit log fields with the current request-scoped context."""
    merged = get_request_log_context()
    merged.update(fields)
    return merged
