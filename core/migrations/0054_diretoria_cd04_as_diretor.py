"""
Campi 40/26 e 70/45: Diretoria ocupa CD-04 como Diretor(a), não Coordenador(a).

Rewires UnitModelo/Unit when foundation data already exists.
On a fresh empty database (TI migrate before load_full_data), this is a no-op
so we never create CargoFuncao Diretor(a)/CD-04 as pk=1 and clash with the
snapshot's Reitor(a)/CD-01. Diretor CD-04 is created later by the fixture
and/or load_consup44_modelos.
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

    # Empty DB (pre-snapshot): do not insert cargos — fixture owns PKs.
    if not CargoFuncao.objects.exists():
        return

    coord_cd04 = CargoFuncao.objects.filter(sigla='CD-04', nome='Coordenador(a)').order_by('id').first()
    if not coord_cd04:
        coord_cd04 = CargoFuncao.objects.filter(sigla='CD-04', nome__icontains='Coordenador').order_by('id').first()

    diretor_cd04 = CargoFuncao.objects.filter(sigla='CD-04', nome='Diretor(a)').order_by('id').first()
    if not diretor_cd04:
        # Only create when other cargos already exist (PK will not steal id=1).
        diretor_cd04 = CargoFuncao.objects.create(sigla='CD-04', nome='Diretor(a)')

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

    modelos = ModeloReferencial.objects.filter(dimensionamento_id__in=dim_ids)
    UnitModelo.objects.filter(
        modelo__in=modelos,
        tipo_unidade__nome='Diretoria',
        cargo_funcao_ref__sigla='CD-04',
    ).exclude(cargo_funcao_ref=diretor_cd04).update(
        cargo_funcao_ref=diretor_cd04,
        sigla_cargo='CD-04',
    )

    if coord_cd04:
        UnitModelo.objects.filter(
            modelo__in=modelos,
            tipo_unidade__nome='Diretoria',
            cargo_funcao_ref=coord_cd04,
        ).update(cargo_funcao_ref=diretor_cd04, sigla_cargo='CD-04')

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
