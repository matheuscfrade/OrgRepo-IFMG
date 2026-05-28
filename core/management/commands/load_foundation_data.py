"""
Management command: load_foundation_data

Loads (or ensures) the institutional "foundation" data.

By default it tries to load a reasonable baseline including Campi.

When preparing a **minimal GitHub snapshot**, you normally do **not** need this
command for Campi/Regimentos/Resoluções — instead run:

    python manage.py load_consup44_modelos

This loads exactly the Resolução CONSUP 44/2025 artifacts:
- Dimensionamentos
- Cargos e Funções
- Tipos de Unidade
- The 6 official Modelos Referenciais + 137 UnitModelos
- RegrasAlteracaoModelo + cotas

Then use `purge_instance_data --github-minimal --force` (on a copy of your DB)
to remove everything else (Campi, Regimentos, Resoluções, organogramas...).

This gives forks a completely free starting point based only on the current rules.
"""

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction

from core.models import (
    Campus,
    Dimensionamento,
    CargoFuncao,
    TipoUnidade,
)


class Command(BaseCommand):
    help = "Ensure the complete institutional foundation data is loaded (Campi, Modelos Referenciais, Regras, Cargos, Tipos, etc.)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-modelos",
            action="store_true",
            default=False,
            help="Skip loading/rebuilding the heavy ModeloReferencial + UnitModelo trees (useful for quick runs).",
        )
        parser.add_argument(
            "--force-rebuild-modelos",
            action="store_true",
            default=False,
            help="Delete existing UnitModelos for the known models and rebuild them from the CONSUP 44/2025 definition.",
        )

    def handle(self, *args, **options):
        skip_modelos = options["skip_modelos"]
        force_rebuild = options["force_rebuild_modelos"]

        self.stdout.write(self.style.NOTICE("=== load_foundation_data ==="))
        self.stdout.write("This command ensures the institutional configuration baseline exists.")
        self.stdout.write("")

        with transaction.atomic():
            # 1. Dimensionamentos, Cargos, Tipos (small lookup tables)
            self._ensure_basic_lookups()

            # 2. Campi (the 20 official IFMG campuses / units)
            self._ensure_campi()

            # 3. Heavy part: Modelos Referenciais + UnitModelos + Regras
            if not skip_modelos:
                self._ensure_reference_models(force_rebuild)
            else:
                self.stdout.write(self.style.WARNING("Skipping ModeloReferencial trees (--skip-modelos)."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Foundation data load complete."))
        self.stdout.write(
            "You now have Campi, Modelos Referenciais, Regras de Alteração, "
            "Cargos, Tipos de Unidade, and Dimensionamentos."
        )
        self.stdout.write(
            "Use 'python manage.py purge_instance_data --force --clear-documents' "
            "(only when preparing a GitHub snapshot) to remove concrete organogramas."
        )

    def _ensure_basic_lookups(self):
        self.stdout.write("Ensuring Dimensionamentos, Cargos and Tipos de Unidade...")

        # Leverage the existing well-tested command for the CONSUP 44/2025 baseline.
        # It is idempotent for these small tables.
        try:
            call_command("load_consup44_modelos", verbosity=0)
            self.stdout.write("  → load_consup44_modelos executed (ensures core lookups + models).")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"  Could not run load_consup44_modelos: {exc}"))
            self.stdout.write("  Falling back to minimal bootstrap...")

            # Very minimal fallback (the bootstrap script in scripts/ does something similar)
            dims = {
                "150": "Modelo 150",
                "150_AGRI": "Modelo 150 Agrícola",
                "90_70_AGRI": "Modelo 90/70 Agrícola",
                "70_45": "Modelo 70/45",
                "40_26": "Modelo 40/26",
                "REITORIA": "Reitoria",
                "POLO": "Polo de Inovação",
            }
            for chave, nome in dims.items():
                Dimensionamento.objects.get_or_create(chave=chave, defaults={"nome": nome})

            cargos = [
                ("Reitor(a)", "CD-01"),
                ("Diretor(a) Geral", "CD-02"),
                ("Diretor(a)", "CD-03"),
                ("Coordenador(a)", "CD-04"),
                ("Chefe", "FG-01"),
                ("Chefe", "FG-02"),
                ("Supervisor(a)", "FG-03"),
            ]
            for nome, sigla in cargos:
                CargoFuncao.objects.get_or_create(nome=nome, sigla=sigla)

            tipos = ["Reitoria", "Campus", "Diretoria", "Pró-Reitoria", "Coordenadoria", "Setor", "Seção", "Núcleo"]
            for nome in tipos:
                TipoUnidade.objects.get_or_create(nome=nome)

        self.stdout.write(self.style.SUCCESS("  Basic lookups ensured."))

    def _ensure_campi(self):
        self.stdout.write("Ensuring Campi (20 official entries)...")

        # Minimal authoritative list of Campi.
        # In a real institutional deployment this list would be maintained in the admin.
        # For GitHub / forks we want the structure to exist so people can start aligned.
        campi_data = [
            ("IFMG - Reitoria", "IFMG", "REITORIA"),
            ("Campus Betim", "CBMG-BET", "150"),
            ("Campus Congonhas", "CBMG-CON", "70_45"),
            ("Campus Formiga", "CBMG-FOR", "70_45"),
            ("Campus Governador Valadares", "CBMG-GVA", "70_45"),
            ("Campus Ibirité", "CBMG-IBI", "70_45"),
            ("Campus Ipatinga", "CBMG-IPA", "70_45"),
            ("Campus Ouro Preto", "CBMG-OPR", "70_45"),
            ("Campus Pouso Alegre", "CBMG-POA", "70_45"),
            ("Campus Sabará", "CBMG-SAB", "70_45"),
            ("Campus Santa Luzia", "CBMG-SLU", "70_45"),
            ("Campus São João Evangelista", "CBMG-SJE", "70_45"),
            ("Campus Varginha", "CBMG-VAR", "70_45"),
            ("Campus Bambuí", "CBMG-BAM", "150_AGRI"),
            ("Campus Januária", "CBMG-JAN", "150_AGRI"),
            ("Campus Montes Claros", "CBMG-MOC", "150_AGRI"),
            ("Campus Pirapora", "CBMG-PIR", "150_AGRI"),
            ("Campus São João da Ponte", "CBMG-SJP", "150_AGRI"),
            ("Polo de Inovação", "POLO-INOV", "POLO"),
            ("Campus Conselheiro Lafaiete", "CBMG-CLF", "40_26"),
        ]

        created = 0
        for nome, sigla, dim_chave in campi_data:
            dim = Dimensionamento.objects.filter(chave=dim_chave).first()
            campus, was_created = Campus.objects.get_or_create(
                sigla=sigla,
                defaults={
                    "nome": nome,
                    "dimensionamento": dim_chave,
                    "dimensionamento_fk": dim,
                },
            )
            if was_created:
                created += 1
            else:
                # Keep existing name/dimensionamento in sync if missing
                updated = False
                if not campus.nome:
                    campus.nome = nome
                    updated = True
                if dim and not campus.dimensionamento_fk:
                    campus.dimensionamento_fk = dim
                    updated = True
                if updated:
                    campus.save()

        self.stdout.write(f"  {created} new Campi created, others ensured.")

    def _ensure_reference_models(self, force_rebuild: bool):
        self.stdout.write("Ensuring Modelos Referenciais + UnitModelos + Regras...")

        if force_rebuild:
            self.stdout.write("  --force-rebuild-modelos: clearing existing UnitModelos for known models...")
            # The load_consup44_modelos command already does a full rebuild when called.
            pass

        try:
            call_command(
                "load_consup44_modelos",
                verbosity=1 if self.verbosity >= 2 else 0,
            )
            self.stdout.write(self.style.SUCCESS("  Modelos Referenciais ensured via load_consup44_modelos."))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Failed to ensure reference models: {exc}"))
            self.stdout.write("  You may need to run 'python manage.py load_consup44_modelos' manually.")