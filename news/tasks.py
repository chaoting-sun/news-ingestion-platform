import logging

from celery import shared_task

from news.pipeline.runner import run_pipeline
from news.pipeline.sources import SOURCES

logger = logging.getLogger(__name__)


@shared_task
def scrape_news_task(source_name="udn"):
    source = SOURCES[source_name]()
    logger.info("Celery task: starting %s news scrape", source.name)
    result = run_pipeline(source)
    summary = result.as_dict()
    logger.info("Celery task: done — %s", summary)
    return summary
