from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Campus,
    CargoFuncao,
    Dimensionamento,
    ModeloReferencial,
    RegrasAlteracaoModelo,
    TipoUnidade,
    UnitModelo,
)
from core.services.governance import apply_rule_defaults


RESOLUCAO = 'Resolução CONSUP 44/2025'
RESOLUCAO_LEGADA = 'Resolucao CONSUP 44/2025'

DIMENSIONAMENTOS = {
    '150': 'Modelo 150',
    '150_AGRI': 'Modelo 150 Agrícola',
    '90_70_AGRI': 'Modelo 90/70 Agrícola',
    '70_45': 'Modelo 70/45',
    '40_26': 'Modelo 40/26',
    'POLO': 'Polo de Inovação',
}

CARGOS = {
    'CD-01': 'Reitor(a)',
    'CD-02': 'Diretor(a) Geral',
    'CD-03': 'Diretor(a)',
    'CD-04': 'Coordenador(a)',  # Coordenadoria (todos os dimensionamentos)
    'FG-01': 'Chefe',
    'FG-02': 'Chefe',
    'FG-03': 'Supervisor(a)',
}

# Diretoria em modelos 40/26 e 70/45 usa CD-04 com nomenclatura de Diretor(a),
# distinto do CD-04 Coordenador(a) das Coordenadorias.
CARGO_DIRETOR_CD04_KEY = 'CD-04-DIR'
CARGO_DIRETOR_CD04_NOME = 'Diretor(a)'
CARGO_DIRETOR_CD04_SIGLA = 'CD-04'
SMALL_CAMPUS_DIMS_WITH_DIRETORIA_CD04 = frozenset({'40_26', '70_45'})

TIPOS = {
    'IFMG campus': ('Campus', 'CD-02'),
    'IFMG Polo de Inovação': ('Polo de Inovação', 'CD-02'),
    'Diretoria': ('Diretoria', 'CD-03'),
    'Coordenadoria': ('Coordenadoria', 'CD-04'),
    'Departamento': ('Departamento', 'FG-01'),
    'Setor': ('Setor', 'FG-01'),
    'Seção': ('Seção', 'FG-02'),
    'Núcleo': ('Núcleo', 'FG-03'),
}


def unit(name, cargo, children=None):
    return {'name': name, 'cargo': cargo, 'children': children or []}


