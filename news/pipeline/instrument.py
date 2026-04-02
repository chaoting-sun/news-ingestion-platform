"""Pipeline instrumentation: structured logging with stage-level timing."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any

import structlog

logger = structlog.get_logger()


def new_run_id() -> str:
    """Generate a unique ID for correlating all logs within one pipeline run."""
    return uuid.uuid4().hex[:12]


@contextmanager
def log_stage(stage: str, **extra: Any):
    """Context manager that wraps a pipeline stage with timing and error capture.

    Yields a mutable dict that callers can populate with stage-specific fields.
    Those fields are included in the completion or error log entry.

    Usage::

        with log_stage("fetch", source="udn", url=url) as ctx:
            html = source.fetch(url)
            ctx["status_code"] = 200
            ctx["content_length"] = len(html)
    """
    ctx: dict[str, Any] = {}
    bound = logger.bind(stage=stage, **extra)
    start = time.monotonic()
    try:
        yield ctx
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        bound.info("stage.completed", duration_ms=duration_ms, **ctx)
    except Exception as exc:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        bound.error(
            "stage.failed",
            duration_ms=duration_ms,
            error=str(exc),
            error_type=type(exc).__name__,
            **ctx,
        )
        raise
