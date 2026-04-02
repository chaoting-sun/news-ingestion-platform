import json
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlparse, urlunparse

import requests
from asgiref.sync import async_to_sync
from bs4 import BeautifulSoup
from channels.layers import get_channel_layer
from django.db import IntegrityError

from django.core.cache import cache

from .consumers import GROUP_NAME
from .models import News

logger = logging.getLogger(__name__)

INDEX_URL = "http://tw-nba.udn.com/nba/index"
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 1.5
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}


def _clean_url(url: str) -> str:
    """Strip tracking query params to get a canonical article URL."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _fetch(url: str) -> str:
    """Fetch a URL and return the response text. Raises on HTTP errors."""
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def scrape_index() -> list[str]:
    """Fetch the index page and return a list of canonical article URLs
    from the 焦點新聞 carousel."""
    html = _fetch(INDEX_URL)
    soup = BeautifulSoup(html, "lxml")

    focus = soup.select_one("#focus")
    if not focus:
        logger.warning("Could not find #focus element on index page")
        return []

    links = focus.select(".splide__list .splide__slide a[href]")
    urls = []
    for a_tag in links:
        raw_url = a_tag.get("href", "")
        if "/nba/story/" not in raw_url:
            continue
        urls.append(_clean_url(raw_url))

    logger.info("Found %d carousel articles on index page", len(urls))
    return urls


def _extract_json_ld(soup: BeautifulSoup) -> dict | None:
    """Extract the first NewsArticle JSON-LD block from the page."""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "NewsArticle":
            return data
    return None


def sanitize_content(body_span) -> str:
    """Remove ads, widgets, scripts from the article body and return
    sanitized HTML."""
    unwanted_selectors = [
        "div.only_web",
        "div.only_mobile",
        "div.inline-ad",
        "a.player_card_link",
        "a.liveupdates__container_link",
        "script",
        "style",
        "link",
    ]
    for selector in unwanted_selectors:
        for el in body_span.select(selector):
            el.decompose()

    html = body_span.decode_contents()
    html = re.sub(r"<!--\d+-->", "", html)
    html = re.sub(r"<p>\s*</p>", "", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def scrape_article(url: str) -> dict | None:
    """Fetch an article page and extract all fields. Returns a dict
    suitable for creating a News object, or None on failure."""
    html = _fetch(url)
    soup = BeautifulSoup(html, "lxml")

    json_ld = _extract_json_ld(soup)
    if not json_ld:
        logger.warning("No JSON-LD NewsArticle found for %s", url)
        return None

    title = json_ld.get("headline", "")

    author_meta = soup.select_one('meta[property="dable:author"]')
    author = author_meta["content"] if author_meta else ""

    pubdate_meta = soup.select_one('meta[name="pubdate"]')
    if not pubdate_meta:
        logger.warning("No pubdate meta found for %s", url)
        return None
    published_at = datetime.fromisoformat(pubdate_meta["content"])

    source_name = ""
    author_div = soup.select_one(".shareBar__info--author")
    if author_div:
        text = author_div.get_text(strip=True)
        date_span = author_div.select_one("span")
        if date_span:
            text = text.replace(date_span.get_text(), "", 1).strip()
        if "/" in text:
            source_name = text.split("/")[0].strip()
        else:
            source_name = text.strip()
    if not source_name:
        source_name = "udn NBA"

    image_data = json_ld.get("image", {})
    hero_image_url = ""
    hero_image_caption = ""
    if isinstance(image_data, dict):
        hero_image_url = image_data.get("url", image_data.get("contentUrl", ""))
        hero_image_caption = image_data.get("name", "")

    body_span = soup.select_one("#story_body_content > span")
    content = ""
    if body_span:
        content = sanitize_content(body_span)
    else:
        logger.warning("No article body found for %s", url)

    return {
        "title": title,
        "author": author,
        "published_at": published_at,
        "source_name": source_name,
        "source_url": url,
        "content": content,
        "hero_image_url": hero_image_url,
        "hero_image_caption": hero_image_caption,
    }


def _notify_new_article(news_obj: News) -> None:
    """Push a WebSocket notification to the news_updates group."""
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


def run_scraper() -> dict:
    """Main entry point. Scrapes the index carousel, fetches each article,
    and saves new ones to the database.

    Returns a summary dict with counts of created, skipped, and failed articles.
    """
    summary = {"created": 0, "skipped": 0, "failed": 0}

    urls = scrape_index()
    if not urls:
        logger.warning("No article URLs found, nothing to scrape")
        return summary

    for url in urls:
        if News.objects.filter(source_url=url).exists():
            logger.info("SKIP (duplicate): %s", url)
            summary["skipped"] += 1
            continue

        try:
            article_data = scrape_article(url)
            if not article_data:
                summary["failed"] += 1
                continue

            news_obj = News.objects.create(**article_data)
            logger.info("SAVED: %s", article_data["title"])
            summary["created"] += 1
            _notify_new_article(news_obj)
        except IntegrityError:
            logger.info("SKIP (race condition duplicate): %s", url)
            summary["skipped"] += 1
        except Exception:
            logger.exception("FAILED to scrape %s", url)
            summary["failed"] += 1

        time.sleep(REQUEST_DELAY)

    if summary["created"] > 0:
        cache.clear()
        logger.info("Cache cleared after creating %d new articles", summary["created"])

    logger.info(
        "Scraping complete: %d created, %d skipped, %d failed",
        summary["created"],
        summary["skipped"],
        summary["failed"],
    )
    return summary
