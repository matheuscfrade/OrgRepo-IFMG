"""
Management command: dump_full_data

Dumps the full current database (excluding some technical tables) into a fixture.
This fixture can later be used with `load_full_data` to restore a complete state.

Usage:
    python manage.py dump_full_data --output full_data.json
"""

from django.core.management.base import BaseCommand
from django.core.management import call_command
import os


class Command(BaseCommand):
    help = "Dump the full database content (for later restoration with load_full_data)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="full_data.json",
            help="Output filename for the fixture (default: full_data.json)",
        )

    def handle(self, *args, **options):
        output_file = options["output"]

        exclude = [
            "contenttypes",
            "auth.permission",
            "sessions.session",
            "admin.logentry",
        ]

        self.stdout.write(f"Dumping full data to {output_file}...")

        with open(output_file, "w", encoding="utf-8") as f:
            call_command(
                "dumpdata",
                "--natural-foreign",
                "--natural-primary",
                "--indent", "2",
                exclude=exclude,
                stdout=f,
            )

        self.stdout.write(self.style.SUCCESS(f"Full data dumped to {output_file}"))