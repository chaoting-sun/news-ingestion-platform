import json
from unittest.mock import patch, MagicMock

from django.test import TestCase

from news.pipeline.sources.tsna import TSNASource
from news.pipeline.types import ArticleData


# --- Sample JSON fixtures ---

TOP_RESPONSE = {
    "Code": "1",
    "Result": {
        "Newest": [
            {"ID": "50001", "Title": "Article 1"},
            {"ID": "50002", "Title": "Article 2"},
            {"ID": "50003", "Title": "Article 3"},
        ]
    },
}

TOP_RESPONSE_BAD_CODE = {
    "Code": "0",
    "Result": None,
}

TOP_RESPONSE_EMPTY = {
    "Code": "1",
    "Result": {"Newest": []},
}

DETAIL_RESPONSE = {
    "Code": "1",
    "Result": {
        "Body": {
            "Title": "Curry三分球破紀錄",
            "Author": "王小明",
            "Content": "<p>Curry今天投進了關鍵三分球。</p>",
            "PublishTime": "2025-06-10T18:30:00+08:00",
            "Cover": {
                "Url": "https://cdn.tsna.com/hero.jpg",
                "Title": "Curry celebrates",
            },
        }
    },
}

DETAIL_RESPONSE_NO_BODY = {
    "Code": "1",
    "Result": {"Body": {}},
}

DETAIL_RESPONSE_BAD_CODE = {
    "Code": "0",
    "Result": None,
}

DETAIL_RESPONSE_NO_PUBLISH_TIME = {
    "Code": "1",
    "Result": {
        "Body": {
            "Title": "Some Article",
            "Author": "Author",
            "Content": "<p>Content</p>",
            "PublishTime": "",
        }
    },
}


class TSNASourceDiscoverTest(TestCase):
    @patch("news.pipeline.sources.tsna.requests.get")
    def test_returns_article_urls(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = TOP_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        source = TSNASource()
        urls = source.discover()

        self.assertEqual(len(urls), 3)
        self.assertEqual(urls[0], "https://tsna.com/article/50001")
        self.assertEqual(urls[1], "https://tsna.com/article/50002")
        self.assertEqual(urls[2], "https://tsna.com/article/50003")

    @patch("news.pipeline.sources.tsna.requests.get")
    def test_returns_empty_on_bad_code(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = TOP_RESPONSE_BAD_CODE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        source = TSNASource()
        urls = source.discover()
        self.assertEqual(urls, [])

    @patch("news.pipeline.sources.tsna.requests.get")
    def test_returns_empty_when_no_articles(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = TOP_RESPONSE_EMPTY
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        source = TSNASource()
        urls = source.discover()
        self.assertEqual(urls, [])

    @patch("news.pipeline.sources.tsna.requests.get")
    def test_skips_items_without_id(self, mock_get):
        data = {
            "Code": "1",
            "Result": {
                "Newest": [
                    {"ID": "50001", "Title": "Has ID"},
                    {"Title": "No ID field"},
                    {"ID": "", "Title": "Empty ID"},
                ]
            },
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = data
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        source = TSNASource()
        urls = source.discover()
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], "https://tsna.com/article/50001")


class TSNASourceFetchTest(TestCase):
    @patch("news.pipeline.sources.tsna.requests.get")
    def test_fetch_extracts_id_and_returns_text(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = json.dumps(DETAIL_RESPONSE)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        source = TSNASource()
        result = source.fetch("https://tsna.com/article/50001")

        self.assertEqual(result, json.dumps(DETAIL_RESPONSE))
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        self.assertEqual(call_kwargs.kwargs["params"]["ID"], "50001")


class TSNASourceParseTest(TestCase):
    def test_parses_article_fields(self):
        source = TSNASource()
        raw = json.dumps(DETAIL_RESPONSE)
        result = source.parse("https://tsna.com/article/50001", raw)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, ArticleData)
        self.assertEqual(result.title, "Curry三分球破紀錄")
        self.assertEqual(result.author, "王小明")
        self.assertEqual(result.source_name, "TSNA")
        self.assertEqual(result.source_url, "https://tsna.com/article/50001")
        self.assertEqual(result.hero_image_url, "https://cdn.tsna.com/hero.jpg")
        self.assertEqual(result.hero_image_caption, "Curry celebrates")
        self.assertIn("Curry今天投進了關鍵三分球", result.content)

    def test_returns_none_on_invalid_json(self):
        source = TSNASource()
        result = source.parse("https://tsna.com/article/50001", "not valid json")
        self.assertIsNone(result)

    def test_returns_none_on_bad_code(self):
        source = TSNASource()
        raw = json.dumps(DETAIL_RESPONSE_BAD_CODE)
        result = source.parse("https://tsna.com/article/50001", raw)
        self.assertIsNone(result)

    def test_returns_none_on_empty_body(self):
        source = TSNASource()
        raw = json.dumps(DETAIL_RESPONSE_NO_BODY)
        result = source.parse("https://tsna.com/article/50001", raw)
        self.assertIsNone(result)

    def test_returns_none_when_no_publish_time(self):
        source = TSNASource()
        raw = json.dumps(DETAIL_RESPONSE_NO_PUBLISH_TIME)
        result = source.parse("https://tsna.com/article/50001", raw)
        self.assertIsNone(result)

    def test_handles_missing_cover(self):
        data = {
            "Code": "1",
            "Result": {
                "Body": {
                    "Title": "No Cover",
                    "Author": "Author",
                    "Content": "<p>Body</p>",
                    "PublishTime": "2025-06-10T18:30:00+08:00",
                }
            },
        }
        source = TSNASource()
        result = source.parse("https://tsna.com/article/50001", json.dumps(data))

        self.assertIsNotNone(result)
        self.assertEqual(result.hero_image_url, "")
        self.assertEqual(result.hero_image_caption, "")
