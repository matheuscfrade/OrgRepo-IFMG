from django.db import migrations, models


def seed_diretoria_cd03_cd04(apps, schema_editor):
    """Allow Diretoria to use CD-03 (default) or CD-04 (small-campus models)."""
    TipoUnidade = apps.get_model('core', 'TipoUnidade')
    CargoFuncao = apps.get_model('core', 'CargoFuncao')

    diretoria = TipoUnidade.objects.filter(nome='Diretoria').order_by('id').first()
    if not diretoria:
        return

    cd03 = CargoFuncao.objects.filter(sigla='CD-03').order_by('id').first()
    cd04 = CargoFuncao.objects.filter(sigla='CD-04').order_by('id').first()
    cargos = [c for c in (cd03, cd04) if c is not None]
    if not cargos:
        return

    if cd03 and diretoria.cargo_padrao_id is None:
        diretoria.cargo_padrao_id = cd03.id
        diretoria.save(update_fields=['cargo_padrao_id'])

    diretoria.cargos_ocupantes_permitidos.set(cargos)


def unseed_diretoria(apps, schema_editor):
    TipoUnidade = apps.get_model('core', 'TipoUnidade')
    diretoria = TipoUnidade.objects.filter(nome='Diretoria').order_by('id').first()
    if diretoria:
        diretoria.cargos_ocupantes_permitidos.clear()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0052_solicitacaoalteracao_rascunho'),
    ]

    operations = [
        migrations.AddField(
            model_name='tipounidade',
            name='cargos_ocupantes_permitidos',
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    'Lista de cargos/funções aceitos para este tipo. Se vazia, vale apenas o cargo padrão. '
                    'Ex.: Diretoria pode permitir CD-03 (Diretor) e CD-04 (Coordenador) nos campi menores.'
                ),
                related_name='tipos_unidade_como_ocupante',
                to='core.cargofuncao',
                verbose_name='Cargos ocupantes permitidos',
            ),
        ),
        migrations.RunPython(seed_diretoria_cd03_cd04, unseed_diretoria),
    ]
