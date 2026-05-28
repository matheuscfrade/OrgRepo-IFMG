"""
Management command: load_full_data

Loads a full data fixture previously generated with `dump_full_data`.

Usage:
    python manage.py load_full_data --file full_data.json
"""

import os

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction


class Command(BaseCommand):
    help = "Load a full data fixture (previously generated with dump_full_data)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the fixture file (e.g. full_data.json)",
        )

    def handle(self, *args, **options):
        fixture_file = options["file"]

        if not os.path.exists(fixture_file):
            self.stdout.write(self.style.ERROR(f"File not found: {fixture_file}"))
            return

        self.stdout.write(f"Loading full data from {fixture_file}...")

        with transaction.atomic():
            call_command("loaddata", fixture_file, verbosity=1)

        self.stdout.write(self.style.SUCCESS("Full data loaded successfully."))