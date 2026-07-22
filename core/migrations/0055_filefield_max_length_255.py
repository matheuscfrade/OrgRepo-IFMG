from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0054_diretoria_cd04_as_diretor'),
    ]

    operations = [
        migrations.AlterField(
            model_name='regimentocampus',
            name='arquivo',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to='regimentos_campus/',
                verbose_name='Arquivo do Regimento',
            ),
        ),
        migrations.AlterField(
            model_name='resolucaoestruturaorganizacional',
            name='arquivo',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to='documentos_aprovacao/',
                verbose_name='Arquivo da Resolução',
            ),
        ),
        migrations.AlterField(
            model_name='organograma',
            name='documento_aprovacao',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to='documentos_aprovacao/',
                verbose_name='Arquivo da Resolução',
            ),
        ),
        migrations.AlterField(
            model_name='organograma',
            name='regimento_arquivo',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to='regimentos/',
                verbose_name='Arquivo do Regimento Interno',
            ),
        ),
        migrations.AlterField(
            model_name='organograma',
            name='regimento_geral_arquivo',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to='regimentos_gerais/',
                verbose_name='Arquivo do Regimento Geral',
            ),
        ),
    ]
