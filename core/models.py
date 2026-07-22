from django.db import connection, models, transaction
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver

class Dimensionamento(models.Model):
    nome = models.CharField(max_length=100)
    chave = models.CharField(max_length=20, unique=True) # Ex: '150', 'REITORIA'

    class Meta:
        verbose_name = "Dimensionamento"
        verbose_name_plural = "Dimensionamentos"

    def __str__(self):
        return self.nome

class Campus(models.Model):
    DIMENSIONAMENTO_CHOICES = [
        ('150', 'Modelo 150'),
        ('150_AGRI', 'Modelo 150 Agrícola'),
        ('90_70_AGRI', 'Modelo 90/70 Agrícola'),
        ('70_45', 'Modelo 70/45'),
        ('40_26', 'Modelo 40/26'),
        ('REITORIA', 'Reitoria'),
        ('POLO', 'Polo de Inovação'),
    ]
    nome = models.CharField(max_length=255)
    sigla = models.CharField(max_length=20)
    dimensionamento = models.CharField(
        max_length=20, 
        choices=DIMENSIONAMENTO_CHOICES, 
        null=True, 
        blank=True,
        verbose_name="Tipo de Dimensionamento (Legado)"
    )
    dimensionamento_fk = models.ForeignKey(Dimensionamento, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Tipo de Dimensionamento")
    modelo_referencial_padrao = models.ForeignKey(
        'ModeloReferencial',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campi_padrao',
        verbose_name="Modelo Referencial do Campus",
    )
    
    @property
    def get_sigla_prefix(self):
        if self.sigla == 'IFMG': # Reitoria
            return 'RE'
        if self.sigla.startswith('POLO-'):
            return 'POLO'
        if '-' in self.sigla:
            return self.sigla.split('-')[0]
        return self.sigla

    @property
    def dispensa_modelo_referencial(self):
        return self.sigla == 'IFMG'

    class Meta:
        verbose_name = "Campus"
        verbose_name_plural = "Campi"

    def __str__(self):
        return f"{self.nome} ({self.sigla})"

    @property
    def dimensionamento_chave(self):
        if self.dimensionamento_fk_id:
            return self.dimensionamento_fk.chave
        return self.dimensionamento or ""


class RegimentoCampus(models.Model):
    TIPO_CHOICES = [
        ('INTERNO', 'Regimento Interno'),
        ('GERAL', 'Regimento Geral'),
    ]
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='regimentos')
    tipo = models.CharField("Tipo de Regimento", max_length=20, choices=TIPO_CHOICES, default='INTERNO')
    nome = models.CharField("Nome do Regimento", max_length=255)
    numero = models.CharField("Número/Ato", max_length=100, blank=True, default="")
    data_publicacao = models.DateField("Data de Publicação", null=True, blank=True)
    arquivo = models.FileField(
        "Arquivo do Regimento",
        upload_to='regimentos_campus/',
        null=True,
        blank=True,
        max_length=255,
    )
    link = models.URLField("Link do Regimento", max_length=500, null=True, blank=True)
    vigente = models.BooleanField("Regimento Vigente", default=False)
    observacoes = models.TextField("Observações", blank=True, default="")

    class Meta:
        verbose_name = "Regimento do Campus"
        verbose_name_plural = "Regimentos dos Campi"
        ordering = ['campus__nome', '-vigente', '-data_publicacao', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['campus', 'tipo'],
                condition=models.Q(vigente=True),
                name='unique_regimento_vigente_por_campus_tipo',
            )
        ]

    def save(self, *args, **kwargs):
        regimentos_vigentes_anteriores = []
        if self.vigente:
            regimentos_vigentes_anteriores = list(
                RegimentoCampus.objects.filter(
                    campus=self.campus,
                    tipo=self.tipo,
                    vigente=True,
                ).exclude(pk=self.pk)
            )
            RegimentoCampus.objects.filter(campus=self.campus, tipo=self.tipo, vigente=True).exclude(pk=self.pk).update(vigente=False)
        super().save(*args, **kwargs)
        # During fixture load (load_full_data), skip auto-versioning of organogramas:
        # the snapshot already contains the intended OFICIAL trees and PKs.
        if self.vigente and not getattr(connection, "_orgrepo_loading_fixture", False):
            _versionar_organograma_oficial_por_novo_regimento(self, regimentos_vigentes_anteriores)

    def __str__(self):
        partes = [self.nome]
        if self.numero:
            partes.append(self.numero)
        partes.append(self.campus.sigla)
        partes.append(self.get_tipo_display())
        if self.vigente:
            partes.append("vigente")
        return " - ".join(partes)


class ResolucaoEstruturaOrganizacional(models.Model):
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='resolucoes_estrutura')
    nome = models.CharField("Resolução da Estrutura Organizacional", max_length=255)
    numero = models.CharField("Número/Ato", max_length=100, blank=True, default="")
    data_publicacao = models.DateField("Data de Publicação", null=True, blank=True)
    arquivo = models.FileField(
        "Arquivo da Resolução",
        upload_to='documentos_aprovacao/',
        null=True,
        blank=True,
        max_length=255,
    )
    link = models.URLField("Link da Resolução", max_length=500, null=True, blank=True)
    observacoes = models.TextField("Observações", blank=True, default="")
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Resolução de Estrutura Organizacional"
        verbose_name_plural = "Resoluções de Estruturas Organizacionais"
        ordering = ['campus__nome', '-data_publicacao', '-id']

    def __str__(self):
        partes = [self.nome]
        if self.numero:
            partes.append(self.numero)
        partes.append(self.campus.sigla)
        return " - ".join(partes)


