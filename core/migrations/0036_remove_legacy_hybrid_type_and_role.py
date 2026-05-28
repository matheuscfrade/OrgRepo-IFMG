from django.db import migrations


def remove_legacy_hybrid_records(apps, schema_editor):
    TipoUnidade = apps.get_model('core', 'TipoUnidade')
    CargoFuncao = apps.get_model('core', 'CargoFuncao')
    Unit = apps.get_model('core', 'Unit')
    UnitModelo = apps.get_model('core', 'UnitModelo')

    legacy_tipos = list(TipoUnidade.objects.filter(nome__in=['Setor ou Seção', 'Setor ou Secao']))
    legacy_cargos = list(CargoFuncao.objects.filter(sigla__in=['FG-01 ou FG-02', 'FG-01 OU FG-02']))

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


def restore_legacy_hybrid_records(apps, schema_editor):
    TipoUnidade = apps.get_model('core', 'TipoUnidade')
    CargoFuncao = apps.get_model('core', 'CargoFuncao')

    CargoFuncao.objects.get_or_create(
        sigla='FG-01 ou FG-02',
        defaults={'nome': 'Chefe'},
    )
    TipoUnidade.objects.get_or_create(
        nome='Setor ou Seção',
        defaults={
            'apenas_modelo_referencial': True,
            'selecao_cargo_livre': False,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_unitmodelo_cargos_resolucao_permitidos_and_more'),
    ]

    operations = [
        migrations.RunPython(remove_legacy_hybrid_records, restore_legacy_hybrid_records),
    ]
