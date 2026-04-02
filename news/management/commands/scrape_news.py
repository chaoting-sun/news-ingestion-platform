from django.core.management.base import BaseCommand

from news.scraper import run_scraper


class Command(BaseCommand):
    help = "Scrape 焦點新聞 from UDN NBA index page and save to database"

    def handle(self, *args, **options):
        self.stdout.write("Starting UDN NBA news scraper...")
        summary = run_scraper()
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {summary['created']} created, "
                f"{summary['skipped']} skipped, "
                f"{summary['failed']} failed"
            )
        )
