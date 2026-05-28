"""
Management command: load_full_data

Loads a full data fixture previously generated with `dump_full_data`.

This is useful when you want to restore a complete previous state
(all Campi + real Organogramas + Regimentos + Resoluções, etc.)
on top of the clean foundation.

The loader is **resilient**: it will import as many objects as possible
even if some records conflict (unique constraints, duplicate Users/Profiles, etc.).
At the end it prints a summary of what was loaded vs skipped.

By default it loads data/full_data.json (if present in the repo)
and automatically copies any PDFs/media from data/media/ into var/media/.

Usage examples:
    python manage.py load_full_data
    python manage.py load_full_data --file my_backup.json
    python manage.py load_full_data --no-media
"""

import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Load a full data fixture (best-effort / resilient mode). "
        "Imports as many objects as possible even when there are conflicts. "
        "Defaults to data/full_data.json + copies PDFs from data/media/."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="data/full_data.json",
            help="Path to the fixture file (default: data/full_data.json)",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="Skip copying media/PDF files from data/media/",
        )

    def handle(self, *args, **options):
        fixture_path = Path(options["file"])
        if not fixture_path.is_absolute():
            fixture_path = settings.BASE_DIR / fixture_path

        if not fixture_path.exists():
            self.stdout.write(self.style.ERROR(f"Fixture not found: {fixture_path}"))
            self.stdout.write(
                self.style.WARNING(
                    "The full data snapshot (data/full_data.json) is not present in this clone.\n"
                    "Use the clean foundation instead:\n"
                    "    python manage.py load_consup44_modelos"
                )
            )
            return

        self.stdout.write(f"Loading full data from {fixture_path}...")

        # Read the fixture with tolerant encoding.
        # The current full_data.json was generated on Windows and uses cp1252/latin-1.
        try:
            with open(fixture_path, encoding="utf-8") as f:
                fixture_content = f.read()
        except UnicodeDecodeError:
            self.stdout.write(
                self.style.WARNING(
                    "UTF-8 decoding failed. Using latin-1 fallback "
                    "(common when the JSON was created on Windows)..."
                )
            )
            with open(fixture_path, encoding="latin-1") as f:
                fixture_content = f.read()

        # Resilient object-by-object loading.
        # This allows the command to succeed even when the historical fixture
        # contains duplicates or conflicts with existing data (e.g. CargoFuncao,
        # User + Profile relationships, etc.).
        from io import StringIO
        from django.core import serializers
        from django.db import IntegrityError
        from django.core.exceptions import ValidationError

        loaded = 0
        skipped = 0
        errors = 0

        self.stdout.write("Importing objects (best-effort mode)...")

        for deserialized_obj in serializers.deserialize(
            "json", StringIO(fixture_content), ignorenonexistent=True
        ):
            try:
                deserialized_obj.save()
                loaded += 1
            except (IntegrityError, ValidationError) as e:
                skipped += 1
                if options.get("verbosity", 1) >= 2:
                    self.stdout.write(
                        self.style.WARNING(f"  Skipped {deserialized_obj.object._meta.label}: {e}")
                    )
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"  Error on {deserialized_obj.object._meta.label}: {e}"))

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Import finished."))
        self.stdout.write(f"  Loaded:   {loaded}")
        self.stdout.write(f"  Skipped (conflicts/duplicates): {skipped}")
        if errors:
            self.stdout.write(self.style.WARNING(f"  Errors:   {errors}"))

        if loaded == 0 and skipped > 0:
            self.stdout.write(
                self.style.WARNING(
                    "\nNo objects were loaded because of conflicts.\n"
                    "This usually happens when foundation data (Cargos, Profiles, etc.) "
                    "already exists. Try on a fresh database after 'migrate' only."
                )
            )

        # Copy media files (PDFs of regimentos, resoluções, etc.)
        if not options.get("no_media"):
            self._copy_media_files()

        self.stdout.write(
            self.style.WARNING(
                "Note: If reference models (Modelos Referenciais, Cargos, etc.) were overwritten, "
                "you may want to run:\n"
                "    python manage.py load_consup44_modelos"
            )
        )

    def _copy_media_files(self):
        src = settings.BASE_DIR / "data" / "media"
        dst = settings.BASE_DIR / "var" / "media"

        if not src.exists():
            self.stdout.write(
                self.style.WARNING("No data/media/ folder found — skipping PDF copy.")
            )
            return

        dst.mkdir(parents=True, exist_ok=True)

        self.stdout.write("Copying media files (PDFs) from data/media/ to var/media/...")

        copied = 0
        for root, dirs, files in os.walk(src):
            rel = Path(root).relative_to(src)
            target_dir = dst / rel
            target_dir.mkdir(parents=True, exist_ok=True)

            for filename in files:
                src_file = Path(root) / filename
                dst_file = target_dir / filename
                shutil.copy2(src_file, dst_file)
                copied += 1

        if copied > 0:
            self.stdout.write(
                self.style.SUCCESS(f"Copied {copied} media file(s) into var/media/.")
            )
        else:
            self.stdout.write("No media files found to copy.")
