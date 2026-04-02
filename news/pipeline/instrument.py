"""Pipeline instrumentation: structured logging and Prometheus metrics."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any

import structlog
from prometheus_client import Counter, Histogram

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

ARTICLES_TOTAL = Counter(
    "scraper_articles_total",
    "Total articles processed by the scraper",
    ["source", "outcome"],
)

STAGE_DURATION = Histogram(
    "scraper_stage_duration_seconds",
    "Duration of each pipeline stage in seconds",
    ["source", "stage"],
)

STAGE_ERRORS = Counter(
    "scraper_stage_errors_total",
    "Total errors per pipeline stage",
    ["source", "stage", "error_type"],
)

RUN_DURATION = Histogram(
    "scraper_run_duration_seconds",
    "Duration of a full pipeline run in seconds",
    ["source"],
)


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
    source = extra.get("source", "unknown")
    start = time.monotonic()
    try:
        yield ctx
        duration = time.monotonic() - start
        duration_ms = round(duration * 1000, 1)
        bound.info("stage.completed", duration_ms=duration_ms, **ctx)
        STAGE_DURATION.labels(source=source, stage=stage).observe(duration)
    except Exception as exc:
        duration = time.monotonic() - start
        duration_ms = round(duration * 1000, 1)
        error_type = type(exc).__name__
        bound.error(
            "stage.failed",
            duration_ms=duration_ms,
            error=str(exc),
            error_type=error_type,
            **ctx,
        )
        STAGE_ERRORS.labels(
            source=source, stage=stage, error_type=error_type
        ).inc()
        raise
