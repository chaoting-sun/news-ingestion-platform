from __future__ import annotations

import dataclasses
from datetime import datetime


@dataclasses.dataclass
class ArticleData:
    """Source-independent representation of a scraped article."""

    title: str
    author: str
    published_at: datetime
    source_name: str
    source_url: str
    content: str
    hero_image_url: str = ""
    hero_image_caption: str = ""


@dataclasses.dataclass
class PipelineResult:
    """Aggregated outcome of a pipeline run."""

    created: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return dataclasses.asdict(self)
