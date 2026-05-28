"""
Management command: clean_db

Aggressively cleans the current database by removing test/draft data.

This is intended to be run on the source checkout (OrgRepo) before generating
a clean data/full_data.json for distribution.

It removes:
- Test/dummy Campi (names containing test/demo/dummy/etc.)
- All non-OFICIAL organogramas
- Non-vigente regimentos
- Regimentos with "test" in the name
- Units and Solicitações linked to removed data
- Draft/test Solicitações

Usage:
    python manage.py clean_db --dry-run     # See what would be deleted
    python manage.py clean_db --force       # Actually delete
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Campus, Organograma, RegimentoCampus, Unit, SolicitacaoAlteracao


class Command(BaseCommand):
    help = (
        "Aggressively clean the current database (remove test Campi, non-OFICIAL organogramas, "
        "non-vigente regimentos, test regimentos, etc.) before generating clean full_data.json"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Actually perform the deletions (without this it runs in dry-run mode)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run" or not options["force"]]

        if dry_run:
            self.stdout.write(self.style.WARNING("=== DRY RUN MODE - No changes will be made ==="))

        self.stdout.write("Analyzing database for test / non-official data...\n")

        # 1. Find test Campi
        test_patterns = ["test", "teste", "demo", "dummy", "exemplo", "sample"]
        test_campi = Campus.objects.filter(
            nome__iregex=r"test|demo|dummy|exemplo|sample"
        ) | Campus.objects.filter(
            sigla__iregex=r"test|demo|dummy|exemplo|sample"
        )
        test_campus_ids = list(test_campi.values_list("id", flat=True))

        self.stdout.write(f"Test/Dummy Campi found: {len(test_campus_ids)}")
        for c in test_campi:
            self.stdout.write(f"  - {c.nome} ({c.sigla})")

        # 2. Find non-OFICIAL organogramas
        non_oficial_orgs = Organograma.objects.exclude(status="OFICIAL")
        non_oficial_org_ids = list(non_oficial_orgs.values_list("id", flat=True))

        self.stdout.write(f"\nNon-OFICIAL Organogramas: {len(non_oficial_org_ids)}")
        for o in non_oficial_orgs[:10]:
            self.stdout.write(f"  - {o.campus.sigla} | {o.status}")

        # 3. Find bad regimentos (non-vigente or test name)
        bad_regimentos = RegimentoCampus.objects.filter(vigente=False) | \
                         RegimentoCampus.objects.filter(nome__icontains="test")
        bad_regimento_ids = list(bad_regimentos.values_list("id", flat=True))

        self.stdout.write(f"\nBad Regimentos (non-vigente or test name): {len(bad_regimento_ids)}")

        # 4. Find Units belonging to bad organogramas
        bad_units = Unit.objects.filter(organograma_id__in=non_oficial_org_ids)
        self.stdout.write(f"\nUnits to remove (linked to non-OFICIAL organogramas): {bad_units.count()}")

        # 5. Find bad Solicitações
        bad_solicitacoes = SolicitacaoAlteracao.objects.filter(
            status__in=["RASCUNHO", "DEVOLVIDO_CORRECAO"]
        ) | SolicitacaoAlteracao.objects.filter(
            organograma_original_id__in=non_oficial_org_ids
        ) | SolicitacaoAlteracao.objects.filter(
            organograma_proposto_id__in=non_oficial_org_ids
        )
        self.stdout.write(f"Solicitações to remove (drafts or linked to bad organogramas): {bad_solicitacoes.count()}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run complete. No data was deleted."))
            self.stdout.write("Run with --force to actually clean the database.")
            return

        # Actual deletion
        self.stdout.write(self.style.WARNING("\n=== PERFORMING DELETIONS ==="))

        with transaction.atomic():
            # Delete in safe order
            deleted_solic = bad_solicitacoes.delete()[0]
            self.stdout.write(f"Deleted Solicitações: {deleted_solic}")

            deleted_units = bad_units.delete()[0]
            self.stdout.write(f"Deleted Units: {deleted_units}")

            deleted_reg = bad_regimentos.delete()[0]
            self.stdout.write(f"Deleted Regimentos: {deleted_reg}")

            deleted_orgs = non_oficial_orgs.delete()[0]
            self.stdout.write(f"Deleted Organogramas: {deleted_orgs}")

            deleted_campi = test_campi.delete()[0]
            self.stdout.write(f"Deleted Campi: {deleted_campi}")

        self.stdout.write(self.style.SUCCESS("\nDatabase cleaning completed successfully!"))

        self.stdout.write("\nNext step: Generate a clean fixture with:")
        self.stdout.write("  python manage.py dump_full_data --output data/full_data.json")
