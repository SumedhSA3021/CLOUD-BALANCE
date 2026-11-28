"""Structured JSON logging with correlation ID propagation."""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the current correlation ID, generating one if unset."""
    cid = correlation_id_ctx.get()
    if not cid:
        cid = uuid.uuid4().hex[:12]
        correlation_id_ctx.set(cid)
    return cid


def set_correlation_id(cid: str | None = None) -> str:
    """Set a specific correlation ID or generate a new one."""
    resolved = cid if cid else uuid.uuid4().hex[:12]
    correlation_id_ctx.set(resolved)
    return resolved


def inject_correlation_id(
    _logger: object, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Structlog processor to inject correlation_id into every log entry."""
    cid = correlation_id_ctx.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(json_logs: bool = True, level: int = logging.INFO) -> None:
    """Configure structlog for structured JSON output."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            inject_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "cloudbalance") -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound with component name."""
    return structlog.get_logger(component=name)  # type: ignore[no-any-return]

