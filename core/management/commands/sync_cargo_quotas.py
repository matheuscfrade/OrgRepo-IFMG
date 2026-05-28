from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    CampusCotaCargo,
    CargoFuncao,
    ModeloReferencialCotaCargo,
    Organograma,
)
from core.services.cargo_quotas import is_cd_fg_sigla, normalize_cargo_sigla


def count_cd_fg_units(organograma):
    counts = defaultdict(int)
    units = organograma.unidades.filter(is_agrupamento=False).select_related('cargo_funcao_ref')
    for unit in units:
        sigla = unit.cargo_funcao_ref.sigla if unit.cargo_funcao_ref_id else (unit.sigla_cargo or unit.cargo_funcao or '')
        if is_cd_fg_sigla(sigla):
            counts[normalize_cargo_sigla(sigla)] += 1
    return dict(sorted(counts.items()))


def cargo_by_normalized_sigla():
    result = {}
    for cargo in CargoFuncao.objects.all().order_by('sigla', 'id'):
        if is_cd_fg_sigla(cargo.sigla):
            result.setdefault(normalize_cargo_sigla(cargo.sigla), cargo)
    return result


def sync_quota_rows(model, parent_field, parent, counts, cargos, dry_run=False):
    manager = getattr(parent, 'cotas_cargos')
    existing = list(manager.select_related('cargo_funcao'))
    changed = []

    for quota in existing:
        if not is_cd_fg_sigla(quota.cargo_funcao.sigla):
            continue
        key = normalize_cargo_sigla(quota.cargo_funcao.sigla)
        if key not in counts:
            changed.append(f"remover {quota.cargo_funcao.sigla}")
            if not dry_run:
                quota.delete()

    for key, quantidade in counts.items():
        cargo = cargos.get(key)
        if not cargo:
            changed.append(f"ignorar {key} sem cadastro de CargoFuncao")
            continue
        defaults = {'quantidade': quantidade}
        lookup = {parent_field: parent, 'cargo_funcao': cargo}
        quota = model.objects.filter(**lookup).first()
        if quota:
            if quota.quantidade != quantidade:
                changed.append(f"{cargo.sigla}: {quota.quantidade} -> {quantidade}")
                if not dry_run:
                    quota.quantidade = quantidade
                    quota.save(update_fields=['quantidade'])
        else:
            changed.append(f"criar {cargo.sigla}: {quantidade}")
            if not dry_run:
                model.objects.create(**lookup, **defaults)

    return changed


class Command(BaseCommand):
    help = "Sincroniza cotas de Cargos/Funcoes a partir dos organogramas oficiais existentes."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Mostra as alteracoes sem grava-las.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        cargos = cargo_by_normalized_sigla()
        organogramas = (
            Organograma.objects
            .filter(status='OFICIAL')
            .select_related('campus', 'campus__dimensionamento_fk', 'campus__modelo_referencial_padrao', 'modelo_base')
            .order_by('campus__dimensionamento_fk__chave', 'campus__sigla')
        )

        modelo_groups = defaultdict(list)
        reitoria = []
        for organograma in organogramas:
            counts = count_cd_fg_units(organograma)
            if organograma.campus.sigla == 'IFMG':
                reitoria.append((organograma, counts))
                continue
            modelo = organograma.modelo_referencial_efetivo
            if not modelo:
                self.stdout.write(self.style.WARNING(f"{organograma.campus.sigla}: sem modelo referencial efetivo; ignorado."))
                continue
            key = (organograma.campus.dimensionamento_chave, modelo.id)
            modelo_groups[key].append((organograma, modelo, counts))

        with transaction.atomic():
            for rows in modelo_groups.values():
                sample_org, modelo, sample_counts = rows[0]
                unique_counts = {tuple(counts.items()) for _, _, counts in rows}
                siglas = ', '.join(org.campus.sigla for org, _, _ in rows)
                if len(unique_counts) != 1:
                    self.stdout.write(self.style.WARNING(
                        f"{sample_org.campus.dimensionamento_chave}: divergencia entre {siglas}; cotas do modelo {modelo.id} nao alteradas."
                    ))
                    continue

                changes = sync_quota_rows(
                    ModeloReferencialCotaCargo,
                    'modelo_referencial',
                    modelo,
                    sample_counts,
                    cargos,
                    dry_run=dry_run,
                )
                status = "sem alteracoes" if not changes else "; ".join(changes)
                self.stdout.write(f"{sample_org.campus.dimensionamento_chave} ({siglas}) -> {modelo.nome}: {status}")

            for organograma, counts in reitoria:
                changes = sync_quota_rows(
                    CampusCotaCargo,
                    'campus',
                    organograma.campus,
                    counts,
                    cargos,
                    dry_run=dry_run,
                )
                status = "sem alteracoes" if not changes else "; ".join(changes)
                self.stdout.write(f"REITORIA ({organograma.campus.sigla}) -> {status}")

            if dry_run:
                transaction.set_rollback(True)
