"""
Management command: clean_full_data

Aggressively cleans a full_data.json fixture:

- Keeps only OFICIAL organogramas (status=OFICIAL)
- Removes all test/dummy Campi (names containing: test, teste, demo, dummy, etc.)
- Removes non-vigente regimentos
- Removes test regimentos (name containing "test")
- Removes Units, Solicitações, and other objects linked to removed data

This produces a clean fixture suitable for distribution.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Aggressively clean a full_data.json fixture: "
        "remove test Campi, non-OFICIAL organogramas, non-vigente regimentos, "
        "test regimentos, and all related draft/test data."
    )

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

        # ============================================
        # AGGRESSIVE CLEANING - Multiple passes
        # ============================================

        # Pass 1: Identify test Campi
        test_campus_patterns = ["test", "teste", "demo", "dummy", "exemplo", "sample"]
        test_campus_pks = set()

        for obj in data:
            if obj.get("model") == "core.campus":
                fields = obj.get("fields", {})
                nome = (fields.get("nome") or "").lower()
                sigla = (fields.get("sigla") or "").lower()
                if any(p in nome or p in sigla for p in test_campus_patterns):
                    pk = obj.get("pk")
                    if pk is not None:
                        test_campus_pks.add(pk)

        self.stdout.write(f"Detected {len(test_campus_pks)} test/dummy Campi to remove.")

        # Pass 2: Collect kept Campi (non-test)
        kept_campus_pks = set()
        for obj in data:
            if obj.get("model") == "core.campus":
                pk = obj.get("pk")
                if pk is not None and pk not in test_campus_pks:
                    kept_campus_pks.add(pk)

        # Pass 3: Collect kept Organogramas (OFICIAL + belonging to kept Campi)
        kept_organograma_pks = set()
        for obj in data:
            if obj.get("model") == "core.organograma":
                fields = obj.get("fields", {})
                pk = obj.get("pk")
                campus_ref = fields.get("campus")
                status = fields.get("status")

                if pk is not None:
                    if status == "OFICIAL" and campus_ref in kept_campus_pks:
                        kept_organograma_pks.add(pk)

        self.stdout.write(f"Keeping {len(kept_organograma_pks)} official organogramas.")

        # Pass 4: Collect kept Regimentos (vigente + not test name + from kept campi)
        kept_regimento_pks = set()
        for obj in data:
            if obj.get("model") == "core.regimentocampus":
                fields = obj.get("fields", {})
                pk = obj.get("pk")
                campus_ref = fields.get("campus")
                nome = (fields.get("nome") or "").lower()
                vigente = fields.get("vigente", False)

                if pk is not None:
                    if ("test" not in nome and
                        vigente is True and
                        campus_ref in kept_campus_pks):
                        kept_regimento_pks.add(pk)

        self.stdout.write(f"Keeping {len(kept_regimento_pks)} vigente official regimentos.")

        # ============================================
        # Final filtering pass
        # ============================================
        cleaned = []
        removed_by_model = {}

        for obj in data:
            model = obj.get("model", "")
            fields = obj.get("fields", {})
            pk = obj.get("pk")

            keep = True
            reason = ""

            if model == "core.campus":
                if pk in test_campus_pks:
                    keep = False
                    reason = "test/dummy campus"

            elif model == "core.organograma":
                campus_ref = fields.get("campus")
                status = fields.get("status")
                if status != "OFICIAL" or campus_ref not in kept_campus_pks:
                    keep = False
                    reason = f"non-OFICIAL or from test campus (status={status})"

            elif model == "core.unit":
                orga_ref = fields.get("organograma")
                if orga_ref and orga_ref not in kept_organograma_pks:
                    keep = False
                    reason = "belongs to non-official organograma"

            elif model == "core.solicitacaoalteracao":
                status = fields.get("status")
                if status in ("RASCUNHO", "DEVOLVIDO_CORRECAO"):
                    keep = False
                    reason = f"draft status={status}"
                else:
                    orig = fields.get("organograma_original")
                    prop = fields.get("organograma_proposto")
                    if (orig and orig not in kept_organograma_pks) or \
                       (prop and prop not in kept_organograma_pks):
                        keep = False
                        reason = "linked to non-official organograma"

            elif model == "core.regimentocampus":
                campus_ref = fields.get("campus")
                nome = (fields.get("nome") or "").lower()
                vigente = fields.get("vigente", False)

                if campus_ref not in kept_campus_pks:
                    keep = False
                    reason = "belongs to test campus"
                elif "test" in nome:
                    keep = False
                    reason = "test regimento"
                elif not vigente:
                    keep = False
                    reason = "non-vigente regimento"

            # Future-proof: also drop any objects pointing to removed campuses/organogramas
            if keep:
                for fk_field in ("campus", "organograma", "organograma_original", "organograma_proposto"):
                    ref = fields.get(fk_field)
                    if ref is not None:
                        if fk_field == "campus" and ref not in kept_campus_pks:
                            keep = False
                            reason = "references removed test campus"
                            break
                        if fk_field in ("organograma", "organograma_original", "organograma_proposto") and ref not in kept_organograma_pks:
                            keep = False
                            reason = "references removed non-official organograma"
                            break

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
            "The fixture is now much cleaner (only official organogramas + clean related data)."
        )
        self.stdout.write(
            "You can commit/replace data/full_data.json with this file."
        )