MODELOS = {
    'POLO': unit('IFMG Polo de Inovação', 'CD-02', [
        unit('Coordenadoria de Prospecção e Gestão de Projetos de PD&I', 'CD-04'),
        unit('Seção de Administração', 'FG-02'),
        unit('Seção de Finanças', 'FG-02'),
    ]),
    '40_26': unit('IFMG campus', 'CD-02', [
        unit('Diretoria de Ensino', 'CD-04', [
            unit('Setor ou Seção de Planejamento de Ensino', 'FG-01 ou FG-02'),
            unit('Setor ou Seção de Assuntos Estudantis', 'FG-01 ou FG-02'),
            unit('Setor ou Seção de Controle e Registro Acadêmico', 'FG-01 ou FG-02'),
        ]),
        unit('Setor ou Seção de Pesquisa, Inovação e Pós-Graduação', 'FG-01 ou FG-02'),
        unit('Setor ou Seção de Extensão, Esporte e Cultura', 'FG-01 ou FG-02'),
        unit('Diretoria de Administração e Planejamento', 'CD-04', [
            unit('Setor ou Seção de Administração e Infraestrutura', 'FG-01 ou FG-02'),
            unit('Setor ou Seção de Planejamento e Orçamento', 'FG-01 ou FG-02'),
            unit('Setor ou Seção de Almoxarifado e Patrimônio', 'FG-01 ou FG-02'),
        ]),
        unit('Setor ou Seção de Gestão de Pessoas', 'FG-01 ou FG-02'),
        unit('Setor ou Seção de Tecnologia da Informação', 'FG-01 ou FG-02'),
        unit('Setor ou Seção de Assuntos Institucionais', 'FG-01 ou FG-02'),
        unit('Setor ou Seção de Relações Institucionais e Comunicação', 'FG-01 ou FG-02'),
    ]),
    '70_45': unit('IFMG campus', 'CD-02', [
        unit('Diretoria de Ensino ou de Ensino, Pesquisa e Extensão', 'CD-04', [
            unit('Setor ou Seção de Planejamento de Ensino', 'FG-01 ou FG-02'),
            unit('Setor ou Seção Pedagógico(a)', 'FG-01 ou FG-02'),
            unit('Setor ou Seção de Assuntos Estudantis', 'FG-01 ou FG-02'),
            unit('Setor ou Seção de Controle e Registro Acadêmico', 'FG-01 ou FG-02'),
        ]),
        unit('Setor ou Seção de Pesquisa, Inovação e Pós-Graduação', 'FG-01 ou FG-02'),
        unit('Setor ou Seção de Extensão', 'FG-01 ou FG-02'),
        unit('Diretoria de Administração e Planejamento', 'CD-04', [
            unit('Setor ou Seção de Administração e Infraestrutura', 'FG-01 ou FG-02'),
            unit('Setor ou Seção de Planejamento e Orçamento', 'FG-01 ou FG-02'),
            unit('Setor ou Seção de Almoxarifado e Patrimônio', 'FG-01 ou FG-02'),
        ]),
        unit('Setor ou Seção de Gestão de Pessoas', 'FG-01 ou FG-02'),
        unit('Setor ou Seção de Tecnologia da Informação', 'FG-01 ou FG-02'),
        unit('Setor ou Seção de Assuntos Institucionais', 'FG-01 ou FG-02'),
    ]),
    '90_70_AGRI': unit('IFMG campus', 'CD-02', [
        unit('Diretoria de Ensino', 'CD-03', [
            unit('Coordenadoria de Ensino Médio e Técnico', 'CD-04', [
                unit('Núcleo de Apoio ao Ensino Médio', 'FG-03'),
            ]),
            unit('Coordenadoria de Ensino Superior', 'CD-04'),
            unit('Coordenadoria de Assuntos Estudantis', 'CD-04', [
                unit('Núcleo de Moradia Estudantil', 'FG-03'),
            ]),
            unit('Seção de Controle e Registro Acadêmico', 'FG-02'),
        ]),
        unit('Seção de Pesquisa, Inovação e Pós-Graduação', 'FG-02'),
        unit('Setor de Extensão, Esporte e Cultura', 'FG-01'),
        unit('Diretoria de Administração e Planejamento', 'CD-03', [
            unit('Coordenadoria de Administração', 'CD-04', [
                unit('Seção de Manutenção e Infraestrutura', 'FG-02'),
                unit('Seção de Logística e Mecanização', 'FG-02'),
            ]),
            unit('Setor de Planejamento, Finanças e Contabilidade', 'FG-01', [
                unit('Seção de Contratos', 'FG-02'),
                unit('Núcleo de Planejamento e Compras', 'FG-03'),
                unit('Seção de Projetos de Produção Agrícola', 'FG-02'),
                unit('Seção de Projetos de Produção Animal', 'FG-02'),
            ]),
        ]),
        unit('Setor de Gestão de Pessoas', 'FG-01'),
        unit('Setor de Tecnologia da Informação', 'FG-01'),
        unit('Seção de Assuntos Institucionais, Comunicação e Eventos', 'FG-02', [
            unit('Núcleo de Comunicação e Eventos', 'FG-03'),
        ]),
    ]),
    '150_AGRI': unit('IFMG campus', 'CD-02', [
        unit('Diretoria de Ensino', 'CD-03', [
            unit('Coordenadoria de Gestão Acadêmica', 'CD-04', [
                unit('Seção de Apoio Educacional Ensino Técnico', 'FG-02'),
                unit('Seção de Apoio Educacional Ensino Superior', 'FG-02'),
                unit('Núcleo de Biblioteca', 'FG-03'),
                unit('Setor de Planejamento e Controle Acadêmico', 'FG-01'),
                unit('Seção de Registro Acadêmico Cursos Técnicos', 'FG-02'),
                unit('Seção de Registro Acadêmico Cursos Superiores', 'FG-02'),
            ]),
            unit('Seção de Planejamento e Assuntos Educacionais', 'FG-02'),
            unit('Departamento de Ciências Agrárias', 'FG-01'),
            unit('Departamento de Ciências e Linguagens', 'FG-01'),
            unit('Departamento de Ciências Gerenciais e Humanas', 'FG-01'),
            unit('Departamento de Engenharia e Computação', 'FG-01'),
        ]),
        unit('Diretoria de Pesquisa, Inovação e Pós-Graduação', 'CD-03', [
            unit('Seção de Pesquisa e Pós-Graduação', 'FG-02'),
            unit('Núcleo de Inovação e Empreendedorismo', 'FG-03'),
            unit('Núcleo de Controle e Registro Acadêmico de Pós-Graduação', 'FG-03'),
        ]),
        unit('Diretoria de Extensão, Esporte e Cultura', 'CD-03', [
            unit('Seção de Extensão', 'FG-02'),
            unit('Seção de Estágio e Mobilidade Acadêmica', 'FG-02'),
            unit('Seção de Extensão Curricular e Qualificação Profissional', 'FG-02'),
        ]),
        unit('Diretoria de Administração e Planejamento', 'CD-03', [
            unit('Coordenadoria de Planejamento e Orçamento', 'CD-04', [
                unit('Setor de Compras, Contratos e Convênios', 'FG-01'),
                unit('Seção de Almoxarifado e Patrimônio', 'FG-02'),
            ]),
            unit('Coordenadoria de Produção', 'CD-04', [
                unit('Setor de Logística e Mecanização', 'FG-01'),
                unit('Setor de Manutenção e Infraestrutura', 'FG-01'),
                unit('Seção de Jardinagem e Paisagismo', 'FG-02'),
                unit('Seção de Comercialização de Produtos e Serviços', 'FG-02'),
            ]),
        ]),
        unit('Coordenadoria de Gestão de Pessoas', 'CD-04', [
            unit('Seção de Desenvolvimento de Pessoas', 'FG-02'),
            unit('Seção de Cadastro e Pagamento', 'FG-02'),
        ]),
        unit('Coordenadoria de Tecnologia da Informação', 'CD-04', [
            unit('Núcleo de Supervisão de Serviços e Processos de TI', 'FG-03'),
        ]),
        unit('Coordenadoria de Assuntos Estudantis', 'CD-04', [
            unit('Seção da Moradia Estudantil', 'FG-02'),
        ]),
        unit('Coordenadoria de Assuntos Institucionais, Comunicação e Eventos', 'CD-04', [
            unit('Seção de Comunicação e Eventos', 'FG-02'),
        ]),
        unit('Coordenadoria de Desenvolvimento Institucional', 'CD-04'),
        unit('Setor de Atendimento Veterinário', 'FG-01'),
    ]),
    '150': unit('IFMG campus', 'CD-02', [
        unit('Diretoria de Ensino', 'CD-03', [
            unit('Coordenadoria de Planejamento de Ensino', 'CD-04', [
                unit('Seção de Biblioteca', 'FG-02'),
                unit('Seção de Avaliação Educacional, Normas e Projetos', 'FG-02'),
            ]),
            unit('Coordenadoria de Controle e Registro Acadêmico', 'CD-04', [
                unit('Seção de Controle Acadêmico', 'FG-02'),
                unit('Setor de Registro Acadêmico', 'FG-01'),
            ]),
            unit('Setor de Funcionamento e Logística Escolar', 'FG-01'),
            unit('Setor de Apoio e Desenvolvimento a Docências de Áreas', 'FG-01'),
        ]),
        unit('Coordenadoria de Assuntos Pedagógicos e Estudantis', 'CD-04', [
            unit('Seção Pedagógica', 'FG-02'),
            unit('Seção de Assistência Estudantil', 'FG-02'),
            unit('Seção de Alimentação Escolar', 'FG-02'),
        ]),
        unit('Diretoria de Pesquisa, Inovação e Pós-Graduação', 'CD-03', [
            unit('Seção de Pesquisa', 'FG-02'),
            unit('Seção de Inovação e Empreendedorismo', 'FG-02'),
            unit('Seção de Pós-Graduação', 'FG-02'),
        ]),
        unit('Diretoria de Extensão, Esporte e Cultura', 'CD-03', [
            unit('Setor de Relações Empresariais', 'FG-01'),
            unit('Setor de Extensão', 'FG-01'),
        ]),
        unit('Diretoria de Administração e Planejamento', 'CD-03', [
            unit('Coordenadoria de Planejamento e Orçamento', 'CD-04', [
                unit('Seção de Finanças e Contabilidade', 'FG-02'),
                unit('Seção de Suprimentos', 'FG-02'),
            ]),
            unit('Coordenadoria de Manutenção e Infraestrutura', 'CD-04'),
            unit('Setor de Logística e Materiais', 'FG-01'),
        ]),
        unit('Coordenadoria de Gestão de Pessoas', 'CD-04', [
            unit('Seção de Desenvolvimento de Pessoas', 'FG-02'),
            unit('Seção de Cadastro e Pagamento', 'FG-02'),
        ]),
        unit('Coordenadoria de Desenvolvimento Institucional', 'CD-04', [
            unit('Setor de Tecnologia da Informação', 'FG-01'),
            unit('Setor de Tecnologias Educacionais Digitais e Educação a Distância', 'FG-01'),
            unit('Seção de Desenvolvimento de Sistemas', 'FG-02'),
        ]),
        unit('Coordenadoria de Assuntos Institucionais, Comunicação e Eventos', 'CD-04', [
            unit('Setor de Comunicação', 'FG-01'),
            unit('Seção de Relações Institucionais', 'FG-02'),
            unit('Seção de Eventos', 'FG-02'),
        ]),
    ]),
}