class Organograma(models.Model):
    STATUS_CHOICES = [
        ('RASCUNHO', 'Rascunho'),
        ('OFICIAL', 'Oficial'),
        ('HISTORICO', 'Histórico'),
        ('PROPOSTA', 'Proposta de Alteração'),
    ]
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='organogramas')
    data_vigencia = models.DateField(null=True, blank=True)
    documento_aprovacao = models.FileField(
        upload_to='documentos_aprovacao/',
        null=True,
        blank=True,
        max_length=255,
        verbose_name="Arquivo da Resolução",
    )
    nome_documento_aprovacao = models.CharField(max_length=255, null=True, blank=True, verbose_name="Número/Nome da Resolução")
    resolucao_estrutura = models.ForeignKey(ResolucaoEstruturaOrganizacional, on_delete=models.SET_NULL, null=True, blank=True, related_name='organogramas', verbose_name="Resolução da Estrutura Organizacional")
    nome_regimento = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome do Regimento Interno")
    regimento_arquivo = models.FileField(
        upload_to='regimentos/',
        null=True,
        blank=True,
        max_length=255,
        verbose_name="Arquivo do Regimento Interno",
    )
    nome_regimento_geral = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome do Regimento Geral")
    regimento_geral_arquivo = models.FileField(
        upload_to='regimentos_gerais/',
        null=True,
        blank=True,
        max_length=255,
        verbose_name="Arquivo do Regimento Geral",
    )
    regimento_referencia = models.ForeignKey(RegimentoCampus, on_delete=models.SET_NULL, null=True, blank=True, related_name='organogramas', verbose_name="Regimento de Referência")
    regimento_geral_referencia = models.ForeignKey(RegimentoCampus, on_delete=models.SET_NULL, null=True, blank=True, related_name='organogramas_regimento_geral', verbose_name="Regimento Geral de Referência")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RASCUNHO')
    data_aprovacao_sistema = models.DateTimeField("Data de Aprovação no Sistema", null=True, blank=True)
    modelo_referencia_atualizado_em = models.DateTimeField(null=True, blank=True, verbose_name="Revisão do Modelo Referencial Aplicada")
    organogramas_vinculados = models.ManyToManyField('self', blank=True, symmetrical=False, related_name='vinculados_por', verbose_name="Organogramas Vinculados")
    modelo_base = models.ForeignKey('ModeloReferencial', on_delete=models.SET_NULL, null=True, blank=True, related_name='organogramas_derivados', verbose_name="Modelo Referencial Base")

    @property
    def modelo_referencial_efetivo(self):
        if self.campus.dispensa_modelo_referencial:
            return None
        if self.modelo_base_id:
            return self.modelo_base
        if self.campus.modelo_referencial_padrao_id:
            return self.campus.modelo_referencial_padrao
        chave = self.campus.dimensionamento_chave
        if not chave:
            return None
        return ModeloReferencial.objects.filter(
            dimensionamento__chave=chave,
            ativo=True,
        ).order_by('id').first()

    @property
    def resumo_por_tipo(self):
        from django.db.models import Count
        tipos = self.unidades.values('tipo_unidade__nome').annotate(total=Count('id')).order_by('-total')
        linhas = []
        for t in tipos:
            nome = t['tipo_unidade__nome'] or 'Indefinido/Raiz'
            linhas.append(f"<strong>{ t['total'] }</strong> {nome}")
        return "<br>".join(linhas)

    @property
    def resumo_por_cargo(self):
        resumo = {}
        sem_cargo_count = 0
        for u in self.unidades.all():
            if u.is_agrupamento:
                continue
            
            sigla = u.cargo_funcao_ref.sigla if u.cargo_funcao_ref else u.sigla_cargo
            sigla = sigla.strip() if sigla and sigla.strip() else ''
            
            if sigla.startswith('CD') or sigla.startswith('FG'):
                resumo[sigla] = resumo.get(sigla, 0) + 1
            else:
                sem_cargo_count += 1
            
        ordenados = sorted(resumo.items(), key=lambda x: x[0])
        linhas = [f"<strong>{count}</strong> {sigla}" for sigla, count in ordenados]
        if sem_cargo_count > 0:
            linhas.append(f"<strong>{sem_cargo_count}</strong> Sem CD/FG")
        return "<br>".join(linhas)

    @property
    def resumo_cotas_cargos(self):
        from .services.cargo_quotas import get_organograma_cargo_quota_summary
        return get_organograma_cargo_quota_summary(self)['items']

    @property
    def unidades_reais_count(self):
        return self.unidades.filter(is_agrupamento=False).count()

    @property
    def tem_proposta_ativa(self):
        active_statuses = ['RASCUNHO', 'EM_ANALISE', 'ENVIADO_CONSUP', 'DEVOLVIDO_CORRECAO']
        if not self.campus_id:
            return self.solicitacoes_origem.filter(status__in=active_statuses).exists()
        return SolicitacaoAlteracao.objects.filter(
            organograma_original__campus_id=self.campus_id,
            status__in=active_statuses,
        ).exists()

    @property
    def precisa_adequacao_modelo(self):
        modelo = self.modelo_referencial_efetivo
        if not modelo or not hasattr(modelo, 'regras_alteracao'):
            return False
        if not modelo.regras_alteracao.exigir_adequacao_quando_modelo_mudar:
            return False
        if not self.modelo_referencia_atualizado_em:
            return True
        return self.modelo_referencia_atualizado_em < modelo.data_atualizacao

    @property
    def has_pending_units(self):
        """Verifica se há unidades com definições genéricas pendentes."""
        for u in self.unidades.all():
            if u.has_pending_definition:
                return True
        return False

    @property
    def regimento_competencias_referencia(self):
        if self.regimento_referencia_id:
            return self.regimento_referencia
        return self.campus.regimentos.filter(tipo='INTERNO', vigente=True).order_by('-data_publicacao', '-id').first()

    @property
    def regimentos_competencias_referencia(self):
        regimentos = []
        regimento_interno = self.regimento_competencias_referencia
        if regimento_interno:
            regimentos.append(regimento_interno)
        if self.campus.sigla == 'IFMG':
            if self.regimento_geral_referencia_id:
                regimento_geral = self.regimento_geral_referencia
            else:
                regimento_geral = self.campus.regimentos.filter(tipo='GERAL', vigente=True).order_by('-data_publicacao', '-id').first()
            if regimento_geral and all(r.id != regimento_geral.id for r in regimentos):
                regimentos.append(regimento_geral)
        return regimentos

    @property
    def resolucao_estrutura_referencia(self):
        return self.resolucao_estrutura

    @property
    def competencias_resumo(self):
        resumo = {
            'sem_competencias': 0,
            'desatualizadas': 0,
            'revisadas': 0,
            'total': 0,
        }
        for unidade in self.unidades.filter(is_agrupamento=False):
            resumo['total'] += 1
            status = unidade.competencias_status
            if status == 'sem_competencias':
                resumo['sem_competencias'] += 1
            elif status == 'desatualizada':
                resumo['desatualizadas'] += 1
            elif status == 'revisada':
                resumo['revisadas'] += 1
        resumo['tem_alertas'] = bool(resumo['sem_competencias'] or resumo['desatualizadas'])
        return resumo

    def validar_limites_alteracao(self):
        from .services.governance import validate_organograma_governance
        return validate_organograma_governance(self, persist_links=True)['errors']

    def save(self, *args, **kwargs):
        if self.status == 'OFICIAL':
            if not self.data_aprovacao_sistema:
                self.data_aprovacao_sistema = timezone.now()
                update_fields = kwargs.get('update_fields')
                if update_fields is not None and 'data_aprovacao_sistema' not in update_fields:
                    kwargs['update_fields'] = list(update_fields) + ['data_aprovacao_sistema']
            # Se este está sendo salvo como OFICIAL, desativa os outros do mesmo Campus
            Organograma.objects.filter(campus=self.campus, status='OFICIAL').exclude(pk=self.pk).update(status='HISTORICO')
        super().save(*args, **kwargs)

    def __str__(self):
        status_display = dict(self.STATUS_CHOICES).get(self.status, self.status)
        return f"Organograma {self.campus.sigla} - {status_display}"

