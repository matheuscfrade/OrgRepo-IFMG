"""
Management command: clean_full_data

Cleans a full_data.json fixture by removing test/draft data,
keeping only OFICIAL organogramas and their related records.

This is the recommended way to prepare a clean version of the
historical data for distribution in the repository.

Usage:
    python manage.py clean_full_data --input data/full_data.json --output data/full_data.json --force

After running, the output file will contain only official organogramas,
their units, approved solicitações, official regimentos, etc.
Test regimentos (name containing "test") are also removed.
"""

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Clean a full_data.json fixture: keep only OFICIAL organogramas and remove test/draft data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default="data/full_data.json",
            help="Path to the input fixture file",
        )
        parser.add_argument(
            "--output",
            default="data/full_data.json",
            help="Path to write the cleaned fixture (can be same as input with --force)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite output file without asking",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be removed without writing the file",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])
        output_path = Path(options["output"])
        dry_run = options["dry_run"]

        if not input_path.exists():
            self.stdout.write(self.style.ERROR(f"Input file not found: {input_path}"))
            return

        self.stdout.write(f"Loading fixture from {input_path}...")

        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            self.stdout.write(self.style.ERROR("Fixture does not look like a valid Django dump (expected list of objects)."))
            return

        original_count = len(data)

        # Pass 1: collect PKs of official organogramas
        oficial_organograma_pks = set()
        for obj in data:
            if obj.get("model") == "core.organograma":
                fields = obj.get("fields", {})
                if fields.get("status") == "OFICIAL":
                    pk = obj.get("pk")
                    if pk is not None:
                        oficial_organograma_pks.add(pk)

        self.stdout.write(f"Found {len(oficial_organograma_pks)} OFICIAL organogramas.")

        # Pass 2: filter objects
        cleaned = []
        removed_by_model = {}

        for obj in data:
            model = obj.get("model", "")
            fields = obj.get("fields", {})
            pk = obj.get("pk")

            keep = True
            reason = ""

            if model == "core.organograma":
                if fields.get("status") != "OFICIAL":
                    keep = False
                    reason = f"status={fields.get('status')}"

            elif model == "core.unit":
                # Keep only units that belong to an official organograma
                orga_ref = fields.get("organograma")
                if orga_ref and orga_ref not in oficial_organograma_pks:
                    keep = False
                    reason = "belongs to non-OFICIAL organograma"

            elif model == "core.solicitacaoalteracao":
                status = fields.get("status")
                if status in ("RASCUNHO", "DEVOLVIDO_CORRECAO"):
                    keep = False
                    reason = f"status={status}"
                else:
                    # Also drop if linked to non-official organogramas
                    orig = fields.get("organograma_original")
                    prop = fields.get("organograma_proposto")
                    if (orig and orig not in oficial_organograma_pks) or \
                       (prop and prop not in oficial_organograma_pks):
                        keep = False
                        reason = "linked to non-OFICIAL organograma"

            elif model == "core.regimentocampus":
                nome = (fields.get("nome") or "").lower()
                if "test" in nome:
                    keep = False
                    reason = "test regimento"

            if keep:
                cleaned.append(obj)
            else:
                removed_by_model[model] = removed_by_model.get(model, 0) + 1
                if options.get("verbosity", 1) >= 2:
                    self.stdout.write(f"  Removing {model} (pk={pk}): {reason}")

        removed_total = original_count - len(cleaned)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Cleaning complete."))
        self.stdout.write(f"  Original objects: {original_count}")
        self.stdout.write(f"  Kept objects:     {len(cleaned)}")
        self.stdout.write(f"  Removed objects:  {removed_total}")

        if removed_by_model:
            self.stdout.write("\nRemoved by model:")
            for model, count in sorted(removed_by_model.items()):
                self.stdout.write(f"  {model}: {count}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry-run mode — no file was written."))
            return

        # Write output
        if output_path.exists() and not options["force"]:
            self.stdout.write(
                self.style.ERROR(
                    f"Output file already exists: {output_path}\n"
                    "Use --force to overwrite or choose a different --output path."
                )
            )
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2, ensure_ascii=False)

        self.stdout.write(
            self.style.SUCCESS(f"\nCleaned fixture written to: {output_path}")
        )
        self.stdout.write(
            "You can now commit this file (or replace data/full_data.json with it)."
        )
