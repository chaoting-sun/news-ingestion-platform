import json
import re
from datetime import datetime
from urllib.parse import urlparse, urlunparse

import requests
import structlog
from bs4 import BeautifulSoup

from news.pipeline.types import ArticleData

logger = structlog.get_logger()

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


def _sanitize_content(body_span) -> str:
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


class UDNSource:
    """Scrapes NBA news from UDN (聯合報)."""

    name = "udn"
    request_delay = REQUEST_DELAY

    def discover(self) -> list[str]:
        """Fetch the index page and return canonical article URLs from the
        焦點新聞 carousel."""
        html = self.fetch(INDEX_URL)
        soup = BeautifulSoup(html, "lxml")

        focus = soup.select_one("#focus")
        if not focus:
            logger.warning("discover.no_focus", msg="Could not find #focus element")
            return []

        links = focus.select(".splide__list .splide__slide a[href]")
        urls = []
        for a_tag in links:
            raw_url = a_tag.get("href", "")
            if "/nba/story/" not in raw_url:
                continue
            urls.append(_clean_url(raw_url))

        logger.info("discover.complete", url_count=len(urls))
        return urls

    def fetch(self, url: str) -> str:
        """Download a URL and return the response text."""
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text

    def parse(self, url: str, raw_html: str) -> ArticleData | None:
        """Extract article data from a UDN article page."""
        soup = BeautifulSoup(raw_html, "lxml")

        json_ld = _extract_json_ld(soup)
        if not json_ld:
            logger.warning("parse.no_json_ld", url=url)
            return None

        title = json_ld.get("headline", "")

        author_meta = soup.select_one('meta[property="dable:author"]')
        author = author_meta["content"] if author_meta else ""

        pubdate_meta = soup.select_one('meta[name="pubdate"]')
        if not pubdate_meta:
            logger.warning("parse.no_pubdate", url=url)
            return None
        published_at = datetime.fromisoformat(pubdate_meta["content"])

        source_name = self._extract_source_name(soup)

        image_data = json_ld.get("image", {})
        hero_image_url = ""
        hero_image_caption = ""
        if isinstance(image_data, dict):
            hero_image_url = image_data.get("url", image_data.get("contentUrl", ""))
            hero_image_caption = image_data.get("name", "")

        body_span = soup.select_one("#story_body_content > span")
        content = ""
        if body_span:
            content = _sanitize_content(body_span)
        else:
            logger.warning("parse.no_body", url=url)

        return ArticleData(
            title=title,
            author=author,
            published_at=published_at,
            source_name=source_name,
            source_url=url,
            content=content,
            hero_image_url=hero_image_url,
            hero_image_caption=hero_image_caption,
        )

    @staticmethod
    def _extract_source_name(soup: BeautifulSoup) -> str:
        """Extract the source name from the author div."""
        author_div = soup.select_one(".shareBar__info--author")
        if author_div:
            text = author_div.get_text(strip=True)
            date_span = author_div.select_one("span")
            if date_span:
                text = text.replace(date_span.get_text(), "", 1).strip()
            if "/" in text:
                return text.split("/")[0].strip()
            if text.strip():
                return text.strip()
        return "udn NBA"