class CargoFuncao(models.Model):
    nome = models.CharField("Nome do Cargo/Função", max_length=100)
    sigla = models.CharField("Sigla", max_length=20)
    dimensionamentos_permitidos = models.ManyToManyField(Dimensionamento, blank=True, verbose_name="Dimensionamentos Autorizados")

    class Meta:
        verbose_name = "Cargo/Função"
        verbose_name_plural = "Cargos/Funções"
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(fields=['nome', 'sigla'], name='unique_cargo_funcao_nome_sigla'),
        ]

    def __str__(self):
        return f"{self.nome} ({self.sigla})"

    @property
    def is_generico_pendente(self):
        nome_upper = (self.nome or "").upper()
        sigla_upper = (self.sigla or "").upper()
        return "FG-01 OU FG-02" in nome_upper or "FG-01 OU FG-02" in sigla_upper


class TipoUnidade(models.Model):
    nome = models.CharField("Tipo de Departamento", max_length=100)
    cargo_padrao = models.ForeignKey(CargoFuncao, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Cargo Ocupante Padrão")
    dimensionamentos_permitidos = models.ManyToManyField(Dimensionamento, blank=True, verbose_name="Dimensionamentos Autorizados")
    # When set, the unit form may choose among these cargos (e.g. Diretoria: CD-03 and CD-04
    # for small campuses under Resolução CONSUP 44/2025 models 40/26 and 70/45).
    cargos_ocupantes_permitidos = models.ManyToManyField(
        CargoFuncao,
        blank=True,
        related_name='tipos_unidade_como_ocupante',
        verbose_name="Cargos ocupantes permitidos",
        help_text=(
            "Lista de cargos/funções aceitos para este tipo. Se vazia, vale apenas o cargo padrão. "
            "Ex.: Diretoria pode permitir CD-03 Diretor(a) e CD-04 Diretor(a) nos campi 40/26 e 70/45 "
            "(Coordenador(a)/CD-04 continua como cargo distinto para Coordenadoria)."
        ),
    )
    selecao_cargo_livre = models.BooleanField(
        default=False,
        verbose_name="Permite Seleção Livre de Cargo",
        help_text="Quando marcado, o cargo não é preenchido automaticamente - o usuário pode escolher entre os cargos disponíveis (ex: Setor/Seção que aceitam FG-01 ou FG-02)."
    )
    apenas_modelo_referencial = models.BooleanField(
        default=False,
        verbose_name="Exclusivo para Modelos Referenciais",
        help_text="Quando marcado, este tipo só aparece no construtor de Modelos Referenciais - não fica disponível no builder de organogramas de campus."
    )

    class Meta:
        verbose_name = "Tipo de Unidade"
        verbose_name_plural = "Tipos de Unidades"
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(fields=['nome'], name='unique_tipo_unidade_nome'),
        ]

    def __str__(self):
        return self.nome

    @property
    def is_generico_pendente(self):
        nome_upper = (self.nome or "").upper()
        return "SETOR OU SEÇÃO" in nome_upper or "SETOR OU SECAO" in nome_upper

    def get_allowed_cargo_ids(self):
        """
        Cargo IDs acceptable for units of this type.

        Priority:
        1. Explicit cargos_ocupantes_permitidos (plus cargo_padrao if set)
        2. selecao_cargo_livre / genérico pendente → FG-01 and FG-02
        3. cargo_padrao alone
        """
        explicit_ids = list(self.cargos_ocupantes_permitidos.values_list('id', flat=True))
        if explicit_ids:
            ids = set(explicit_ids)
            if self.cargo_padrao_id:
                ids.add(self.cargo_padrao_id)
            return sorted(ids)
        if self.selecao_cargo_livre or self.is_generico_pendente:
            return list(
                CargoFuncao.objects.filter(sigla__in=['FG-01', 'FG-02'])
                .order_by('sigla', 'id')
                .values_list('id', flat=True)
            )
        if self.cargo_padrao_id:
            return [self.cargo_padrao_id]
        return []

    @property
    def permite_escolha_entre_cargos(self):
        """True when the builder should unlock the cargo select (more than one option)."""
        return len(self.get_allowed_cargo_ids()) > 1


