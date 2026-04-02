import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from news.consumers import GROUP_NAME
from news.models import News

logger = logging.getLogger(__name__)


def notify(news_obj: News) -> None:
    """Push a WebSocket notification for a newly created article."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            GROUP_NAME,
            {
                "type": "new_article",
                "article": {
                    "id": news_obj.id,
                    "title": news_obj.title,
                    "author": news_obj.author,
                    "published_at": news_obj.published_at.isoformat(),
                    "hero_image_url": news_obj.hero_image_url,
                },
            },
        )
    except Exception:
        logger.exception("Failed to send WebSocket notification")
