from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from news.models import News
from news.pipeline.sources.udn import (
    _clean_url,
    _extract_json_ld,
    _sanitize_content,
    UDNSource,
)
from news.pipeline.runner import run_pipeline
from news.pipeline.types import ArticleData

from bs4 import BeautifulSoup


# --- Sample HTML fixtures ---

INDEX_HTML = """
<html><body>
<div id="focus">
  <div class="splide__list">
    <div class="splide__slide"><a href="https://tw-nba.udn.com/nba/story/7002/1001?from=udn">Article 1</a></div>
    <div class="splide__slide"><a href="https://tw-nba.udn.com/nba/story/7002/1002?from=udn">Article 2</a></div>
    <div class="splide__slide"><a href="https://tw-nba.udn.com/nba/ads/banner">Ad link</a></div>
  </div>
</div>
</body></html>
"""

ARTICLE_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@type": "NewsArticle",
  "headline": "Lakers Beat Celtics",
  "image": {
    "url": "https://example.com/hero.jpg",
    "name": "Game photo"
  }
}
</script>
<meta property="dable:author" content="John Doe">
<meta name="pubdate" content="2025-01-15T10:00:00+08:00">
</head><body>
<div class="shareBar__info--author">udn NBA / <span>2025-01-15</span></div>
<div id="story_body_content"><span><p>First paragraph.</p><div class="inline-ad">ad</div><p>Second paragraph.</p></span></div>
</body></html>
"""

ARTICLE_HTML_NO_JSON_LD = """
<html><head>
<meta name="pubdate" content="2025-01-15T10:00:00+08:00">
</head><body></body></html>
"""


class CleanUrlTest(TestCase):
    def test_strips_query_params(self):
        url = "https://tw-nba.udn.com/nba/story/7002/1001?from=udn&utm=test"
        self.assertEqual(
            _clean_url(url),
            "https://tw-nba.udn.com/nba/story/7002/1001",
        )

    def test_preserves_clean_url(self):
        url = "https://tw-nba.udn.com/nba/story/7002/1001"
        self.assertEqual(_clean_url(url), url)


class ExtractJsonLdTest(TestCase):
    def test_extracts_news_article(self):
        html = """
        <html><head>
        <script type="application/ld+json">{"@type": "NewsArticle", "headline": "Test"}</script>
        </head></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_json_ld(soup)
        self.assertEqual(result["headline"], "Test")

    def test_ignores_non_news_article(self):
        html = """
        <html><head>
        <script type="application/ld+json">{"@type": "WebPage", "name": "Test"}</script>
        </head></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertIsNone(_extract_json_ld(soup))

    def test_handles_invalid_json(self):
        html = """
        <html><head>
        <script type="application/ld+json">not valid json</script>
        </head></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertIsNone(_extract_json_ld(soup))

    def test_returns_none_when_no_script(self):
        soup = BeautifulSoup("<html></html>", "html.parser")
        self.assertIsNone(_extract_json_ld(soup))


