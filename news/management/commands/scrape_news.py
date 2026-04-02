from django.core.management.base import BaseCommand

from news.pipeline.runner import run_pipeline
from news.pipeline.sources import SOURCES


class Command(BaseCommand):
    help = "Scrape news articles and save to database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default="udn",
            choices=SOURCES.keys(),
            help="News source to scrape (default: udn)",
        )

    def handle(self, *args, **options):
        source_name = options["source"]
        source = SOURCES[source_name]()

        self.stdout.write(f"Starting {source.name} news scraper...")
        result = run_pipeline(source)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {result.created} created, "
                f"{result.skipped} skipped, "
                f"{result.failed} failed"
            )
        )
