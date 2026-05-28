from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0051_dedupe_cargos_tipos_constraints'),
    ]

    operations = [
        migrations.AlterField(
            model_name='solicitacaoalteracao',
            name='status',
            field=models.CharField(
                choices=[
                    ('RASCUNHO', 'Rascunho'),
                    ('EM_ANALISE', 'Em Análise'),
                    ('ENVIADO_CONSUP', 'Enviado para Aprovação no CONSUP'),
                    ('DEVOLVIDO_CORRECAO', 'Devolvido para Correção'),
                    ('APROVADO', 'Aprovado'),
                    ('REJEITADO', 'Rejeitado'),
                ],
                default='RASCUNHO',
                max_length=20,
            ),
        ),
    ]
