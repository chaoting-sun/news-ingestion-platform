import dataclasses
import logging

from django.db import IntegrityError

from news.models import News
from news.pipeline.types import ArticleData

logger = logging.getLogger(__name__)


def persist(article: ArticleData) -> News | None:
    """Save an ArticleData to the database.

    Returns the created News object, or None if it was a duplicate.
    Raises on unexpected errors.
    """
    try:
        news_obj = News.objects.create(**dataclasses.asdict(article))
        logger.info("SAVED: %s", article.title)
        return news_obj
    except IntegrityError:
        logger.info("SKIP (race condition duplicate): %s", article.source_url)
        return None
