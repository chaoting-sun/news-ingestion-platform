import dataclasses

import structlog
from django.db import IntegrityError

from news.models import News
from news.pipeline.types import ArticleData

logger = structlog.get_logger()


def persist(article: ArticleData) -> News | None:
    """Save an ArticleData to the database.

    Returns the created News object, or None if it was a duplicate.
    Raises on unexpected errors.
    """
    try:
        news_obj = News.objects.create(**dataclasses.asdict(article))
        logger.info("persist.saved", title=article.title, url=article.source_url)
        return news_obj
    except IntegrityError:
        logger.info(
            "persist.duplicate", url=article.source_url, reason="race_condition"
        )
        return None
