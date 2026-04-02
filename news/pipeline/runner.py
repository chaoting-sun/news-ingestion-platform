import logging
import time

from django.core.cache import cache

from news.models import News
from news.pipeline.base import NewsSource
from news.pipeline.notify import notify
from news.pipeline.persist import persist
from news.pipeline.types import PipelineResult

logger = logging.getLogger(__name__)


def run_pipeline(source: NewsSource) -> PipelineResult:
    """Run the full scraping pipeline for a given news source.

    Stages: discover → fetch → parse → persist → notify
    """
    result = PipelineResult()

    urls = source.discover()
    if not urls:
        logger.warning("[%s] No article URLs found, nothing to scrape", source.name)
        return result

    delay = getattr(source, "request_delay", 0)

    for url in urls:
        if News.objects.filter(source_url=url).exists():
            logger.info("[%s] SKIP (duplicate): %s", source.name, url)
            result.skipped += 1
            continue

        try:
            raw_html = source.fetch(url)
        except Exception:
            logger.exception("[%s] FAILED to fetch %s", source.name, url)
            result.failed += 1
            if delay:
                time.sleep(delay)
            continue

        try:
            article = source.parse(url, raw_html)
        except Exception:
            logger.exception("[%s] FAILED to parse %s", source.name, url)
            result.failed += 1
            if delay:
                time.sleep(delay)
            continue

        if article is None:
            result.failed += 1
            if delay:
                time.sleep(delay)
            continue

        try:
            news_obj = persist(article)
            if news_obj is None:
                result.skipped += 1
            else:
                result.created += 1
                notify(news_obj)
        except Exception:
            logger.exception("[%s] FAILED to persist %s", source.name, url)
            result.failed += 1

        if delay:
            time.sleep(delay)

    if result.created > 0:
        cache.clear()
        logger.info(
            "[%s] Cache cleared after creating %d new articles",
            source.name,
            result.created,
        )

    logger.info(
        "[%s] Scraping complete: %d created, %d skipped, %d failed",
        source.name,
        result.created,
        result.skipped,
        result.failed,
    )
    return result
