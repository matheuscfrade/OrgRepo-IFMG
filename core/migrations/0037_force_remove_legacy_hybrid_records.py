from django.db import migrations
from django.db.models import Q


def force_remove_legacy_hybrid_records(apps, schema_editor):
    TipoUnidade = apps.get_model('core', 'TipoUnidade')
    CargoFuncao = apps.get_model('core', 'CargoFuncao')
    Unit = apps.get_model('core', 'Unit')
    UnitModelo = apps.get_model('core', 'UnitModelo')

    legacy_tipos = list(
        TipoUnidade.objects.filter(
            Q(nome='Setor ou Seção') |
            Q(nome='Setor ou Secao') |
            Q(nome='Setor ou SeÃ§Ã£o')
        )
    )
    legacy_cargos = list(
        CargoFuncao.objects.filter(
            Q(sigla='FG-01 ou FG-02') |
            Q(sigla='FG-01 OU FG-02')
        )
    )

    if legacy_tipos:
        tipo_ids = [item.id for item in legacy_tipos]
        Unit.objects.filter(tipo_unidade_id__in=tipo_ids).update(tipo_unidade=None)
        UnitModelo.objects.filter(tipo_unidade_id__in=tipo_ids).update(tipo_unidade=None)
        TipoUnidade.objects.filter(id__in=tipo_ids).delete()

    if legacy_cargos:
        cargo_ids = [item.id for item in legacy_cargos]
        Unit.objects.filter(cargo_funcao_ref_id__in=cargo_ids).update(cargo_funcao_ref=None)
        UnitModelo.objects.filter(cargo_funcao_ref_id__in=cargo_ids).update(cargo_funcao_ref=None)
        CargoFuncao.objects.filter(id__in=cargo_ids).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0036_remove_legacy_hybrid_type_and_role'),
    ]

    operations = [
        migrations.RunPython(force_remove_legacy_hybrid_records, noop_reverse),
    ]
