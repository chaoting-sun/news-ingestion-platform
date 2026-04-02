import logging

from celery import shared_task

from news.scraper import run_scraper

logger = logging.getLogger(__name__)


@shared_task
def scrape_news_task():
    logger.info("Celery task: starting news scrape")
    summary = run_scraper()
    logger.info("Celery task: done — %s", summary)
    return summary