class Unit(models.Model):
    organograma = models.ForeignKey(Organograma, on_delete=models.CASCADE, related_name='unidades')
    unidade_pai = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='sub_unidades')
    source_unit = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='propostas_unidade', verbose_name="Unidade Origem (para Propostas)")
    origem_modelo = models.ForeignKey('UnitModelo', on_delete=models.SET_NULL, null=True, blank=True, related_name='unidades_derivadas', verbose_name="Caixa Origem no Modelo")
    nome_unidade = models.CharField("Nome da Unidade Organizacional", max_length=255)
    sigla_unidade = models.CharField("Sigla da Unidade", max_length=50, blank=True, null=True)
    
    # Novos campos de metadados
    tipo_unidade = models.ForeignKey(TipoUnidade, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Tipo de Departamento")
    cargo_funcao_ref = models.ForeignKey(CargoFuncao, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Cargo ou Função Relacionada")
    
    # Campos livres para uso em tipos customizados (ex: Outro)
    cargo_funcao = models.CharField("Cargo ou Função Relacionada", max_length=255, null=True, blank=True)
    sigla_cargo = models.CharField("Sigla do Cargo/Função", max_length=50, null=True, blank=True)
    atribuicoes = models.TextField("Atribuições do Departamento", null=True, blank=True)
    ordem = models.IntegerField("Ordem", default=0)

    # Ligações e Vínculos avançados
    ligacao_indireta = models.BooleanField("Ligação Indireta", default=False, help_text="A linha de conexão com o superior será tracejada.")
    oculto_no_organograma = models.BooleanField(
        default=False,
        verbose_name="Oculto no Organograma",
        help_text="Se marcado, esta unidade (e suas subunidades) não aparecerão na visualização pública."
    )

    is_agrupamento = models.BooleanField(
        default=False,
        verbose_name="É Agrupamento Visual?",
        help_text="Define se esta unidade é apenas um grupo de interface para organizar outras caixinhas."
    )

    layout_filhos = models.CharField(
        max_length=1,
        choices=[('H', 'Horizontal'), ('V', 'Vertical')],
        default='V',
        verbose_name="Layout dos Filhos",
        help_text="Define se as subunidades serão dispostas lado a lado (Horizontal) ou empilhadas (Vertical)."
    )

    class Meta:
        verbose_name = "Unidade"
        verbose_name_plural = "Unidades"
        ordering = ['ordem', 'id']

    def __str__(self):
        prefix = "[Agrupamento] " if self.is_agrupamento else ""
        if self.sigla_unidade and self.sigla_unidade.strip():
            return f"{prefix}{self.sigla_unidade} - {self.nome_unidade}"
        return f"{prefix}{self.nome_unidade}"

    @property
    def has_pending_definition(self):
        if self.is_agrupamento:
            return False
        if self.origem_modelo and self.origem_modelo.has_flexible_resolution:
            nome_upper = (self.nome_unidade or "").upper()
            nome_pendente = "SETOR OU SEÇÃO" in nome_upper or "SETOR OU SECAO" in nome_upper
            tipo_ids = self.origem_modelo.allowed_tipo_ids
            cargo_ids = self.origem_modelo.allowed_cargo_ids
            tipo_pendente = bool(tipo_ids) and self.tipo_unidade_id not in tipo_ids
            cargo_pendente = bool(cargo_ids) and self.cargo_funcao_ref_id not in cargo_ids
            return nome_pendente or tipo_pendente or cargo_pendente
        if self.tipo_unidade and (self.tipo_unidade.is_generico_pendente or self.tipo_unidade.apenas_modelo_referencial):
            return True
        if self.cargo_funcao_ref and self.cargo_funcao_ref.is_generico_pendente:
            return True
        cargo_upper = (self.cargo_funcao or "").upper()
        if "FG-01 OU FG-02" in cargo_upper:
            return True
        nome_upper = (self.nome_unidade or "").upper()
        return "SETOR OU SEÇÃO" in nome_upper or "SETOR OU SECAO" in nome_upper

    @property
    def competencias_status(self):
        if self.is_agrupamento:
            return 'revisada'
        competencias = list(self.competencias.all())
        if not competencias:
            return 'sem_competencias'
        regimentos = self.organograma.regimentos_competencias_referencia
        if not regimentos:
            return 'desatualizada'
        regimento_ids = {regimento.id for regimento in regimentos}
        if any(c.regimento_id not in regimento_ids for c in competencias):
            return 'desatualizada'
        return 'revisada'

    @property
    def competencias_status_label(self):
        labels = {
            'sem_competencias': 'Sem competências',
            'desatualizada': 'Competências desatualizadas',
            'revisada': 'Competências revisadas',
        }
        return labels.get(self.competencias_status, 'Sem competências')


class CompetenciaUnidade(models.Model):
    unidade = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='competencias')
    regimento = models.ForeignKey(RegimentoCampus, on_delete=models.PROTECT, related_name='competencias_unidades')
    artigo = models.CharField("Artigo", max_length=50, blank=True, default="")
    paragrafo = models.CharField("Parágrafo", max_length=50, blank=True, default="")
    inciso = models.CharField("Inciso", max_length=50, blank=True, default="")
    alinea = models.CharField("Alínea", max_length=50, blank=True, default="")
    texto = models.TextField("Competência")
    ordem = models.PositiveIntegerField("Ordem", default=0)
    revisada_em = models.DateTimeField("Revisada em", null=True, blank=True)
    revisada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='competencias_revisadas')

    class Meta:
        verbose_name = "Competência da Unidade"
        verbose_name_plural = "Competências das Unidades"
        ordering = ['ordem', 'id']

    def __str__(self):
        return f"{self.unidade} - {self.referencia_formatada or 'Sem referência'}"

    @property
    def referencia_formatada(self):
        partes = []
        if self.artigo:
            partes.append(f"Art. {self.artigo}")
        if self.inciso:
            partes.append(f"inciso {self.inciso}")
        if self.alinea:
            partes.append(f"alínea {self.alinea}")
        if self.paragrafo:
            partes.append(f"§ {self.paragrafo}")
        return ", ".join(partes)

    @property
    def esta_atualizada(self):
        regimento_ids = {regimento.id for regimento in self.unidade.organograma.regimentos_competencias_referencia}
        return self.regimento_id in regimento_ids


