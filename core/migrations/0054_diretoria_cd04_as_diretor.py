"""
Campi 40/26 e 70/45: Diretoria ocupa CD-04 como Diretor(a), não Coordenador(a).

Creates CargoFuncao Diretor(a)/CD-04 if missing, rewires UnitModelo and Unit
for those dimensionamentos, and updates TipoUnidade.Diretoria allowed cargos.
"""

from django.db import migrations


DIMS = ('40_26', '70_45')


def forwards(apps, schema_editor):
    CargoFuncao = apps.get_model('core', 'CargoFuncao')
    TipoUnidade = apps.get_model('core', 'TipoUnidade')
    Dimensionamento = apps.get_model('core', 'Dimensionamento')
    Unit = apps.get_model('core', 'Unit')
    UnitModelo = apps.get_model('core', 'UnitModelo')
    ModeloReferencial = apps.get_model('core', 'ModeloReferencial')

    coord_cd04 = CargoFuncao.objects.filter(sigla='CD-04', nome='Coordenador(a)').order_by('id').first()
    if not coord_cd04:
        coord_cd04 = CargoFuncao.objects.filter(sigla='CD-04').order_by('id').first()

    diretor_cd04 = CargoFuncao.objects.filter(sigla='CD-04', nome='Diretor(a)').order_by('id').first()
    if not diretor_cd04:
        diretor_cd04 = CargoFuncao.objects.create(sigla='CD-04', nome='Diretor(a)')

    # Copy dimension permissions from Coordenador CD-04 when present
    if coord_cd04:
        dim_ids = list(coord_cd04.dimensionamentos_permitidos.values_list('id', flat=True))
        if dim_ids:
            diretor_cd04.dimensionamentos_permitidos.add(*dim_ids)
    else:
        all_dims = list(Dimensionamento.objects.values_list('id', flat=True))
        if all_dims:
            diretor_cd04.dimensionamentos_permitidos.add(*all_dims)

    cd03 = CargoFuncao.objects.filter(sigla='CD-03').order_by('id').first()
    diretoria = TipoUnidade.objects.filter(nome='Diretoria').order_by('id').first()
    if diretoria:
        if cd03 and not diretoria.cargo_padrao_id:
            diretoria.cargo_padrao_id = cd03.id
            diretoria.save(update_fields=['cargo_padrao_id'])
        permitidos = [c for c in (cd03, diretor_cd04) if c is not None]
        if permitidos:
            diretoria.cargos_ocupantes_permitidos.set(permitidos)

    dim_ids = list(Dimensionamento.objects.filter(chave__in=DIMS).values_list('id', flat=True))
    if not dim_ids:
        return

    # UnitModelo under 40/26 and 70/45 models: Diretoria + CD-04 → Diretor(a) CD-04
    modelos = ModeloReferencial.objects.filter(dimensionamento_id__in=dim_ids)
    UnitModelo.objects.filter(
        modelo__in=modelos,
        tipo_unidade__nome='Diretoria',
        cargo_funcao_ref__sigla='CD-04',
    ).exclude(cargo_funcao_ref=diretor_cd04).update(
        cargo_funcao_ref=diretor_cd04,
        sigla_cargo='CD-04',
    )

    # Also by cargo name Coordenador if tipo missing
    if coord_cd04:
        UnitModelo.objects.filter(
            modelo__in=modelos,
            tipo_unidade__nome='Diretoria',
            cargo_funcao_ref=coord_cd04,
        ).update(cargo_funcao_ref=diretor_cd04, sigla_cargo='CD-04')

    # Live organogram units on those campi
    Unit.objects.filter(
        organograma__campus__dimensionamento_fk_id__in=dim_ids,
        tipo_unidade__nome='Diretoria',
        cargo_funcao_ref__sigla='CD-04',
    ).exclude(cargo_funcao_ref=diretor_cd04).update(
        cargo_funcao_ref=diretor_cd04,
        sigla_cargo='CD-04',
    )
    if coord_cd04:
        Unit.objects.filter(
            organograma__campus__dimensionamento_fk_id__in=dim_ids,
            tipo_unidade__nome='Diretoria',
            cargo_funcao_ref=coord_cd04,
        ).update(cargo_funcao_ref=diretor_cd04, sigla_cargo='CD-04')

    # Fallback: campus.dimensionamento legacy char field
    Unit.objects.filter(
        organograma__campus__dimensionamento__in=DIMS,
        tipo_unidade__nome='Diretoria',
        cargo_funcao_ref__sigla='CD-04',
    ).exclude(cargo_funcao_ref=diretor_cd04).update(
        cargo_funcao_ref=diretor_cd04,
        sigla_cargo='CD-04',
    )


def backwards(apps, schema_editor):
    CargoFuncao = apps.get_model('core', 'CargoFuncao')
    Unit = apps.get_model('core', 'Unit')
    UnitModelo = apps.get_model('core', 'UnitModelo')
    Dimensionamento = apps.get_model('core', 'Dimensionamento')
    ModeloReferencial = apps.get_model('core', 'ModeloReferencial')

    diretor_cd04 = CargoFuncao.objects.filter(sigla='CD-04', nome='Diretor(a)').order_by('id').first()
    coord_cd04 = CargoFuncao.objects.filter(sigla='CD-04', nome='Coordenador(a)').order_by('id').first()
    if not diretor_cd04 or not coord_cd04:
        return

    dim_ids = list(Dimensionamento.objects.filter(chave__in=DIMS).values_list('id', flat=True))
    modelos = ModeloReferencial.objects.filter(dimensionamento_id__in=dim_ids)

    UnitModelo.objects.filter(
        modelo__in=modelos,
        tipo_unidade__nome='Diretoria',
        cargo_funcao_ref=diretor_cd04,
    ).update(cargo_funcao_ref=coord_cd04)

    Unit.objects.filter(
        organograma__campus__dimensionamento_fk_id__in=dim_ids,
        tipo_unidade__nome='Diretoria',
        cargo_funcao_ref=diretor_cd04,
    ).update(cargo_funcao_ref=coord_cd04)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0053_tipounidade_cargos_ocupantes_permitidos'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