class SanitizeContentTest(TestCase):
    def test_removes_ads_and_scripts(self):
        html = """
        <span>
            <p>Keep this.</p>
            <div class="inline-ad">ad content</div>
            <script>alert(1)</script>
            <p>Also keep.</p>
        </span>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = _sanitize_content(soup.find("span"))
        self.assertIn("Keep this.", result)
        self.assertIn("Also keep.", result)
        self.assertNotIn("inline-ad", result)
        self.assertNotIn("script", result)
        self.assertNotIn("alert", result)

    def test_removes_empty_paragraphs(self):
        html = "<span><p>Content</p><p>   </p></span>"
        soup = BeautifulSoup(html, "html.parser")
        result = _sanitize_content(soup.find("span"))
        self.assertNotIn("<p>   </p>", result)
        self.assertIn("Content", result)


class UDNSourceDiscoverTest(TestCase):
    @patch.object(UDNSource, "fetch")
    def test_returns_cleaned_article_urls(self, mock_fetch):
        mock_fetch.return_value = INDEX_HTML
        source = UDNSource()
        urls = source.discover()

        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0], "https://tw-nba.udn.com/nba/story/7002/1001")
        self.assertEqual(urls[1], "https://tw-nba.udn.com/nba/story/7002/1002")

    @patch.object(UDNSource, "fetch")
    def test_filters_non_story_links(self, mock_fetch):
        mock_fetch.return_value = INDEX_HTML
        source = UDNSource()
        urls = source.discover()

        for url in urls:
            self.assertIn("/nba/story/", url)

    @patch.object(UDNSource, "fetch")
    def test_returns_empty_when_no_focus(self, mock_fetch):
        mock_fetch.return_value = "<html><body></body></html>"
        source = UDNSource()
        urls = source.discover()
        self.assertEqual(urls, [])


class UDNSourceParseTest(TestCase):
    def test_parses_article_fields(self):
        source = UDNSource()
        result = source.parse("https://tw-nba.udn.com/nba/story/7002/1001", ARTICLE_HTML)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, ArticleData)
        self.assertEqual(result.title, "Lakers Beat Celtics")
        self.assertEqual(result.author, "John Doe")
        self.assertEqual(result.source_name, "udn NBA")
        self.assertEqual(result.source_url, "https://tw-nba.udn.com/nba/story/7002/1001")
        self.assertEqual(result.hero_image_url, "https://example.com/hero.jpg")
        self.assertEqual(result.hero_image_caption, "Game photo")
        self.assertIn("First paragraph.", result.content)
        self.assertNotIn("inline-ad", result.content)

    def test_returns_none_without_json_ld(self):
        source = UDNSource()
        result = source.parse("https://tw-nba.udn.com/nba/story/7002/1001", ARTICLE_HTML_NO_JSON_LD)
        self.assertIsNone(result)


class RunPipelineTest(TestCase):
    def setUp(self):
        cache.clear()

    def _make_source(self):
        source = UDNSource()
        source.request_delay = 0  # no delay in tests
        return source

    @patch("news.pipeline.runner.notify")
    @patch.object(UDNSource, "parse")
    @patch.object(UDNSource, "fetch")
    @patch.object(UDNSource, "discover")
    def test_creates_new_articles(self, mock_discover, mock_fetch, mock_parse, mock_notify):
        mock_discover.return_value = ["https://example.com/story/1"]
        mock_fetch.return_value = "<html></html>"
        mock_parse.return_value = ArticleData(
            title="New Article",
            author="Author",
            published_at=timezone.now(),
            source_name="udn NBA",
            source_url="https://example.com/story/1",
            content="<p>Body</p>",
        )

        result = run_pipeline(self._make_source())

        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.failed, 0)
        self.assertEqual(News.objects.count(), 1)
        mock_notify.assert_called_once()

    @patch("news.pipeline.runner.notify")
    @patch.object(UDNSource, "fetch")
    @patch.object(UDNSource, "discover")
    def test_skips_duplicate_urls(self, mock_discover, mock_fetch, mock_notify):
        News.objects.create(
            title="Existing",
            author="Author",
            published_at=timezone.now(),
            source_name="udn NBA",
            source_url="https://example.com/story/1",
            content="<p>Old</p>",
        )
        mock_discover.return_value = ["https://example.com/story/1"]

        result = run_pipeline(self._make_source())

        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.created, 0)
        mock_fetch.assert_not_called()

    @patch("news.pipeline.runner.notify")
    @patch.object(UDNSource, "parse")
    @patch.object(UDNSource, "fetch")
    @patch.object(UDNSource, "discover")
    def test_counts_failed_articles(self, mock_discover, mock_fetch, mock_parse, mock_notify):
        mock_discover.return_value = ["https://example.com/story/1"]
        mock_fetch.return_value = "<html></html>"
        mock_parse.return_value = None

        result = run_pipeline(self._make_source())

        self.assertEqual(result.failed, 1)
        self.assertEqual(result.created, 0)

    @patch.object(UDNSource, "discover")
    def test_returns_empty_result_when_no_urls(self, mock_discover):
        mock_discover.return_value = []

        result = run_pipeline(self._make_source())

        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.failed, 0)
