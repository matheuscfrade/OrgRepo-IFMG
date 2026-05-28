from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0049_solicitacaoalteracao_justificativa_avaliador_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='CampusCotaCargo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantidade', models.PositiveIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Quantidade')),
                ('campus', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cotas_cargos', to='core.campus', verbose_name='Campus')),
                ('cargo_funcao', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cotas_campi', to='core.cargofuncao', verbose_name='Cargo/Função')),
            ],
            options={
                'verbose_name': 'Cota de Cargo/Função do Campus',
                'verbose_name_plural': 'Cotas de Cargos/Funções do Campus',
                'ordering': ['cargo_funcao__sigla'],
                'unique_together': {('campus', 'cargo_funcao')},
            },
        ),
        migrations.CreateModel(
            name='ModeloReferencialCotaCargo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantidade', models.PositiveIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Quantidade')),
                ('cargo_funcao', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cotas_modelos_referenciais', to='core.cargofuncao', verbose_name='Cargo/Função')),
                ('modelo_referencial', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cotas_cargos', to='core.modeloreferencial', verbose_name='Modelo Referencial')),
            ],
            options={
                'verbose_name': 'Cota de Cargo/Função do Modelo',
                'verbose_name_plural': 'Cotas de Cargos/Funções do Modelo',
                'ordering': ['cargo_funcao__sigla'],
                'unique_together': {('modelo_referencial', 'cargo_funcao')},
            },
        ),
    ]