def _versionar_organograma_oficial_por_novo_regimento(regimento, regimentos_vigentes_anteriores=None):
    if regimento.tipo == 'GERAL' and regimento.campus.sigla != 'IFMG':
        return None

    campo_referencia = 'regimento_referencia' if regimento.tipo == 'INTERNO' else 'regimento_geral_referencia'
    campo_referencia_id = f'{campo_referencia}_id'
    organograma_atual = (
        Organograma.objects
        .filter(campus=regimento.campus, status='OFICIAL')
        .order_by('-id')
        .first()
    )
    if not organograma_atual:
        return None

    if getattr(organograma_atual, campo_referencia_id) == regimento.id:
        return None

    regimento_anterior = None
    regimentos_vigentes_anteriores = regimentos_vigentes_anteriores or []
    if getattr(organograma_atual, campo_referencia_id):
        regimento_anterior = getattr(organograma_atual, campo_referencia)
    elif regimentos_vigentes_anteriores:
        regimento_anterior = regimentos_vigentes_anteriores[0]

    with transaction.atomic():
        if regimento_anterior and not getattr(organograma_atual, campo_referencia_id):
            Organograma.objects.filter(pk=organograma_atual.pk).update(**{campo_referencia_id: regimento_anterior.id})
            setattr(organograma_atual, campo_referencia, regimento_anterior)
            setattr(organograma_atual, campo_referencia_id, regimento_anterior.id)

        novo_organograma = Organograma.objects.create(
            campus=organograma_atual.campus,
            data_vigencia=organograma_atual.data_vigencia,
            documento_aprovacao=organograma_atual.documento_aprovacao,
            nome_documento_aprovacao=organograma_atual.nome_documento_aprovacao,
            resolucao_estrutura=organograma_atual.resolucao_estrutura,
            nome_regimento=organograma_atual.nome_regimento,
            regimento_arquivo=organograma_atual.regimento_arquivo,
            nome_regimento_geral=organograma_atual.nome_regimento_geral,
            regimento_geral_arquivo=organograma_atual.regimento_geral_arquivo,
            regimento_referencia=regimento if regimento.tipo == 'INTERNO' else organograma_atual.regimento_referencia,
            regimento_geral_referencia=regimento if regimento.tipo == 'GERAL' else organograma_atual.regimento_geral_referencia,
            modelo_referencia_atualizado_em=organograma_atual.modelo_referencia_atualizado_em,
            modelo_base=organograma_atual.modelo_base,
            status='OFICIAL',
        )
        novo_organograma.organogramas_vinculados.set(organograma_atual.organogramas_vinculados.all())

        unidades_originais = list(organograma_atual.unidades.all().order_by('ordem', 'id'))
        id_map = {}
        for unidade in unidades_originais:
            nova_unidade = Unit.objects.create(
                organograma=novo_organograma,
                origem_modelo=unidade.origem_modelo,
                nome_unidade=unidade.nome_unidade,
                sigla_unidade=unidade.sigla_unidade,
                tipo_unidade=unidade.tipo_unidade,
                cargo_funcao_ref=unidade.cargo_funcao_ref,
                cargo_funcao=unidade.cargo_funcao,
                sigla_cargo=unidade.sigla_cargo,
                atribuicoes=unidade.atribuicoes,
                ordem=unidade.ordem,
                ligacao_indireta=unidade.ligacao_indireta,
                oculto_no_organograma=unidade.oculto_no_organograma,
                is_agrupamento=unidade.is_agrupamento,
                layout_filhos=unidade.layout_filhos,
            )
            id_map[unidade.id] = nova_unidade

        for unidade in unidades_originais:
            if unidade.unidade_pai_id:
                nova_unidade = id_map[unidade.id]
                nova_unidade.unidade_pai = id_map.get(unidade.unidade_pai_id)
                nova_unidade.save(update_fields=['unidade_pai'])

        for unidade in unidades_originais:
            nova_unidade = id_map[unidade.id]
            for competencia in unidade.competencias.all().order_by('ordem', 'id'):
                CompetenciaUnidade.objects.create(
                    unidade=nova_unidade,
                    regimento=competencia.regimento,
                    artigo=competencia.artigo,
                    paragrafo=competencia.paragrafo,
                    inciso=competencia.inciso,
                    alinea=competencia.alinea,
                    texto=competencia.texto,
                    ordem=competencia.ordem,
                    revisada_em=competencia.revisada_em,
                    revisada_por=competencia.revisada_por,
                )

    return novo_organograma


