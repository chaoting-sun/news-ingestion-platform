import structlog
from celery import shared_task

from news.pipeline.runner import run_pipeline
from news.pipeline.sources import SOURCES

logger = structlog.get_logger()


@shared_task
def scrape_news_task(source_name="udn"):
    source = SOURCES[source_name]()
    logger.info("celery.scrape_started", source=source.name)
    result = run_pipeline(source)
    summary = result.as_dict()
    logger.info("celery.scrape_finished", source=source.name, **summary)
    return summary
