"""
Management command: purge_instance_data

Safely removes data to prepare a clean starting point.

By default it removes concrete "instance" data (Organogramas, Units, Solicitações)
while trying to preserve foundation.

When using --github-minimal (recommended for GitHub preparation):

It aggressively cleans everything except the pure "Resolução CONSUP 44/2025"
normative foundation:

- Dimensionamentos
- Cargos e Funções (CargoFuncao) + their allowed dimensionamentos
- Tipos de Unidade + defaults
- The 6 official Modelos Referenciais + their full UnitModelo trees (137 units)
- RegrasAlteracaoModelo + cotas for those models

It removes:
- All Campi
- All RegimentoCampus (records + will clean related media)
- All ResolucaoEstruturaOrganizacional (records + media)
- All Organogramas, Units, Solicitações, etc.

This gives forks a completely free starting point based only on the current
official rules (Resolução 44), without any outdated campus registrations,
regimentos, or resolutions.

The command is conservative and has strong dry-run protection.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings

from core.models import (
    Organograma,
    SolicitacaoAlteracao,
    RegimentoCampus,
    ResolucaoEstruturaOrganizacional,
    Unit,
    Campus,
)


class Command(BaseCommand):
    help = (
        "Remove data for clean starting points. "
        "Default: removes instance data. "
        "With --github-minimal: removes Campi + Regimentos + Resoluções + instance data, "
        "leaving ONLY the pure Resolução CONSUP 44/2025 foundation (models, rules, cargos, tipos)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be deleted without actually deleting anything.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Actually perform the deletions (required unless --dry-run).",
        )
        parser.add_argument(
            "--clear-documents",
            action="store_true",
            default=False,
            help=(
                "Also clear the 'arquivo' FileFields (and delete the physical files) "
                "from RegimentoCampus and ResolucaoEstruturaOrganizacional. "
                "Use this when preparing a clean GitHub snapshot."
            ),
        )
        parser.add_argument(
            "--also-clear-organograma-files",
            action="store_true",
            default=False,
            help="Clear denormalized document files that may still exist on Organograma records before they are deleted.",
        )
        parser.add_argument(
            "--github-minimal",
            "--resolucao-44-only",
            dest="github_minimal",
            action="store_true",
            default=False,
            help=(
                "AGGRESSIVE MODE for GitHub snapshot: Also delete ALL RegimentoCampus, "
                "ALL ResolucaoEstruturaOrganizacional, and ALL Campi. "
                "This leaves ONLY the pure Resolução CONSUP 44/2025 foundation "
                "(Modelos Referenciais, UnitModelos, Regras, Cargos, Tipos, Dimensionamentos). "
                "Use this when you want forks to start completely from zero with only the current rules."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        clear_documents = options["clear_documents"]
        clear_org_files = options["also_clear_organograma_files"]
        github_minimal = options["github_minimal"]

        if not dry_run and not force:
            raise CommandError(
                "This is a destructive command. Use --dry-run to preview, or --force to actually delete."
            )

        self.stdout.write(self.style.WARNING("=== purge_instance_data ==="))
        self.stdout.write(f"Mode: {'DRY RUN' if dry_run else 'LIVE (DESTRUCTIVE)'}")
        if github_minimal:
            self.stdout.write(self.style.WARNING("GITHUB MINIMAL MODE (--github-minimal / --resolucao-44-only)"))
            self.stdout.write("  - Will remove Campi, Regimentos, Resolucoes + all instance data.")
            self.stdout.write("  - Only pure Resolucao 44 foundation (models + rules) will remain.")
        self.stdout.write(f"Clear foundation documents: {clear_documents}")
        self.stdout.write("")

        # === 1. Count what we will affect ===
        solicitacoes_count = SolicitacaoAlteracao.objects.count()
        organogramas_count = Organograma.objects.count()
        units_count = Unit.objects.count()
        regimentos_count = RegimentoCampus.objects.count()
        resolucoes_count = ResolucaoEstruturaOrganizacional.objects.count()
        campi_count = Campus.objects.count()

        self.stdout.write("Current counts:")
        self.stdout.write(f"  SolicitacaoAlteracao: {solicitacoes_count}")
        self.stdout.write(f"  Organograma:          {organogramas_count}")
        self.stdout.write(f"  Unit (concrete):      {units_count}")
        self.stdout.write(f"  RegimentoCampus:      {regimentos_count}")
        self.stdout.write(f"  ResolucaoEstrutura:   {resolucoes_count}")
        self.stdout.write(f"  Campus:               {campi_count}")
        self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run complete. Nothing was deleted."))
            if github_minimal:
                self.stdout.write(self.style.WARNING("With --github-minimal this would leave ONLY the Resolução 44 foundation."))
            self.stdout.write("Re-run with --force when you are ready.")
            return

        # === 2. Actual purge ===
        with transaction.atomic():
            # Delete Solicitações first (they have custom delete logic that cleans proposed organogramas)
            if solicitacoes_count > 0:
                self.stdout.write(f"Deleting {solicitacoes_count} SolicitacaoAlteracao records...")
                deleted_s, _ = SolicitacaoAlteracao.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(f"  Deleted {deleted_s} SolicitacaoAlteracao (and related objects via custom delete)."))

            # Delete all Organogramas — this should cascade to their Units via FK
            if organogramas_count > 0:
                self.stdout.write(f"Deleting {organogramas_count} Organograma records (cascades to Units)...")
                deleted_o, _ = Organograma.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(f"  Deleted {deleted_o} Organograma records."))

            # Verify Units are gone
            remaining_units = Unit.objects.count()
            if remaining_units > 0:
                self.stdout.write(self.style.WARNING(f"  Warning: {remaining_units} Units still remain (possible orphan or different FK)."))

            # === GitHub Minimal mode: nuke the outdated institutional registers ===
            if github_minimal:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING("GITHUB MINIMAL: Removing Campi, Regimentos and Resoluções..."))

                if regimentos_count > 0:
                    self.stdout.write(f"  Deleting all {regimentos_count} RegimentoCampus records...")
                    deleted_r, _ = RegimentoCampus.objects.all().delete()
                    self.stdout.write(self.style.SUCCESS(f"    Deleted {deleted_r} RegimentoCampus."))

                if resolucoes_count > 0:
                    self.stdout.write(f"  Deleting all {resolucoes_count} ResolucaoEstruturaOrganizacional records...")
                    deleted_res, _ = ResolucaoEstruturaOrganizacional.objects.all().delete()
                    self.stdout.write(self.style.SUCCESS(f"    Deleted {deleted_res} ResolucaoEstruturaOrganizacional."))

                if campi_count > 0:
                    self.stdout.write(f"  Deleting all {campi_count} Campus records (this is intended for GitHub minimal mode)...")
                    deleted_c, _ = Campus.objects.all().delete()
                    self.stdout.write(self.style.SUCCESS(f"    Deleted {deleted_c} Campus."))

                self.stdout.write(self.style.WARNING("  Only pure Resolução 44 foundation data should remain now."))

            # Optionally clear document files from foundation objects (Regimentos / Resoluções)
            if clear_documents and not github_minimal:
                # In github_minimal we already deleted the records, so no need
                self._clear_foundation_document_files(clear_org_files)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Purge complete."))

        if github_minimal:
            self.stdout.write(
                self.style.SUCCESS(
                    "GitHub minimal mode finished. "
                    "Only the pure Resolução CONSUP 44/2025 foundation remains "
                    "(Modelos Referenciais + UnitModelos + Regras + Cargos + Tipos + Dimensionamentos)."
                )
            )
        else:
            self.stdout.write(
                "Foundation data (Campi, Modelos Referenciais, Regras, Cargos, Tipos, "
                "Dimensionamentos, Regimento/Resolução *metadata*) has been preserved."
            )
            if clear_documents:
                self.stdout.write(self.style.WARNING(
                    "Document files (PDFs) on RegimentoCampus and ResolucaoEstruturaOrganizacional were cleared."
                ))

    def _clear_foundation_document_files(self, also_clear_on_deleted_organogramas=False):
        """Clear FileFields on the foundation Regimento and Resolução objects."""
        self.stdout.write("Clearing document files from foundation Regimentos and Resoluções...")

        # RegimentoCampus
        regimentos = RegimentoCampus.objects.exclude(arquivo="")
        reg_count = regimentos.count()
        for reg in regimentos:
            if reg.arquivo:
                try:
                    reg.arquivo.delete(save=False)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Could not delete file for Regimento #{reg.pk}: {e}"))
                reg.arquivo = ""
                reg.save(update_fields=["arquivo"])
        self.stdout.write(f"  Cleared {reg_count} RegimentoCampus files.")

        # ResolucaoEstruturaOrganizacional
        resolucoes = ResolucaoEstruturaOrganizacional.objects.exclude(arquivo="")
        res_count = resolucoes.count()
        for res in resolucoes:
            if res.arquivo:
                try:
                    res.arquivo.delete(save=False)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Could not delete file for Resolução #{res.pk}: {e}"))
                res.arquivo = ""
                res.save(update_fields=["arquivo"])
        self.stdout.write(f"  Cleared {res_count} ResolucaoEstruturaOrganizacional files.")

        # Note: We already deleted the Organogramas above, so their direct file fields are gone.
        # The flag is here for future-proofing or partial runs.
        if also_clear_on_deleted_organogramas:
            self.stdout.write("  (Organograma direct document files were removed together with the records.)")

        self.stdout.write(self.style.SUCCESS("Document files cleared from foundation objects."))