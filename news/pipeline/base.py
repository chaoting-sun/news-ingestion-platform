from __future__ import annotations

from typing import Protocol

from .types import ArticleData


class NewsSource(Protocol):
    """Interface that every news source must implement."""

    name: str

    def discover(self) -> list[str]:
        """Return a list of article URLs to process."""
        ...

    def fetch(self, url: str) -> str:
        """Download a single URL and return the raw HTML."""
        ...

    def parse(self, url: str, raw_html: str) -> ArticleData | None:
        """Extract article data from raw HTML. Return None on failure."""
        ...