class SolicitacaoAlteracaoQuerySet(models.QuerySet):
    def delete(self):
        proposal_ids = list(
            self.filter(organograma_proposto__status='PROPOSTA')
            .values_list('organograma_proposto_id', flat=True)
        )
        result = super().delete()
        if proposal_ids:
            Organograma.objects.filter(
                id__in=proposal_ids,
                status='PROPOSTA',
                solicitacoes_proposta__isnull=True,
            ).delete()
        return result


class SolicitacaoAlteracao(models.Model):
    STATUS_CHOICES = [
        ('RASCUNHO', 'Rascunho'),
        ('EM_ANALISE', 'Em Análise'),
        ('ENVIADO_CONSUP', 'Enviado para Aprovação no CONSUP'),
        ('DEVOLVIDO_CORRECAO', 'Devolvido para Correção'),
        ('APROVADO', 'Aprovado'),
        ('REJEITADO', 'Rejeitado'),
    ]
    organograma_original = models.ForeignKey(Organograma, on_delete=models.CASCADE, related_name='solicitacoes_origem')
    organograma_proposto = models.ForeignKey(Organograma, on_delete=models.CASCADE, related_name='solicitacoes_proposta')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='solicitacoes')
    justificativa = models.TextField("Justificativa da Alteração")
    justificativa_avaliador = models.TextField("Justificativa do Avaliador", blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RASCUNHO')
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)

    objects = SolicitacaoAlteracaoQuerySet.as_manager()

    class Meta:
        verbose_name = "Solicitação de Alteração"
        verbose_name_plural = "Solicitações de Alteração"

    def __str__(self):
        return f"Solicitação #{self.id} - {self.organograma_original.campus.sigla} - {self.get_status_display()}"

    def delete(self, *args, **kwargs):
        proposal = self.organograma_proposto
        result = super().delete(*args, **kwargs)
        if proposal.status == 'PROPOSTA' and not proposal.solicitacoes_proposta.exists():
            proposal.delete()
        return result


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    campus = models.ForeignKey(Campus, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Campus Responsável")

    def __str__(self):
        return f"{self.user.username} - {self.campus.sigla if self.campus else 'Geral'}"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.get_or_create(user=instance)
    instance.profile.save()

class ModeloReferencial(models.Model):
    nome = models.CharField("Nome do Modelo", max_length=255)
    dimensionamento = models.ForeignKey(Dimensionamento, on_delete=models.CASCADE, verbose_name="Dimensionamento")
    descricao = models.TextField("Descrição", null=True, blank=True)
    resolucao_referencia = models.CharField("Resolução de Referência", max_length=255, blank=True, default="")
    ativo = models.BooleanField(default=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Modelo Referencial"
        verbose_name_plural = "Modelos Referenciais"

    def __str__(self):
        dim_nome = self.dimensionamento.nome if self.dimensionamento_id else "Sem dimensionamento"
        return f"{self.nome} ({dim_nome})"


class ModeloReferencialCotaCargo(models.Model):
    modelo_referencial = models.ForeignKey(
        ModeloReferencial,
        on_delete=models.CASCADE,
        related_name='cotas_cargos',
        verbose_name="Modelo Referencial",
    )
    cargo_funcao = models.ForeignKey(
        CargoFuncao,
        on_delete=models.CASCADE,
        related_name='cotas_modelos_referenciais',
        verbose_name="Cargo/Função",
    )
    quantidade = models.PositiveIntegerField(
        "Quantidade",
        validators=[MinValueValidator(0)],
        default=0,
    )

    class Meta:
        verbose_name = "Cota de Cargo/Função do Modelo"
        verbose_name_plural = "Cotas de Cargos/Funções do Modelo"
        unique_together = ('modelo_referencial', 'cargo_funcao')
        ordering = ['cargo_funcao__sigla']

    def __str__(self):
        return f"{self.modelo_referencial.nome} - {self.cargo_funcao.sigla}: {self.quantidade}"


class CampusCotaCargo(models.Model):
    campus = models.ForeignKey(
        Campus,
        on_delete=models.CASCADE,
        related_name='cotas_cargos',
        verbose_name="Campus",
    )
    cargo_funcao = models.ForeignKey(
        CargoFuncao,
        on_delete=models.CASCADE,
        related_name='cotas_campi',
        verbose_name="Cargo/Função",
    )
    quantidade = models.PositiveIntegerField(
        "Quantidade",
        validators=[MinValueValidator(0)],
        default=0,
    )

    class Meta:
        verbose_name = "Cota de Cargo/Função do Campus"
        verbose_name_plural = "Cotas de Cargos/Funções do Campus"
        unique_together = ('campus', 'cargo_funcao')
        ordering = ['cargo_funcao__sigla']

    def __str__(self):
        return f"{self.campus.sigla} - {self.cargo_funcao.sigla}: {self.quantidade}"


class UnitModelo(models.Model):
    modelo = models.ForeignKey(ModeloReferencial, on_delete=models.CASCADE, related_name='unidades')
    unidade_pai = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='sub_unidades')
    
    nome_unidade = models.CharField("Nome da Unidade Organizacional", max_length=255)
    sigla_unidade = models.CharField("Sigla da Unidade", max_length=50, blank=True, null=True)
    
    tipo_unidade = models.ForeignKey(TipoUnidade, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Tipo de Departamento")
    cargo_funcao_ref = models.ForeignKey(CargoFuncao, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Cargo ou Função Relacionada")
    
    # Campos para customização (ex: tipo Outro)
    cargo_funcao = models.CharField("Cargo ou Função Relacionada", max_length=255, null=True, blank=True)
    sigla_cargo = models.CharField("Sigla do Cargo/Função", max_length=50, null=True, blank=True)
    
    atribuicoes = models.TextField("Atribuições do Departamento", null=True, blank=True)
    ordem = models.IntegerField("Ordem", default=0)

    is_agrupamento = models.BooleanField(
        default=False,
        verbose_name="É Agrupamento Visual?",
    )

    layout_filhos = models.CharField(
        max_length=1,
        choices=[('H', 'Horizontal'), ('V', 'Vertical')],
        default='V',
        verbose_name="Layout dos Filhos",
    )
    permite_resolucao_flexivel = models.BooleanField(
        default=False,
        verbose_name="Permite Resolução Flexível no Campus",
        help_text="Quando marcado, esta unidade pode ser resolvida no campus com um conjunto restrito de tipos e cargos."
    )
    tipos_resolucao_permitidos = models.ManyToManyField(
        TipoUnidade,
        blank=True,
        related_name='unidades_modelo_resolucao_tipo',
        verbose_name="Tipos Permitidos para Resolução"
    )
    cargos_resolucao_permitidos = models.ManyToManyField(
        CargoFuncao,
        blank=True,
        related_name='unidades_modelo_resolucao_cargo',
        verbose_name="Cargos Permitidos para Resolução"
    )

    class Meta:
        verbose_name = "Unidade do Modelo"
        verbose_name_plural = "Unidades do Modelo"
        ordering = ['ordem', 'id']

    def __str__(self):
        return f"{self.nome_unidade} ({self.modelo.nome})"

    @property
    def has_flexible_resolution(self):
        return self.permite_resolucao_flexivel and (
            self.tipos_resolucao_permitidos.exists() or self.cargos_resolucao_permitidos.exists()
        )

    @property
    def allowed_tipo_ids(self):
        return list(self.tipos_resolucao_permitidos.values_list('id', flat=True))

    @property
    def allowed_cargo_ids(self):
        return list(self.cargos_resolucao_permitidos.values_list('id', flat=True))

    @property
    def has_pending_definition(self):
        if self.is_agrupamento:
            return False
        if self.has_flexible_resolution:
            return True
        if self.tipo_unidade and (self.tipo_unidade.is_generico_pendente or self.tipo_unidade.apenas_modelo_referencial):
            return True
        if self.cargo_funcao_ref and self.cargo_funcao_ref.is_generico_pendente:
            return True
        cargo_upper = (self.cargo_funcao or "").upper()
        if "FG-01 OU FG-02" in cargo_upper:
            return True
        nome_upper = (self.nome_unidade or "").upper()
        return "SETOR OU SEÇÃO" in nome_upper or "SETOR OU SECAO" in nome_upper


class RegrasAlteracaoModelo(models.Model):
    modelo_referencial = models.OneToOneField(ModeloReferencial, on_delete=models.CASCADE, related_name='regras_alteracao', verbose_name="Modelo Referencial")
    limite_total_alteracoes = models.IntegerField("Limite Total de Alterações", default=6)
    exige_vinculo_com_modelo = models.BooleanField("Exigir vínculo com unidades do modelo", default=True)
    exigir_adequacao_quando_modelo_mudar = models.BooleanField("Exigir adequação quando o modelo mudar", default=False)
    permite_renomeacao = models.BooleanField("Permite renomeação", default=True)
    limite_renomeacao = models.IntegerField("Limite de renomeações", default=3)
    permite_mudanca_vinculo = models.BooleanField("Permite mudança de vínculo", default=True)
    limite_mudanca_vinculo = models.IntegerField("Limite de mudanças de vínculo", default=3)
    permite_alteracao_cargo = models.BooleanField("Permite alteração de cargo", default=True)
    limite_alteracao_cargo = models.IntegerField("Limite de alterações de cargo", default=3)
    permite_alteracao_tipo_unidade = models.BooleanField("Permite alteração de tipo de unidade", default=True)
    limite_alteracao_tipo_unidade = models.IntegerField("Limite de alterações de tipo", default=3)
    permite_alteracao_sigla = models.BooleanField("Permite alteração de sigla", default=True)
    limite_alteracao_sigla = models.IntegerField("Limite de alterações de sigla", default=3)
    permite_exclusao_unidade_modelo = models.BooleanField("Permite exclusão de unidade do modelo", default=True)
    limite_exclusao_unidade_modelo = models.IntegerField("Limite de exclusões de unidades do modelo", default=3)
    permite_inclusao_unidade_nova = models.BooleanField("Permite inclusão de unidade nova", default=True)
    limite_inclusao_unidade_nova = models.IntegerField("Limite de inclusões de unidades novas", default=3)
    
    limite_flexibilizacao_fg = models.IntegerField(
        "Limite Quantitativo de FGs (25%)", 
        default=3, 
        help_text="Limite inteiro da cota de 25% da Resolução CONSUP nº 44/2025 para alteração de nomenclatura e/ou vinculação de unidades com FG."
    )
    permite_regra_transicao = models.BooleanField(
        "Permitir Regra de Transição (Dim. 40/26)", 
        default=False, 
        help_text="Aplica somente ao dimensionamento 40/26 e eleva temporariamente a cota normativa para até 5 alterações, conforme a Resolução CONSUP nº 44/2025."
    )
    
    prefixos_cargos_bloqueados = models.CharField(
        "Prefixos de Cargos Bloqueados", 
        max_length=255, 
        default="CD",
        help_text="Prefixos de cargos de direção que não admitem flexibilização, conforme a Resolução CONSUP nº 44/2025. Ex: CD."
    )
    
    prefixos_cargos_flexibilizaveis = models.CharField(
        "Prefixos Inclusos na Contabilização", 
        max_length=255, 
        default="FG",
        help_text="Prefixos de funções gratificadas que entram na cota de 25% da Resolução CONSUP nº 44/2025. Ex: FG."
    )
    
    departamentos_intocaveis = models.TextField(
        "Departamentos Restritos à Mudança de Vinculação", 
        default="Gestão de Pessoas, Tecnologia da Informação, Assuntos Institucionais",
        help_text="Unidades que, pela Resolução CONSUP nº 44/2025, são flexíveis apenas quanto à vinculação."
    )
    
    verificar_sufixo_anexo = models.BooleanField(
        "Exigir Preservação de Prefixo (Anexo VII)", 
        default=True, 
        help_text="Exige preservação dos prefixos de nomenclatura do Anexo VII da Resolução CONSUP nº 44/2025."
    )

    class Meta:
        verbose_name = "Regras de Alteração do Modelo"
        verbose_name_plural = "Regras de Alteração"

    def __str__(self):
        return f"Regras do {self.modelo_referencial.nome}"


class ExcecaoRegraAlteracaoCampus(models.Model):
    modelo_referencial = models.ForeignKey(ModeloReferencial, on_delete=models.CASCADE, related_name='excecoes_campus', verbose_name="Modelo Referencial")
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='excecoes_regras_modelo', verbose_name="Campus")
    limite_total_alteracoes = models.IntegerField("Limite Total de Alterações", null=True, blank=True)
    exige_vinculo_com_modelo = models.BooleanField("Exigir vínculo com unidades do modelo", null=True, blank=True)
    exigir_adequacao_quando_modelo_mudar = models.BooleanField("Exigir adequação quando o modelo mudar", null=True, blank=True)
    permite_renomeacao = models.BooleanField("Permite renomeação", null=True, blank=True)
    limite_renomeacao = models.IntegerField("Limite de renomeações", null=True, blank=True)
    permite_mudanca_vinculo = models.BooleanField("Permite mudança de vínculo", null=True, blank=True)
    limite_mudanca_vinculo = models.IntegerField("Limite de mudanças de vínculo", null=True, blank=True)
    permite_alteracao_cargo = models.BooleanField("Permite alteração de cargo", null=True, blank=True)
    limite_alteracao_cargo = models.IntegerField("Limite de alterações de cargo", null=True, blank=True)
    permite_alteracao_tipo_unidade = models.BooleanField("Permite alteração de tipo de unidade", null=True, blank=True)
    limite_alteracao_tipo_unidade = models.IntegerField("Limite de alterações de tipo", null=True, blank=True)
    permite_alteracao_sigla = models.BooleanField("Permite alteração de sigla", null=True, blank=True)
    limite_alteracao_sigla = models.IntegerField("Limite de alterações de sigla", null=True, blank=True)
    permite_exclusao_unidade_modelo = models.BooleanField("Permite exclusão de unidade do modelo", null=True, blank=True)
    limite_exclusao_unidade_modelo = models.IntegerField("Limite de exclusões de unidades do modelo", null=True, blank=True)
    permite_inclusao_unidade_nova = models.BooleanField("Permite inclusão de unidade nova", null=True, blank=True)
    limite_inclusao_unidade_nova = models.IntegerField("Limite de inclusões de unidades novas", null=True, blank=True)

    class Meta:
        verbose_name = "Exceção de Regra por Campus"
        verbose_name_plural = "Exceções de Regra por Campus"
        unique_together = ('modelo_referencial', 'campus')

    def __str__(self):
        return f"{self.campus.sigla} - {self.modelo_referencial.nome}"

