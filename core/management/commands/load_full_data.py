"""
Management command: load_full_data

Loads a full data fixture previously generated with `dump_full_data`.

This is useful when you want to restore a complete previous state
(all Campi + real Organogramas + Regimentos + Resoluções, etc.)
on top of the clean foundation.

The loader is **resilient**:
- Multi-pass import for self-referential FKs (Unit.unidade_pai, UnitModelo, etc.)
- Natural-key remapping for CargoFuncao (nome+sigla) and TipoUnidade (nome)
  when fixture PKs differ from an already-loaded foundation (load_consup44_modelos)
- Optional FKs that still cannot be resolved are nulled so the object can load
- At the end it prints a summary of what was loaded vs skipped

Use --only-oficial to keep **only the official organogramas** (status=OFICIAL)
and automatically remove test/draft data (RASCUNHO, PROPOSTA, test regimentos, etc.).

By default it loads data/full_data.json (if present in the repo)
and automatically copies any PDFs/media from data/media/ into var/media/.

Usage examples:
    python manage.py load_full_data
    python manage.py load_full_data --only-oficial
    python manage.py load_full_data --file my_backup.json --only-oficial --no-media

Recommended for a clean restore (avoids PK clashes with foundation):
    python manage.py migrate
    python manage.py load_full_data
    python manage.py load_consup44_modelos   # refresh normative reference models
"""

import json
import os
import shutil
from collections import Counter, defaultdict
from copy import deepcopy
from io import StringIO
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import IntegrityError, connection, transaction


# Models with self-FK trees that often need multi-pass loading
# (fixture model names are lowercase app_label.model)
SELF_FK_MODELS = {
    "core.unit",
    "core.unitmodelo",
}

# If PK already exists, still apply fixture fields (avoids migrate-created
# placeholder rows blocking Reitor/etc. with wrong natural keys).
LOOKUP_UPDATE_MODELS = {
    "core.cargofuncao",
    "core.tipounidade",
    "core.dimensionamento",
    "core.campus",
    "core.modeloreferencial",
    "core.regrasalteracaomodelo",
}

# Max passes for dependency-ordered retry
MAX_PASSES = 30


