from datetime import datetime

import requests
import structlog

from news.pipeline.types import ArticleData

logger = structlog.get_logger()

API_BASE = "https://webdata-api.tsna.com"
TOP_URL = f"{API_BASE}/front/news/top"
DETAIL_URL = f"{API_BASE}/front/news"
SITE_BASE = "https://tsna.com"
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 1.5
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

# Number of recent popular articles to fetch
TOP_NEWEST_COUNT = 10


class TSNASource:
    """Scrapes news from TSNA (體育新聞團隊) via their JSON API."""

    name = "tsna"
    request_delay = REQUEST_DELAY

    def discover(self) -> list[str]:
        """Fetch the 近期熱門 (recent popular) article URLs."""
        resp = requests.get(
            TOP_URL,
            params={"Newest": TOP_NEWEST_COUNT, "Random": 1},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("Code") != "1" or not data.get("Result"):
            logger.warning("discover.bad_response", code=data.get("Code"))
            return []

        urls = []
        for item in data["Result"].get("Newest", []):
            article_id = item.get("ID")
            if article_id:
                urls.append(f"{SITE_BASE}/article/{article_id}")

        logger.info("discover.complete", url_count=len(urls))
        return urls

    def fetch(self, url: str) -> str:
        """Fetch article detail JSON from the API (returns raw JSON string)."""
        article_id = url.rsplit("/", 1)[-1]
        resp = requests.get(
            DETAIL_URL,
            params={"ID": article_id},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text

    def parse(self, url: str, raw_html: str) -> ArticleData | None:
        """Parse article data from the TSNA API JSON response."""
        import json

        try:
            data = json.loads(raw_html)
        except json.JSONDecodeError:
            logger.warning("parse.invalid_json", url=url)
            return None

        if data.get("Code") != "1" or not data.get("Result"):
            logger.warning("parse.bad_response", url=url, code=data.get("Code"))
            return None

        body = data["Result"].get("Body", {})
        if not body:
            logger.warning("parse.no_body", url=url)
            return None

        title = body.get("Title", "")
        author = body.get("Author", "")
        content = body.get("Content", "")

        publish_time = body.get("PublishTime", "")
        if not publish_time:
            logger.warning("parse.no_publish_time", url=url)
            return None
        published_at = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))

        cover = body.get("Cover", {})
        hero_image_url = cover.get("Url", "") if isinstance(cover, dict) else ""
        hero_image_caption = cover.get("Title", "") if isinstance(cover, dict) else ""

        return ArticleData(
            title=title,
            author=author,
            published_at=published_at,
            source_name="TSNA",
            source_url=url,
            content=content,
            hero_image_url=hero_image_url,
            hero_image_caption=hero_image_caption,
        )
