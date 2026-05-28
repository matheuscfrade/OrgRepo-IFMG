import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import CargoFuncao, TipoUnidade


# Carga de Cargos e Funções
cargos = [
    ('Reitor(a)', 'CD-01'),
    ('Diretor(a) Geral', 'CD-02'),
    ('Diretor(a)', 'CD-03'),
    ('Coordenador(a)', 'CD-04'),
    ('Chefe', 'FG-01'),
    ('Chefe', 'FG-02'),
    ('Supervisor(a)', 'FG-03'),
]

for nome, sigla in cargos:
    CargoFuncao.objects.get_or_create(nome=nome, sigla=sigla)

# Carga de Tipos de Unidades
tipos = [
    'Reitoria', 'Campus', 'Diretoria', 'Pró-Reitoria',
    'Coordenadoria', 'Setor', 'Seção', 'Núcleo'
]

for nome in tipos:
    TipoUnidade.objects.get_or_create(nome=nome)

# Mapeamento Tipo -> Cargo Padrão
mapping = {
    'Reitoria': 'Reitor(a)',
    'Campus': 'Diretor(a) Geral',
    'Pró-Reitoria': 'Diretor(a) Geral',
    'Diretoria': 'Diretor(a)',
    'Coordenadoria': 'Coordenador(a)',
    'Setor': 'Chefe',
    'Seção': 'Chefe',
    'Núcleo': 'Supervisor(a)',
}

for tipo_nome, cargo_nome in mapping.items():
    try:
        tipo = TipoUnidade.objects.get(nome=tipo_nome)
        cargo = CargoFuncao.objects.filter(nome=cargo_nome).order_by('id').first()
        tipo.cargo_padrao = cargo
        tipo.save()
    except TipoUnidade.DoesNotExist:
        pass

print("Vínculos de Cargo Padrão aplicados!")
