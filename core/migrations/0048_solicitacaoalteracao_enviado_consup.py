from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0047_organograma_data_aprovacao_sistema'),
    ]

    operations = [
        migrations.AlterField(
            model_name='solicitacaoalteracao',
            name='status',
            field=models.CharField(
                choices=[
                    ('EM_ANALISE', 'Em Análise'),
                    ('ENVIADO_CONSUP', 'Enviado para Aprovação no CONSUP'),
                    ('APROVADO', 'Aprovado'),
                    ('REJEITADO', 'Rejeitado'),
                ],
                default='EM_ANALISE',
                max_length=20,
            ),
        ),
    ]
