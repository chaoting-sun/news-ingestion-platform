from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from news.models import News


class NewsModelTest(TestCase):
    def _make_news(self, **overrides):
        defaults = {
            "title": "Test Title",
            "author": "Author",
            "published_at": timezone.now(),
            "source_name": "udn NBA",
            "source_url": "https://tw-nba.udn.com/nba/story/7002/10001",
            "content": "<p>Body</p>",
        }
        defaults.update(overrides)
        return News.objects.create(**defaults)

    def test_str_returns_title(self):
        news = self._make_news(title="Lakers win championship")
        self.assertEqual(str(news), "Lakers win championship")

    def test_unique_source_url(self):
        url = "https://tw-nba.udn.com/nba/story/7002/99999"
        self._make_news(source_url=url)
        with self.assertRaises(IntegrityError):
            self._make_news(source_url=url)

    def test_ordering_by_published_at_desc(self):
        now = timezone.now()
        old = self._make_news(
            source_url="https://example.com/1",
            published_at=now - timezone.timedelta(hours=2),
        )
        new = self._make_news(
            source_url="https://example.com/2",
            published_at=now,
        )
        result = list(News.objects.all())
        self.assertEqual(result, [new, old])

    def test_blank_fields_default_to_empty(self):
        news = self._make_news(author="", hero_image_url="", hero_image_caption="")
        news.refresh_from_db()
        self.assertEqual(news.author, "")
        self.assertEqual(news.hero_image_url, "")
        self.assertEqual(news.hero_image_caption, "")

    def test_auto_timestamps(self):
        news = self._make_news()
        self.assertIsNotNone(news.created_at)
        self.assertIsNotNone(news.updated_at)
