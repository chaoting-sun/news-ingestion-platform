import time

import structlog
from django.core.cache import cache

from news.models import News
from news.pipeline.base import NewsSource
from news.pipeline.instrument import (
    ARTICLES_TOTAL,
    RUN_DURATION,
    log_stage,
    new_run_id,
)
from news.pipeline.notify import notify
from news.pipeline.persist import persist
from news.pipeline.types import PipelineResult

logger = structlog.get_logger()


def run_pipeline(source: NewsSource) -> PipelineResult:
    """Run the full scraping pipeline for a given news source.

    Stages: discover -> fetch -> parse -> persist -> notify
    """
    run_id = new_run_id()
    structlog.contextvars.bind_contextvars(run_id=run_id, source=source.name)
    logger.info("pipeline.started")

    result = PipelineResult()
    run_start = time.monotonic()
    input_count = 0
    run_error = None

    try:
        with log_stage("discover", source=source.name) as ctx:
            urls = source.discover()
            ctx["url_count"] = len(urls)
            ARTICLES_TOTAL.labels(source=source.name, outcome="discover").inc(
                len(urls)
            )

        input_count = len(urls)

        if not urls:
            logger.warning("pipeline.empty", msg="No article URLs found")
            return result

        delay = getattr(source, "request_delay", 0)

        for url in urls:
            if News.objects.filter(source_url=url).exists():
                logger.info("pipeline.skip", url=url, reason="duplicate")
                result.skipped += 1
                ARTICLES_TOTAL.labels(source=source.name, outcome="skip").inc()
                continue

            # --- fetch ---
            try:
                with log_stage("fetch", source=source.name, url=url) as ctx:
                    raw_html = source.fetch(url)
                    ctx["status_code"] = 200
                    ctx["content_length"] = len(raw_html)
            except Exception:
                result.failed += 1
                ARTICLES_TOTAL.labels(source=source.name, outcome="fail").inc()
                if delay:
                    time.sleep(delay)
                continue

            # --- parse ---
            try:
                with log_stage("parse", source=source.name, url=url) as ctx:
                    article = source.parse(url, raw_html)
                    if article is not None:
                        extracted = [
                            f for f in ("title", "author", "content", "hero_image_url")
                            if getattr(article, f, "")
                        ]
                        missing = [
                            f for f in ("title", "author", "content", "hero_image_url")
                            if not getattr(article, f, "")
                        ]
                        ctx["fields_extracted"] = extracted
                        ctx["missing_fields"] = missing
                    else:
                        ctx["fields_extracted"] = []
                        ctx["missing_fields"] = ["all"]
            except Exception:
                result.failed += 1
                ARTICLES_TOTAL.labels(source=source.name, outcome="fail").inc()
                if delay:
                    time.sleep(delay)
                continue

            if article is None:
                logger.warning("parse.returned_none", url=url)
                result.failed += 1
                ARTICLES_TOTAL.labels(source=source.name, outcome="fail").inc()
                if delay:
                    time.sleep(delay)
                continue

            # --- persist ---
            try:
                with log_stage("persist", source=source.name, url=url) as ctx:
                    news_obj = persist(article)
                    if news_obj is None:
                        ctx["outcome"] = "skipped"
                        result.skipped += 1
                        ARTICLES_TOTAL.labels(
                            source=source.name, outcome="skip"
                        ).inc()
                    else:
                        ctx["outcome"] = "created"
                        result.created += 1
                        ARTICLES_TOTAL.labels(
                            source=source.name, outcome="create"
                        ).inc()
            except Exception:
                result.failed += 1
                ARTICLES_TOTAL.labels(source=source.name, outcome="fail").inc()
                if delay:
                    time.sleep(delay)
                continue

            # --- notify ---
            if news_obj is not None:
                with log_stage("notify", source=source.name, article_id=news_obj.id) as ctx:
                    notify(news_obj)
                    ctx["delivered"] = True

            if delay:
                time.sleep(delay)

        if result.created > 0:
            cache.clear()
            logger.info(
                "pipeline.cache_cleared", articles_created=result.created
            )

    except Exception as exc:
        run_error = exc
        raise
    finally:
        duration = time.monotonic() - run_start
        RUN_DURATION.labels(source=source.name).observe(duration)

        if run_error is not None:
            completion_status = "error"
        elif result.failed > 0:
            completion_status = "partial"
        else:
            completion_status = "success"

        logger.info(
            "pipeline.finished",
            completion_status=completion_status,
            duration=round(duration, 3),
            input_count=input_count,
            created=result.created,
            skipped=result.skipped,
            failed=result.failed,
        )

        structlog.contextvars.unbind_contextvars("run_id", "source")

    return result
