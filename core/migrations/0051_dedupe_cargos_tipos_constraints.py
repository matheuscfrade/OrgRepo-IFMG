import re
import unicodedata
from collections import defaultdict

from django.db import migrations, models


def normalize_key(value):
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', value).strip().casefold()


def has_accent(value):
    return any(unicodedata.combining(char) for char in unicodedata.normalize('NFKD', value or ''))


def merge_cargo_dimensionamentos(keeper, duplicate):
    keeper.dimensionamentos_permitidos.add(*duplicate.dimensionamentos_permitidos.all())


def merge_tipo_dimensionamentos(keeper, duplicate):
    keeper.dimensionamentos_permitidos.add(*duplicate.dimensionamentos_permitidos.all())


def merge_modelo_quota(ModeloReferencialCotaCargo, keeper_id, duplicate_id):
    duplicate_quotas = list(ModeloReferencialCotaCargo.objects.filter(cargo_funcao_id=duplicate_id))
    for duplicate_quota in duplicate_quotas:
        keeper_quota = ModeloReferencialCotaCargo.objects.filter(
            modelo_referencial_id=duplicate_quota.modelo_referencial_id,
            cargo_funcao_id=keeper_id,
        ).first()
        if keeper_quota:
            keeper_quota.quantidade = max(keeper_quota.quantidade, duplicate_quota.quantidade)
            keeper_quota.save(update_fields=['quantidade'])
            duplicate_quota.delete()
        else:
            duplicate_quota.cargo_funcao_id = keeper_id
            duplicate_quota.save(update_fields=['cargo_funcao'])


def merge_campus_quota(CampusCotaCargo, keeper_id, duplicate_id):
    duplicate_quotas = list(CampusCotaCargo.objects.filter(cargo_funcao_id=duplicate_id))
    for duplicate_quota in duplicate_quotas:
        keeper_quota = CampusCotaCargo.objects.filter(
            campus_id=duplicate_quota.campus_id,
            cargo_funcao_id=keeper_id,
        ).first()
        if keeper_quota:
            keeper_quota.quantidade = max(keeper_quota.quantidade, duplicate_quota.quantidade)
            keeper_quota.save(update_fields=['quantidade'])
            duplicate_quota.delete()
        else:
            duplicate_quota.cargo_funcao_id = keeper_id
            duplicate_quota.save(update_fields=['cargo_funcao'])


def add_unique_m2m_link(through_model, source_field, target_field, source_id, keeper_id):
    link, _ = through_model.objects.get_or_create(**{
        source_field: source_id,
        target_field: keeper_id,
    })
    return link


def merge_duplicate_cadastros(apps, schema_editor):
    CargoFuncao = apps.get_model('core', 'CargoFuncao')
    TipoUnidade = apps.get_model('core', 'TipoUnidade')
    Unit = apps.get_model('core', 'Unit')
    UnitModelo = apps.get_model('core', 'UnitModelo')
    ModeloReferencialCotaCargo = apps.get_model('core', 'ModeloReferencialCotaCargo')
    CampusCotaCargo = apps.get_model('core', 'CampusCotaCargo')

    cargo_groups = defaultdict(list)
    for cargo in CargoFuncao.objects.all().order_by('id'):
        cargo_groups[(normalize_key(cargo.nome), normalize_key(cargo.sigla))].append(cargo)

    cargo_resolution_m2m = UnitModelo.cargos_resolucao_permitidos.through
    for cargos in cargo_groups.values():
        if len(cargos) < 2:
            continue
        keeper = sorted(cargos, key=lambda item: item.id)[0]
        for duplicate in sorted(cargos, key=lambda item: item.id)[1:]:
            merge_cargo_dimensionamentos(keeper, duplicate)
            TipoUnidade.objects.filter(cargo_padrao_id=duplicate.id).update(cargo_padrao_id=keeper.id)
            Unit.objects.filter(cargo_funcao_ref_id=duplicate.id).update(cargo_funcao_ref_id=keeper.id)
            UnitModelo.objects.filter(cargo_funcao_ref_id=duplicate.id).update(cargo_funcao_ref_id=keeper.id)

            for link in list(cargo_resolution_m2m.objects.filter(cargofuncao_id=duplicate.id)):
                add_unique_m2m_link(cargo_resolution_m2m, 'unitmodelo_id', 'cargofuncao_id', link.unitmodelo_id, keeper.id)
                link.delete()

            merge_modelo_quota(ModeloReferencialCotaCargo, keeper.id, duplicate.id)
            merge_campus_quota(CampusCotaCargo, keeper.id, duplicate.id)
            duplicate.delete()

    tipo_groups = defaultdict(list)
    for tipo in TipoUnidade.objects.all().order_by('id'):
        tipo_groups[normalize_key(tipo.nome)].append(tipo)

    tipo_resolution_m2m = UnitModelo.tipos_resolucao_permitidos.through
    for tipos in tipo_groups.values():
        if len(tipos) < 2:
            continue
        keeper = sorted(tipos, key=lambda item: (not has_accent(item.nome), item.id))[0]
        for duplicate in sorted([item for item in tipos if item.id != keeper.id], key=lambda item: item.id):
            merge_tipo_dimensionamentos(keeper, duplicate)
            Unit.objects.filter(tipo_unidade_id=duplicate.id).update(tipo_unidade_id=keeper.id)
            UnitModelo.objects.filter(tipo_unidade_id=duplicate.id).update(tipo_unidade_id=keeper.id)

            for link in list(tipo_resolution_m2m.objects.filter(tipounidade_id=duplicate.id)):
                add_unique_m2m_link(tipo_resolution_m2m, 'unitmodelo_id', 'tipounidade_id', link.unitmodelo_id, keeper.id)
                link.delete()

            duplicate.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0050_cargo_quotas'),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_cadastros, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='cargofuncao',
            constraint=models.UniqueConstraint(fields=('nome', 'sigla'), name='unique_cargo_funcao_nome_sigla'),
        ),
        migrations.AddConstraint(
            model_name='tipounidade',
            constraint=models.UniqueConstraint(fields=('nome',), name='unique_tipo_unidade_nome'),
        ),
    ]
