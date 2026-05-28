"""
Management command: load_full_data

Loads a full data fixture previously generated with `dump_full_data`.

Usage:
    python manage.py load_full_data
    python manage.py load_full_data --file data/full_data.json
"""

import os

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction


class Command(BaseCommand):
    help = "Load a full data fixture (previously generated with dump_full_data). Defaults to data/full_data.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="data/full_data.json",
            help="Path to the fixture file (default: data/full_data.json)",
        )

    def handle(self, *args, **options):
        fixture_file = options["file"]

        if not os.path.exists(fixture_file):
            self.stdout.write(self.style.ERROR(f"File not found: {fixture_file}"))
            self.stdout.write("Tip: Generate it first with 'python manage.py dump_full_data --output data/full_data.json'")
            return

        self.stdout.write(f"Loading full data from {fixture_file}...")

        with transaction.atomic():
            call_command("loaddata", fixture_file, verbosity=1)

        self.stdout.write(self.style.SUCCESS("Full data loaded successfully."))

        # Automatically copy media if present in data/media/
        mediaSource = BASE_DIR / "data" / "media"
        mediaDest   = BASE_DIR / "var" / "media"

        if mediaSource.exists():
            import shutil
            mediaDest.mkdir(parents=True, exist_ok=True)
            for item in mediaSource.glob("**/*"):
                if item.is_file():
                    relative = item.relative_to(mediaSource)
                    target = mediaDest / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
            self.stdout.write(self.style.SUCCESS("Media files copied from data/media/ to var/media/"))
        else:
            self.stdout.write(self.style.WARNING("No data/media/ folder found. PDFs were not copied."))