def infer_tipo_key(name, cargo):
    if name.startswith('IFMG Polo'):
        return 'IFMG Polo de Inovação'
    if name.startswith('IFMG'):
        return 'IFMG campus'
    if name.startswith('Diretoria'):
        return 'Diretoria'
    if name.startswith('Coordenadoria'):
        return 'Coordenadoria'
    if name.startswith('Departamento'):
        return 'Departamento'
    if name.startswith('Núcleo') or name.startswith('Nucleo'):
        return 'Núcleo'
    if name.startswith('Seção') or name.startswith('Secao'):
        return 'Seção'
    if name.startswith('Setor'):
        return 'Setor'
    if 'FG-03' in cargo:
        return 'Núcleo'
    if 'FG-02' in cargo:
        return 'Seção'
    if 'FG-01' in cargo:
        return 'Setor'
    return None


class Command(BaseCommand):
    help = 'Carrega os modelos referenciais da Resolução CONSUP 44/2025.'

    def handle(self, *args, **options):
        with transaction.atomic():
            dimensions = self.ensure_dimensionamentos()
            cargos = self.ensure_cargos(dimensions.values())
            tipos = self.ensure_tipos(cargos, dimensions.values())
            total = 0
            for chave, root in MODELOS.items():
                modelo = self.ensure_modelo(chave, dimensions[chave])
                modelo.unidades.all().delete()
                total += self.create_unit_tree(modelo, root, None, cargos, tipos, dimensions[chave], 1)
                regras, _ = RegrasAlteracaoModelo.objects.get_or_create(modelo_referencial=modelo)
                apply_rule_defaults(regras)
                regras.save()

            # Also load basic Campi as part of the foundation
            self.ensure_basic_campi(dimensions)

        self.stdout.write(self.style.SUCCESS(f'Modelos referenciais carregados: {len(MODELOS)} modelos, {total} unidades.'))

    def ensure_dimensionamentos(self):
        result = {}
        for chave, nome in DIMENSIONAMENTOS.items():
            dim, _ = Dimensionamento.objects.update_or_create(chave=chave, defaults={'nome': nome})
            result[chave] = dim
        return result

    def _ensure_one_cargo(self, sigla, nome, dimensionamentos):
        """Create/update a single CargoFuncao by (nome, sigla) without clobbering siblings."""
        cargo = CargoFuncao.objects.filter(sigla=sigla, nome=nome).order_by('id').first()
        if not cargo:
            cargo = CargoFuncao.objects.create(sigla=sigla, nome=nome)
        cargo.dimensionamentos_permitidos.add(*dimensionamentos)
        return cargo

    def ensure_cargos(self, dimensionamentos):
        result = {}
        for sigla, nome in CARGOS.items():
            result[sigla] = self._ensure_one_cargo(sigla, nome, dimensionamentos)
        # Diretor(a) CD-04 — ocupante de Diretoria nos campi 40/26 e 70/45
        result[CARGO_DIRETOR_CD04_KEY] = self._ensure_one_cargo(
            CARGO_DIRETOR_CD04_SIGLA,
            CARGO_DIRETOR_CD04_NOME,
            dimensionamentos,
        )
        return result

    def ensure_tipos(self, cargos, dimensionamentos):
        result = {}
        for key, (nome, cargo_sigla) in TIPOS.items():
            tipos = TipoUnidade.objects.filter(nome=nome).order_by('id')
            tipo = tipos.first()
            if tipo:
                tipos.update(cargo_padrao=cargos.get(cargo_sigla))
                tipo.refresh_from_db()
            else:
                tipo = TipoUnidade.objects.create(nome=nome, cargo_padrao=cargos.get(cargo_sigla))
            tipo.dimensionamentos_permitidos.add(*dimensionamentos)
            result[key] = tipo

        tipo_setor = result['Setor']
        tipo_secao = result['Seção']
        tipo_setor.selecao_cargo_livre = False
        tipo_secao.selecao_cargo_livre = False
        tipo_setor.save(update_fields=['selecao_cargo_livre'])
        tipo_secao.save(update_fields=['selecao_cargo_livre'])

        # Diretoria: padrão CD-03; campi 40/26 e 70/45 usam CD-04 como Diretor(a)
        tipo_diretoria = result.get('Diretoria')
        if tipo_diretoria:
            cd03 = cargos.get('CD-03')
            cd04_dir = cargos.get(CARGO_DIRETOR_CD04_KEY)
            if cd03:
                tipo_diretoria.cargo_padrao = cd03
                tipo_diretoria.save(update_fields=['cargo_padrao'])
            permitidos = [c for c in (cd03, cd04_dir) if c is not None]
            if permitidos:
                tipo_diretoria.cargos_ocupantes_permitidos.set(permitidos)

        return result

    def ensure_modelo(self, chave, dimensionamento):
        nome = f"{DIMENSIONAMENTOS[chave]} - {RESOLUCAO}"
        modelo = ModeloReferencial.objects.filter(
            dimensionamento=dimensionamento,
            resolucao_referencia__in=[RESOLUCAO, RESOLUCAO_LEGADA],
        ).order_by('id').first()
        if not modelo:
            modelo = ModeloReferencial(dimensionamento=dimensionamento)
        modelo.resolucao_referencia = RESOLUCAO
        modelo.nome = nome
        modelo.descricao = f"Modelo referencial conforme {RESOLUCAO}."
        modelo.ativo = True
        modelo.save()
        return modelo

    def create_unit_tree(self, modelo, data, parent, cargos, tipos, dimensionamento, order):
        cargo_sigla = data['cargo']
        is_flexible = 'ou' in cargo_sigla.lower()
        tipo_key = infer_tipo_key(data['name'], cargo_sigla)
        tipo = None if is_flexible else tipos.get(tipo_key)
        cargo = None
        sigla_cargo_stored = ''
        if not is_flexible:
            # Diretoria + CD-04 nos modelos de campus pequeno = Diretor(a) CD-04
            # (não Coordenador(a) CD-04 das Coordenadorias)
            dim_chave = getattr(dimensionamento, 'chave', None) or ''
            if (
                tipo_key == 'Diretoria'
                and cargo_sigla == 'CD-04'
                and dim_chave in SMALL_CAMPUS_DIMS_WITH_DIRETORIA_CD04
            ):
                cargo = cargos.get(CARGO_DIRETOR_CD04_KEY) or cargos.get('CD-04')
            else:
                cargo = cargos.get(cargo_sigla)
            sigla_cargo_stored = cargo.sigla if cargo else cargo_sigla
        unidade = UnitModelo.objects.create(
            modelo=modelo,
            unidade_pai=parent,
            nome_unidade=data['name'],
            tipo_unidade=tipo,
            cargo_funcao_ref=cargo,
            cargo_funcao='Chefe' if is_flexible else '',
            sigla_cargo=sigla_cargo_stored,
            ordem=order,
            permite_resolucao_flexivel=is_flexible,
        )
        if is_flexible:
            unidade.tipos_resolucao_permitidos.set([tipos['Setor'], tipos['Seção']])
            unidade.cargos_resolucao_permitidos.set([cargos['FG-01'], cargos['FG-02']])

        count = 1
        for child_order, child in enumerate(data['children'], start=1):
            count += self.create_unit_tree(modelo, child, unidade, cargos, tipos, dimensionamento, child_order)
        return count

    def ensure_basic_campi(self, dimensions):
        """Creates the basic list of IFMG Campi as part of the foundation data."""
        campi_data = [
            ("IFMG - Reitoria", "IFMG", "REITORIA"),
            ("Campus Betim", "CBMG-BET", "150"),
            ("Campus Congonhas", "CBMG-CON", "70_45"),
            ("Campus Formiga", "CBMG-FOR", "70_45"),
            ("Campus Governador Valadares", "CBMG-GVA", "70_45"),
            ("Campus Ibirité", "CBMG-IBI", "70_45"),
            ("Campus Ipatinga", "CBMG-IPA", "70_45"),
            ("Campus Ouro Preto", "CBMG-OPR", "70_45"),
            ("Campus Pouso Alegre", "CBMG-POA", "70_45"),
            ("Campus Sabará", "CBMG-SAB", "70_45"),
            ("Campus Santa Luzia", "CBMG-SLU", "70_45"),
            ("Campus São João Evangelista", "CBMG-SJE", "70_45"),
            ("Campus Varginha", "CBMG-VAR", "70_45"),
            ("Campus Bambuí", "CBMG-BAM", "150_AGRI"),
            ("Campus Januária", "CBMG-JAN", "150_AGRI"),
            ("Campus Montes Claros", "CBMG-MOC", "150_AGRI"),
            ("Campus Pirapora", "CBMG-PIR", "150_AGRI"),
            ("Campus São João da Ponte", "CBMG-SJP", "150_AGRI"),
            ("Polo de Inovação", "POLO-INOV", "POLO"),
            ("Campus Conselheiro Lafaiete", "CBMG-CLF", "40_26"),
        ]

        created = 0
        for nome, sigla, dim_chave in campi_data:
            dim = dimensions.get(dim_chave)
            campus, was_created = Campus.objects.get_or_create(
                sigla=sigla,
                defaults={
                    "nome": nome,
                    "dimensionamento": dim_chave,
                    "dimensionamento_fk": dim,
                },
            )
            if was_created:
                created += 1

        if created:
            self.stdout.write(f"  {created} Campi created as part of foundation.")