class Command(BaseCommand):
    help = (
        "Load a full data fixture (resilient multi-pass mode with FK remapping). "
        "Use --only-oficial to import ONLY the official organogramas (status=OFICIAL) "
        "and automatically clean test/draft data (including regimentos named 'test'). "
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
        parser.add_argument(
            "--only-oficial",
            action="store_true",
            help=(
                "Import ONLY official organogramas (status=OFICIAL) and clean "
                "test/draft data (including regimentos named 'test')."
            ),
        )

    def handle(self, *args, **options):
        self.verbosity = options.get('verbosity', 1)
        fixture_path = Path(options["file"])
        if not fixture_path.is_absolute():
            fixture_path = settings.BASE_DIR / fixture_path

        if not fixture_path.exists():
            raise CommandError(
                f"Fixture not found: {fixture_path}\n"
                "Provide data/full_data.json or use:\n"
                "    python manage.py load_consup44_modelos"
            )

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

        try:
            fixture_objects = json.loads(fixture_content)
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON fixture: {e}") from e

        if not isinstance(fixture_objects, list) or not fixture_objects:
            raise CommandError(f"Fixture is empty or not a JSON list: {fixture_path}")

        # Natural-key maps for CargoFuncao / TipoUnidade (foundation PKs may differ)
        self._cargo_pk_map = self._build_cargo_map(fixture_objects)
        self._tipo_pk_map = self._build_tipo_map(fixture_objects)
        if self._cargo_pk_map or self._tipo_pk_map:
            self.stdout.write(
                f"Natural-key remaps ready: "
                f"{len(self._cargo_pk_map)} cargos, {len(self._tipo_pk_map)} tipos"
            )

        # Filter objects for --only-oficial
        if options.get("only_oficial"):
            fixture_objects = self._filter_only_oficial(fixture_objects)

        loaded = 0
        skipped = 0
        errors = 0
        skip_reasons = Counter()

        # Group for multi-pass: non-self-FK first, then self-FK models
        plain_objects = []
        tree_objects = []
        for obj_data in fixture_objects:
            model = (obj_data.get("model") or "").lower()
            if model in SELF_FK_MODELS:
                tree_objects.append(obj_data)
            else:
                plain_objects.append(obj_data)

        self.stdout.write("Importing objects (resilient multi-pass mode)...")

        # Pass 1+: plain objects (lookups, campi, organogramas, competencias later need units)
        # Competencias depend on units — pull them into a third phase
        competency_objects = [
            o for o in plain_objects if (o.get("model") or "").lower() == "core.competenciaunidade"
        ]
        plain_without_comp = [
            o for o in plain_objects if (o.get("model") or "").lower() != "core.competenciaunidade"
        ]

        n_loaded, n_skipped, n_errors, reasons = self._multipass_load(
            plain_without_comp, "lookup/relational"
        )
        loaded += n_loaded
        skipped += n_skipped
        errors += n_errors
        skip_reasons.update(reasons)

        # Rebuild maps after cargos/tipos from fixture (or foundation) are present
        self._cargo_pk_map = self._build_cargo_map(fixture_objects)
        self._tipo_pk_map = self._build_tipo_map(fixture_objects)

        # Tree objects (Unit, UnitModelo) — multi-pass for unidade_pai
        n_loaded, n_skipped, n_errors, reasons = self._multipass_load(
            tree_objects, "tree (self-FK)"
        )
        loaded += n_loaded
        skipped += n_skipped
        errors += n_errors
        skip_reasons.update(reasons)

        # Align unit cargo/tipo FKs to natural keys (fixes foundation PK clashes)
        remapped = self._realign_unit_fks(fixture_objects)
        if remapped:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Realignados cargos/tipos em {remapped} unidade(s) "
                    f"(compatível com load_consup44_modelos prévio)."
                )
            )

        # Competencias last (depend on units)
        n_loaded, n_skipped, n_errors, reasons = self._multipass_load(
            competency_objects, "competencias"
        )
        loaded += n_loaded
        skipped += n_skipped
        errors += n_errors
        skip_reasons.update(reasons)

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Import finished."))
        self.stdout.write(f"  Loaded / applied: {loaded}")
        self.stdout.write(f"  Skipped (conflicts/unresolvable FKs): {skipped}")
        if errors:
            self.stdout.write(self.style.WARNING(f"  Errors:   {errors}"))
        if skip_reasons and options.get("verbosity", 1) >= 2:
            self.stdout.write("  Top skip reasons:")
            for reason, count in skip_reasons.most_common(15):
                self.stdout.write(f"    [{count}] {reason}")

        expected_core = sum(
            1
            for o in fixture_objects
            if (o.get("model") or "").lower()
            in {
                "core.campus",
                "core.organograma",
                "core.unit",
                "core.regimentocampus",
                "core.resolucaoestruturaorganizacional",
            }
        )
        if loaded == 0 and expected_core > 0:
            raise CommandError(
                "No objects were loaded while the fixture has core instance data. "
                "Use a clean database: migrate, then load_full_data (docs/setup.md Opção B)."
            )

        problems = self._print_integrity_report(fixture_objects)
        if problems:
            raise CommandError(
                f"{problems} core model(s) below fixture count after load. "
                "Bootstrap aborted so the app does not start half-loaded. "
                "Fix the database/fixture and retry."
            )

        # Postgres: reset sequences after explicit-PK inserts (like loaddata).
        self._reset_postgres_sequences(fixture_objects)

        # Align cargo quotas with official organogramas (avoids "CD-03: 4 / -")
        # Fixture cotas often use different CargoFuncao PKs than the foundation.
        # Docker path runs sync again after load_consup44_modelos (authoritative).
        self._sync_cargo_quotas_from_officials()

        # Copy media files (PDFs of regimentos, resoluções, etc.)
        if not options.get("no_media"):
            self._copy_media_files()
            self._verify_media_files(fixture_objects)

        if options.get("only_oficial"):
            self.stdout.write(
                self.style.SUCCESS(
                    "\n--only-oficial mode used: Only OFICIAL organogramas were imported. "
                    "Test/draft data (including test regimentos) was cleaned from the fixture."
                )
            )
        else:
            self.stdout.write(
                self.style.NOTICE(
                    "Dica: para alinhar Modelos Referenciais à Resolução 44 vigente, rode:\n"
                    "    python manage.py load_consup44_modelos\n"
                    "    python manage.py sync_cargo_quotas"
                )
            )

    # ------------------------------------------------------------------
    # Natural-key maps
    # ------------------------------------------------------------------
    def _build_cargo_map(self, fixture_objects):
        """Map fixture CargoFuncao PK -> current DB PK via (nome, sigla)."""
        from core.models import CargoFuncao

        mapping = {}
        for obj in fixture_objects:
            if obj.get("model") != "core.cargofuncao":
                continue
            fpk = obj.get("pk")
            fields = obj.get("fields") or {}
            nome = fields.get("nome")
            sigla = fields.get("sigla")
            if fpk is None or not nome:
                continue
            db = CargoFuncao.objects.filter(nome=nome, sigla=sigla).first()
            if db and db.pk != fpk:
                mapping[fpk] = db.pk
            elif db:
                mapping[fpk] = db.pk  # same PK, still useful as identity
        return mapping

    def _build_tipo_map(self, fixture_objects):
        """Map fixture TipoUnidade PK -> current DB PK via nome."""
        from core.models import TipoUnidade

        mapping = {}
        for obj in fixture_objects:
            if obj.get("model") != "core.tipounidade":
                continue
            fpk = obj.get("pk")
            fields = obj.get("fields") or {}
            nome = fields.get("nome")
            if fpk is None or not nome:
                continue
            db = TipoUnidade.objects.filter(nome=nome).first()
            if db:
                mapping[fpk] = db.pk
        return mapping

    def _filter_only_oficial(self, fixture_objects):
        kept = []
        for obj in fixture_objects:
            model = obj.get("model")
            fields = obj.get("fields") or {}
            if model == "core.organograma":
                if fields.get("status") != "OFICIAL":
                    continue
            if model == "core.solicitacaoalteracao":
                if fields.get("status") in ("RASCUNHO", "DEVOLVIDO_CORRECAO"):
                    continue
            if model == "core.regimentocampus":
                nome = (fields.get("nome") or "").lower()
                if "test" in nome:
                    continue
            kept.append(obj)
        return kept

    # ------------------------------------------------------------------
    # Multi-pass loader
    # ------------------------------------------------------------------
    def _multipass_load(self, objects, label):
        if not objects:
            return 0, 0, 0, Counter()

        remaining = list(objects)
        total_loaded = 0
        total_errors = 0
        reasons = Counter()

        for pass_no in range(1, MAX_PASSES + 1):
            if not remaining:
                break
            still = []
            loaded_this = 0

            for obj_data in remaining:
                ok, reason = self._try_save_one(obj_data)
                if ok:
                    loaded_this += 1
                    total_loaded += 1
                else:
                    still.append(obj_data)
                    if reason:
                        reasons[reason] += 1

            if self.verbosity >= 2:
                self.stdout.write(
                    f"  [{label}] pass {pass_no}: loaded={loaded_this}, remaining={len(still)}"
                )

            if loaded_this == 0:
                # Last resort: null optional FKs more aggressively and retry once
                still2 = []
                for obj_data in still:
                    ok, reason = self._try_save_one(obj_data, aggressive_null=True)
                    if ok:
                        loaded_this += 1
                        total_loaded += 1
                    else:
                        still2.append(obj_data)
                        if reason:
                            reasons[f"final:{reason}"] += 1
                remaining = still2
                break

            remaining = still

        skipped = len(remaining)
        if remaining and self.verbosity >= 2:
            for obj_data in remaining[:10]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Unresolved {obj_data.get('model')} pk={obj_data.get('pk')}"
                    )
                )

        return total_loaded, skipped, total_errors, reasons

    def _try_save_one(self, obj_data, aggressive_null=False):
        """Attempt to deserialize+save one fixture object. Returns (ok, reason)."""
        model_name = (obj_data.get("model") or "").lower()
        try:
            app_label, model_code = model_name.split(".", 1)
            model = apps.get_model(app_label, model_code)
        except Exception:
            model = None

        # Skip if already present by PK (except lookup models we force-update)
        pk = obj_data.get("pk")
        if model is not None and pk is not None:
            try:
                if model.objects.filter(pk=pk).exists():
                    if model_name in LOOKUP_UPDATE_MODELS:
                        pass  # fall through: overwrite fields from fixture
                    elif model_name == "core.unit":
                        self._repair_existing_unit_fks(model, pk, obj_data)
                        return True, None
                    else:
                        return True, None
            except Exception:
                pass

        repaired = self._remap_fields(obj_data, aggressive_null=aggressive_null)
        payload = json.dumps([repaired], ensure_ascii=False)

        try:
            with transaction.atomic():
                for deserialized_obj in serializers.deserialize(
                    "json", StringIO(payload), ignorenonexistent=True
                ):
                    deserialized_obj.save()
            return True, None
        except (IntegrityError, ValidationError) as e:
            return False, f"{model_name}:{type(e).__name__}:{str(e)[:120]}"
        except Exception as e:
            # Deserialization errors (missing FK target mid-graph) etc.
            return False, f"{model_name}:{type(e).__name__}:{str(e)[:120]}"

    def _repair_existing_unit_fks(self, model, pk, obj_data):
        """If unit already exists, fix cargo/tipo via natural-key map from fixture."""
        fields = obj_data.get("fields") or {}
        updates = {}
        cargo_fix = fields.get("cargo_funcao_ref")
        tipo_fix = fields.get("tipo_unidade")
        if cargo_fix is not None and cargo_fix in self._cargo_pk_map:
            updates["cargo_funcao_ref_id"] = self._cargo_pk_map[cargo_fix]
        if tipo_fix is not None and tipo_fix in self._tipo_pk_map:
            updates["tipo_unidade_id"] = self._tipo_pk_map[tipo_fix]
        if updates:
            model.objects.filter(pk=pk).update(**updates)

    def _realign_unit_fks(self, fixture_objects):
        """Force unit cargo/tipo FKs to match fixture natural keys (post-import)."""
        from core.models import Unit

        # Refresh maps against current DB
        self._cargo_pk_map = self._build_cargo_map(fixture_objects)
        self._tipo_pk_map = self._build_tipo_map(fixture_objects)

        updated = 0
        for obj_data in fixture_objects:
            if (obj_data.get("model") or "").lower() != "core.unit":
                continue
            pk = obj_data.get("pk")
            if pk is None or not Unit.objects.filter(pk=pk).exists():
                continue
            fields = obj_data.get("fields") or {}
            updates = {}
            cargo_fix = fields.get("cargo_funcao_ref")
            tipo_fix = fields.get("tipo_unidade")
            if cargo_fix is not None and cargo_fix in self._cargo_pk_map:
                want = self._cargo_pk_map[cargo_fix]
                if Unit.objects.filter(pk=pk).exclude(cargo_funcao_ref_id=want).exists():
                    updates["cargo_funcao_ref_id"] = want
            elif cargo_fix is None:
                if Unit.objects.filter(pk=pk).exclude(cargo_funcao_ref_id=None).exists():
                    updates["cargo_funcao_ref_id"] = None
            if tipo_fix is not None and tipo_fix in self._tipo_pk_map:
                want = self._tipo_pk_map[tipo_fix]
                if Unit.objects.filter(pk=pk).exclude(tipo_unidade_id=want).exists():
                    updates["tipo_unidade_id"] = want
            elif tipo_fix is None:
                if Unit.objects.filter(pk=pk).exclude(tipo_unidade_id=None).exists():
                    updates["tipo_unidade_id"] = None
            if updates:
                Unit.objects.filter(pk=pk).update(**updates)
                updated += 1
        return updated

    def _print_integrity_report(self, fixture_objects):
        """Compare key model counts fixture vs DB after load. Returns problem count."""
        fix_counts = Counter((o.get("model") or "").lower() for o in fixture_objects)
        watch = [
            "core.campus",
            "core.organograma",
            "core.unit",
            "core.competenciaunidade",
            "core.regimentocampus",
            "core.resolucaoestruturaorganizacional",
        ]
        self.stdout.write("")
        self.stdout.write("Integrity check (fixture vs database):")
        problems = 0
        for label in watch:
            expected = fix_counts.get(label, 0)
            if expected == 0:
                # Empty on purpose (e.g. competências) — not a failure.
                continue
            try:
                app_label, model_code = label.split(".", 1)
                model = apps.get_model(app_label, model_code)
                actual = model.objects.count()
            except Exception:
                continue
            status = "OK" if actual >= expected else "SHORT"
            if actual < expected:
                problems += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  {label}: fixture={expected} db={actual}  ← incomplete"
                    )
                )
            else:
                extra = f" (+{actual - expected} extra)" if actual > expected else ""
                self.stdout.write(f"  {label}: fixture={expected} db={actual}{extra}  {status}")
        if problems:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{problems} model(s) below fixture count."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("  Core instance data matches the fixture."))
        return problems

    def _reset_postgres_sequences(self, fixture_objects):
        """Reset PK sequences after explicit-PK inserts (PostgreSQL only)."""
        if connection.vendor != "postgresql":
            return

        models = []
        seen = set()
        for obj in fixture_objects:
            label = (obj.get("model") or "").lower()
            if not label or label in seen:
                continue
            seen.add(label)
            try:
                app_label, model_code = label.split(".", 1)
                model = apps.get_model(app_label, model_code)
            except Exception:
                continue
            if model is not None:
                models.append(model)

        if not models:
            return

        style = no_style()
        sql_list = connection.ops.sequence_reset_sql(style, models)
        if not sql_list:
            return

        with connection.cursor() as cursor:
            for sql in sql_list:
                cursor.execute(sql)
        self.stdout.write(
            self.style.SUCCESS(
                f"PostgreSQL sequences reset for {len(sql_list)} statement(s)."
            )
        )

    def _verify_media_files(self, fixture_objects):
        """Warn if referenced media files are missing under MEDIA_ROOT."""
        media_root = Path(settings.MEDIA_ROOT) if settings.MEDIA_ROOT else None
        if not media_root:
            self.stdout.write(
                self.style.ERROR(
                    "MEDIA_ROOT is not configured — PDF links will return 404."
                )
            )
            return

        fields_by_model = {
            "core.regimentocampus": ["arquivo"],
            "core.resolucaoestruturaorganizacional": ["arquivo"],
            "core.organograma": [
                "documento_aprovacao",
                "regimento_arquivo",
                "regimento_geral_arquivo",
            ],
        }
        missing = []
        checked = 0
        for obj in fixture_objects:
            model = (obj.get("model") or "").lower()
            for field in fields_by_model.get(model, []):
                rel = (obj.get("fields") or {}).get(field)
                if not rel:
                    continue
                checked += 1
                path = media_root / rel
                if not path.exists():
                    missing.append(str(rel))

        if checked == 0:
            return
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    f"Media check: {len(missing)}/{checked} referenced file(s) missing under "
                    f"{media_root}. Example: {missing[0]}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Media check: all {checked} referenced PDF/file path(s) present under "
                    f"{media_root}."
                )
            )

    def _sync_cargo_quotas_from_officials(self):
        """
        Rebuild CD/FG quota tables from official organogramas.

        Fixture cotas use CargoFuncao PKs from the dump environment. After foundation
        load (load_consup44_modelos) those PKs often differ, producing cards like
        "CD-03: 4 / -" (used without registered limit). Syncing from the loaded
        OFICIAL trees restores used/limit balance on the list cards.
        """
        from django.core.management import call_command

        self.stdout.write("Sincronizando cotas de cargos a partir dos organogramas OFICIAIS...")
        try:
            call_command("sync_cargo_quotas", verbosity=self.verbosity)
            self.stdout.write(self.style.SUCCESS("Cotas de cargos sincronizadas."))
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(
                    f"Não foi possível sincronizar cotas automaticamente: {e}\n"
                    "Rode manualmente: python manage.py sync_cargo_quotas"
                )
            )

    def _remap_fields(self, obj_data, aggressive_null=False):
        """Return a copy of obj_data with FKs remapped / optionally nulled."""
        from django.apps import apps

        data = deepcopy(obj_data)
        model_name = data.get("model", "")
        fields = data.get("fields") or {}

        # Remap cargo / tipo FK fields (not free-text Unit.cargo_funcao CharField)
        for field_name, mapping in (
            ("cargo_funcao_ref", self._cargo_pk_map),
            ("tipo_unidade", self._tipo_pk_map),
        ):
            if field_name in fields and fields[field_name] is not None:
                fpk = fields[field_name]
                if fpk in mapping:
                    fields[field_name] = mapping[fpk]

        # Through / quota models use cargo_funcao as FK to CargoFuncao
        if model_name in (
            "core.modeloreferencialcotacargo",
            "core.campuscotacargo",
        ):
            cf = fields.get("cargo_funcao")
            if cf in self._cargo_pk_map:
                fields["cargo_funcao"] = self._cargo_pk_map[cf]

        # Null optional FKs that still don't exist (Unit tree helpers)
        model_l = (model_name or "").lower()
        if model_l in ("core.unit", "core.unitmodelo") or aggressive_null:
            self._null_missing_optional_fks(model_l, fields, aggressive_null)

        data["fields"] = fields
        return data

    def _null_missing_optional_fks(self, model_name, fields, aggressive_null):
        from core.models import (
            CargoFuncao,
            TipoUnidade,
            Unit,
            UnitModelo,
        )

        optional_checks = []
        if model_name == "core.unit":
            optional_checks = [
                ("cargo_funcao_ref", CargoFuncao),
                ("tipo_unidade", TipoUnidade),
                ("origem_modelo", UnitModelo),
                ("source_unit", Unit),
            ]
            if aggressive_null:
                optional_checks.append(("unidade_pai", Unit))
                # organograma is required — do not null
        elif model_name == "core.unitmodelo":
            optional_checks = [
                ("cargo_funcao_ref", CargoFuncao),
                ("tipo_unidade", TipoUnidade),
            ]
            if aggressive_null:
                optional_checks.append(("unidade_pai", UnitModelo))

        for field_name, model in optional_checks:
            fk = fields.get(field_name)
            if fk is not None and not model.objects.filter(pk=fk).exists():
                fields[field_name] = None

    def _copy_media_files(self):
        src = settings.BASE_DIR / "data" / "media"
        dst = Path(settings.MEDIA_ROOT)

        if not src.exists():
            self.stdout.write(
                self.style.WARNING("No data/media/ folder found — skipping PDF copy.")
            )
            return

        if not settings.MEDIA_ROOT:
            self.stdout.write(
                self.style.ERROR(
                    "MEDIA_ROOT is empty — PDFs would not be served. "
                    "Check config/settings (MEDIA_ROOT should point to var/media)."
                )
            )
            return

        dst.mkdir(parents=True, exist_ok=True)

        self.stdout.write(f"Copying media files (PDFs) from data/media/ to {dst}...")

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
                self.style.SUCCESS(
                    f"Copied {copied} media file(s) into MEDIA_ROOT ({dst})."
                )
            )
        else:
            self.stdout.write("No media files found to copy.")
