import json
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.db import transaction, models
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .models import Campus, Organograma, Unit, SolicitacaoAlteracao, CargoFuncao, TipoUnidade, ModeloReferencial, UnitModelo, Dimensionamento, RegrasAlteracaoModelo, RegimentoCampus, ResolucaoEstruturaOrganizacional, CompetenciaUnidade
from .forms import OrganogramaForm, UnitForm, CargoFuncaoForm, TipoUnidadeForm, ModeloReferencialForm, UnitModeloForm, RegrasAlteracaoModeloForm, ModeloReferencialCotaCargoFormSet, RegimentoCampusForm, ResolucaoEstruturaOrganizacionalForm, CompetenciaUnidadeForm
from .services.competencias_import import parse_competencias_file
from .services.governance import apply_rule_defaults, validate_organograma_governance


def _get_safe_next_url(request):
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def _get_organogramas_vinculados_unicos(organograma):
    return (
        Organograma.objects.filter(
            models.Q(vinculados_por=organograma)
            | models.Q(organogramas_vinculados=organograma),
            status='OFICIAL',
        )
        .exclude(pk=organograma.pk)
        .select_related('campus')
        .distinct()
        .order_by('campus__nome', 'pk')
    )


def _redirect_with_fallback(request, fallback_name, **kwargs):
    next_url = _get_safe_next_url(request)
    if next_url:
        return redirect(next_url)
    return redirect(fallback_name, **kwargs)


def check_solicitacao_access(user, solicitacao):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if solicitacao.usuario == user:
        return True
    if user.is_staff:
        # Admin limitado não pode acessar RASCUNHO criado por usuário de campus
        is_campus_draft = (solicitacao.status == 'RASCUNHO' and 
                           getattr(solicitacao.usuario, 'profile', None) and 
                           solicitacao.usuario.profile.campus is not None)
        return not is_campus_draft
    return False



def _competencia_to_dict(competencia):
    regimento_url = competencia.regimento.arquivo.url if competencia.regimento.arquivo else (competencia.regimento.link or '')
    return {
        'id': str(competencia.id),
        'regimentoId': str(competencia.regimento_id),
        'regimentoNome': str(competencia.regimento),
        'regimentoTipo': competencia.regimento.get_tipo_display(),
        'regimentoUrl': regimento_url,
        'referencia': competencia.referencia_formatada,
        'artigo': competencia.artigo,
        'paragrafo': competencia.paragrafo,
        'inciso': competencia.inciso,
        'alinea': competencia.alinea,
        'texto': competencia.texto,
        'ordem': competencia.ordem,
        'atualizada': competencia.esta_atualizada,
    }


def _competencias_payload(unidade):
    return [
        _competencia_to_dict(competencia)
        for competencia in unidade.competencias.select_related('regimento').order_by('ordem', 'id')
    ]


def _competencias_diff_text(unidade):
    competencias = []
    for competencia in unidade.competencias.select_related('regimento').order_by('ordem', 'id'):
        referencia = competencia.referencia_formatada
        if referencia:
            competencias.append(f"{referencia}: {competencia.texto}")
        else:
            competencias.append(competencia.texto)
    return "\n".join(competencias) if competencias else "Nenhuma"


def _competencias_signature(unidade):
    return [
        (
            competencia.regimento_id,
            competencia.artigo or '',
            competencia.paragrafo or '',
            competencia.inciso or '',
            competencia.alinea or '',
            competencia.texto or '',
            competencia.ordem,
        )
        for competencia in unidade.competencias.order_by('ordem', 'id')
    ]


def _proposal_non_competency_changes(solicitacao):
    original_units = list(solicitacao.organograma_original.unidades.select_related('unidade_pai').order_by('ordem', 'id'))
    proposal_units = list(solicitacao.organograma_proposto.unidades.select_related('source_unit', 'unidade_pai').order_by('ordem', 'id'))

    proposal_by_source = {unit.source_unit_id: unit for unit in proposal_units if unit.source_unit_id}
    if len(proposal_by_source) != len(proposal_units):
        return True
    if set(proposal_by_source) != {unit.id for unit in original_units}:
        return True

    comparable_fields = [
        'nome_unidade',
        'sigla_unidade',
        'tipo_unidade_id',
        'cargo_funcao_ref_id',
        'cargo_funcao',
        'sigla_cargo',
        'atribuicoes',
        'ordem',
        'ligacao_indireta',
        'oculto_no_organograma',
        'is_agrupamento',
        'layout_filhos',
    ]
    for original in original_units:
        proposal = proposal_by_source[original.id]
        for field in comparable_fields:
            if (getattr(original, field) or '') != (getattr(proposal, field) or ''):
                return True
        original_parent_id = original.unidade_pai_id
        proposal_parent_source_id = proposal.unidade_pai.source_unit_id if proposal.unidade_pai_id else None
        if original_parent_id != proposal_parent_source_id:
            return True
    return False


def _proposal_competency_changes(solicitacao):
    for proposal in solicitacao.organograma_proposto.unidades.select_related('source_unit').order_by('ordem', 'id'):
        if not proposal.source_unit_id:
            return True
        if _competencias_signature(proposal) != _competencias_signature(proposal.source_unit):
            return True
    return False


def _regimento_to_dict(regimento):
    return {
        'id': str(regimento.id),
        'nome': str(regimento),
        'tipo': regimento.tipo,
        'tipoLabel': regimento.get_tipo_display(),
        'url': regimento.arquivo.url if regimento.arquivo else (regimento.link or ''),
    }


def _resolve_competencia_regimento(request, organograma):
    regimentos = organograma.regimentos_competencias_referencia
    if not regimentos:
        return None
    if len(regimentos) == 1:
        return regimentos[0]
    selected_id = request.POST.get('regimento_id')
    if selected_id:
        for regimento in regimentos:
            if str(regimento.id) == str(selected_id):
                return regimento
    return None


def _governance_json_error(validation_result, status=400):
    html = validation_result.get('html') or "<br>".join(validation_result.get('errors', []))
    return JsonResponse({'status': 'error', 'html': html, 'errors': {'__all__': validation_result.get('errors', [])}}, status=status)


def _allows_structure_changes(organograma):
    return organograma.status != 'PROPOSTA'


def _proposal_request(organograma):
    return organograma.solicitacoes_proposta.order_by('-data_atualizacao', '-id').first()


def _allows_unit_metadata_changes(organograma):
    related_solicitacao = _proposal_request(organograma)
    return not related_solicitacao or related_solicitacao.status in ['RASCUNHO', 'DEVOLVIDO_CORRECAO']


def _structure_change_blocked_response(request, organograma):
    message = (
        'Solicitações de alteração não permitem incluir, excluir, agrupar ou desagrupar caixinhas. '
        'A proposta deve manter as unidades do organograma/modelo e ajustar apenas os campos permitidos pela Resolução CONSUP nº 44/2025.'
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'error', 'html': message, 'errors': {'__all__': [message]}}, status=403)
    messages.error(request, message)
    return redirect('organograma_build', pk=organograma.pk)


def _proposal_locked_response(request, organograma):
    message = (
        'Esta proposta esta aguardando analise e nao pode ser alterada. '
        'Aguarde a avaliacao ou a devolucao para correcao.'
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'error', 'html': message, 'errors': {'__all__': [message]}}, status=403)
    messages.error(request, message)
    return redirect('organograma_build', pk=organograma.pk)


def _validate_final_consup_resolution(solicitacao):
    proposal = solicitacao.organograma_proposto
    original = solicitacao.organograma_original
    if not proposal.resolucao_estrutura_id:
        return 'Selecione a resolucao da estrutura aprovada pelo CONSUP antes da aprovacao final.'
    if proposal.resolucao_estrutura.campus_id != proposal.campus_id:
        return 'A resolucao selecionada pertence a outro campus.'
    if original.resolucao_estrutura_id and proposal.resolucao_estrutura_id == original.resolucao_estrutura_id:
        return 'A aprovacao final exige uma nova resolucao da estrutura, diferente da resolucao vigente.'
    return None


def _validate_final_normative_documents(solicitacao):
    if _proposal_non_competency_changes(solicitacao):
        return _validate_final_consup_resolution(solicitacao)

    if not _proposal_competency_changes(solicitacao):
        return None

    original = solicitacao.organograma_original
    proposal = solicitacao.organograma_proposto
    if proposal.campus.sigla == 'IFMG':
        if not proposal.regimento_geral_referencia_id:
            return 'Selecione o novo Regimento Geral de referencia antes da aprovacao final.'
        if proposal.regimento_geral_referencia_id == original.regimento_geral_referencia_id:
            return 'A aprovacao final de alteracoes apenas de competencias exige um novo Regimento Geral de referencia.'
        return None

    if not proposal.regimento_referencia_id:
        return 'Selecione o novo Regimento Interno de referencia antes da aprovacao final.'
    if proposal.regimento_referencia_id == original.regimento_referencia_id:
        return 'A aprovacao final de alteracoes apenas de competencias exige um novo Regimento Interno de referencia.'
    return None


def _apply_governance_guard(request, organograma, validation_result):
    if not validation_result.get('errors'):
        return None
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return _governance_json_error(validation_result)
    for error in validation_result['errors']:
        messages.error(request, error)
    return redirect('organograma_build', pk=organograma.pk)


def _filter_value(request, name):
    return (request.GET.get(name) or '').strip()


def _has_file_or_link(field_name):
    return models.Q(**{f'{field_name}__isnull': False}) & ~models.Q(**{field_name: ''})


def _organograma_doc_query(kind):
    if kind == 'resolucao':
        return models.Q(resolucao_estrutura__isnull=False) | _has_file_or_link('documento_aprovacao')
    if kind == 'regimento_interno':
        return models.Q(regimento_referencia__isnull=False) | _has_file_or_link('regimento_arquivo')
    if kind == 'regimento_geral':
        return _has_file_or_link('regimento_geral_arquivo')
    return models.Q()


def _filter_context():
    return {
        'campus_options': Campus.objects.all().order_by('nome'),
        'dimensionamento_options': Dimensionamento.objects.all().order_by('nome'),
        'modelo_options': ModeloReferencial.objects.all().order_by('nome'),
    }


def _apply_common_organograma_filters(queryset, request):
    q = _filter_value(request, 'q')
    campus = _filter_value(request, 'campus')
    dimensionamento = _filter_value(request, 'dimensionamento')
    modelo = _filter_value(request, 'modelo')
    documento = _filter_value(request, 'documento')
    doc_status = _filter_value(request, 'doc_status')

    if q:
        queryset = queryset.filter(
            models.Q(campus__nome__icontains=q) |
            models.Q(campus__sigla__icontains=q) |
            models.Q(resolucao_estrutura__nome__icontains=q) |
            models.Q(resolucao_estrutura__numero__icontains=q) |
            models.Q(nome_documento_aprovacao__icontains=q)
        )
    if campus:
        queryset = queryset.filter(campus_id=campus)
    if dimensionamento:
        queryset = queryset.filter(
            models.Q(campus__dimensionamento_fk_id=dimensionamento) |
            models.Q(campus__dimensionamento=dimensionamento)
        )
    if modelo:
        queryset = queryset.filter(
            models.Q(modelo_base_id=modelo) |
            models.Q(campus__modelo_referencial_padrao_id=modelo)
        )
    if documento:
        queryset = queryset.filter(_organograma_doc_query(documento))
    if doc_status == 'com_documento':
        queryset = queryset.filter(
            _organograma_doc_query('resolucao') |
            _organograma_doc_query('regimento_interno') |
            _organograma_doc_query('regimento_geral')
        )
    elif doc_status == 'sem_documento':
        queryset = queryset.exclude(
            _organograma_doc_query('resolucao') |
            _organograma_doc_query('regimento_interno') |
            _organograma_doc_query('regimento_geral')
        )
    return queryset


def _apply_organograma_order(queryset, request):
    ordenar = _filter_value(request, 'ordenar')
    if not ordenar or ordenar == 'campus':
        return queryset.order_by('campus__nome', '-id')
    if ordenar == 'antigos':
        return queryset.order_by('id')
    return queryset.order_by('-id')


def _filter_organogramas_by_pending(items, pendencia):
    if not pendencia:
        return list(items)
    filtered = []
    for org in items:
        if pendencia == 'adequacao_modelo' and org.precisa_adequacao_modelo:
            filtered.append(org)
        elif pendencia == 'competencias' and org.competencias_resumo.get('tem_alertas'):
            filtered.append(org)
        elif pendencia == 'unidades_genericas' and org.has_pending_units:
            filtered.append(org)
    return filtered


def organograma_list(request):
    base_qs = Organograma.objects.select_related(
        'campus',
        'campus__dimensionamento_fk',
        'campus__modelo_referencial_padrao',
        'modelo_base',
        'resolucao_estrutura',
        'regimento_referencia',
    ).prefetch_related('unidades', 'solicitacoes_origem')
    status_filter = _filter_value(request, 'status')
    scope = _filter_value(request, 'scope')
    pendencia = _filter_value(request, 'pendencia')

    organogramas = base_qs.filter(status='OFICIAL')
    rascunhos = Organograma.objects.none()
    
    if request.user.is_authenticated:
        if request.user.is_superuser or request.user.is_staff:
            rascunhos = base_qs.filter(status='RASCUNHO')
        else:
            profile = getattr(request.user, 'profile', None)
            if profile and profile.campus:
                rascunhos = base_qs.filter(campus=profile.campus, status='RASCUNHO')
        if scope == 'meu_campus':
            profile = getattr(request.user, 'profile', None)
            if profile and profile.campus:
                organogramas = organogramas.filter(campus=profile.campus)
                rascunhos = rascunhos.filter(campus=profile.campus)
        elif scope == 'meus_rascunhos':
            organogramas = Organograma.objects.none()
    else:
        status_filter = ''

    organogramas = _apply_common_organograma_filters(organogramas, request)
    rascunhos = _apply_common_organograma_filters(rascunhos, request)

    if status_filter == 'rascunho':
        organogramas = Organograma.objects.none()
    elif status_filter == 'oficial':
        rascunhos = Organograma.objects.none()
    elif status_filter == 'oficial_com_proposta':
        organogramas = organogramas.filter(solicitacoes_origem__status__in=['EM_ANALISE', 'ENVIADO_CONSUP']).distinct()
        rascunhos = Organograma.objects.none()

    organogramas = _filter_organogramas_by_pending(_apply_organograma_order(organogramas, request), pendencia)
    rascunhos = _filter_organogramas_by_pending(_apply_organograma_order(rascunhos, request), pendencia)

    context = {
        'organogramas': organogramas,
        'rascunhos': rascunhos,
        'filters': request.GET,
    }
    context.update(_filter_context())
    return render(request, 'core/organograma_list.html', context)

def historico_list(request):
    from collections import defaultdict

    base_qs = Organograma.objects.select_related(
        'campus',
        'campus__dimensionamento_fk',
        'campus__modelo_referencial_padrao',
        'modelo_base',
        'resolucao_estrutura',
        'regimento_referencia',
    ).prefetch_related('unidades').filter(status='HISTORICO')

    version_groups = defaultdict(list)
    for org in base_qs.order_by('campus__nome', 'id'):
        version_groups[org.campus].append(org)

    versioned = []
    for campus, org_list in version_groups.items():
        for idx, org in enumerate(org_list):
            org.versao_calculada = f"v{idx + 1}"
            versioned.append(org)

    organogramas = _apply_common_organograma_filters(base_qs, request)
    data_inicio = _filter_value(request, 'data_inicio')
    data_fim = _filter_value(request, 'data_fim')
    versao = _filter_value(request, 'versao').lower()
    if data_inicio:
        organogramas = organogramas.filter(data_aprovacao_sistema__date__gte=data_inicio)
    if data_fim:
        organogramas = organogramas.filter(data_aprovacao_sistema__date__lte=data_fim)

    allowed_ids = set(organogramas.values_list('id', flat=True))
    filtered = [org for org in versioned if org.id in allowed_ids]
    if versao:
        filtered = [org for org in filtered if org.versao_calculada.lower() == versao]

    campus_groups = defaultdict(list)
    for org in filtered:
        campus_groups[org.campus].append(org)

    ordenar = _filter_value(request, 'ordenar_historico')
    for campus, org_list in campus_groups.items():
        if ordenar == 'versao_antiga':
            org_list.sort(key=lambda org: org.id)
        elif ordenar == 'data_recente':
            org_list.sort(
                key=lambda org: (
                    bool(org.data_aprovacao_sistema),
                    org.data_aprovacao_sistema or timezone.datetime.min.replace(tzinfo=timezone.get_current_timezone()),
                    org.id,
                ),
                reverse=True,
            )
        elif ordenar == 'data_antiga':
            org_list.sort(
                key=lambda org: (
                    not bool(org.data_aprovacao_sistema),
                    org.data_aprovacao_sistema or timezone.datetime.max.replace(tzinfo=timezone.get_current_timezone()),
                    org.id,
                )
            )
        else:
            org_list.sort(key=lambda org: org.id, reverse=True)

    context = {
        'campus_groups': dict(campus_groups),
        'filters': request.GET,
    }
    context.update(_filter_context())
    return render(request, 'core/historico_list.html', context)

def organograma_detail(request, pk):
    organograma = get_object_or_404(Organograma, pk=pk)
    next_url = _get_safe_next_url(request)
    related_solicitacao = organograma.solicitacoes_proposta.order_by('-data_atualizacao', '-id').first()
    
    # Segurança de Visualização
    if organograma.status != 'OFICIAL':
        if not request.user.is_authenticated:
            raise PermissionDenied("Acesso restrito.")
        if not request.user.is_staff:
            profile = getattr(request.user, 'profile', None)
            if not profile or profile.campus != organograma.campus:
                raise PermissionDenied("Acesso restrito ao Responsável pelo Campus.")
        if organograma.status == 'PROPOSTA' and related_solicitacao:
            if not check_solicitacao_access(request.user, related_solicitacao):
                raise PermissionDenied("Acesso restrito.")
    
    linked_orgs = _get_organogramas_vinculados_unicos(organograma)

    # Todos os outros organogramas oficiais para o cluster
    outros_orgs = Organograma.objects.filter(status='OFICIAL').exclude(pk=organograma.id).order_by('campus__nome')
    todos_campi_data = [{'sigla': o.campus.sigla, 'url': f"/organograma/{o.id}/"} for o in outros_orgs]

    unidades_data = _get_unidades_json_data(organograma.unidades.all())

    context = {
        'organograma': organograma,
        'unidades_json': json.dumps(unidades_data),
        'linked_orgs': linked_orgs,
        'todos_campi_json': json.dumps(todos_campi_data),
        'next_url': next_url,
        'show_solicitacao_backlink': next_url == reverse('solicitacao_list'),
        'related_solicitacao': related_solicitacao,
        'competencias_resumo': organograma.competencias_resumo,
        'regimento_competencias': organograma.regimento_competencias_referencia,
        'regimentos_competencias': organograma.regimentos_competencias_referencia,
        'show_competencias_pendencias': request.user.is_authenticated,
        'organograma_export_filename': f'organograma-{organograma.campus.sigla}',
    }
    return render(request, 'core/organograma_detail.html', context)


@login_required(login_url='/admin/login/')
def organograma_create(request):
    if not request.user.is_staff:
        raise PermissionDenied("Apenas administradores podem criar novos organogramas.")
        
    if request.method == 'POST':
        form = OrganogramaForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                org = form.save(commit=False)
                modelo = form.cleaned_data.get('modelo_referencial')
                usar_modelo = form.cleaned_data.get('utilizar_modelo')
                org.modelo_base = modelo
                org.save()
                if modelo:
                    org.modelo_referencia_atualizado_em = modelo.data_atualizacao
                    org.save(update_fields=['modelo_referencia_atualizado_em'])
                    if not org.campus.modelo_referencial_padrao_id:
                        org.campus.modelo_referencial_padrao = modelo
                        org.campus.save(update_fields=['modelo_referencial_padrao'])
                
                if modelo and usar_modelo:
                    # Clonagem da Estrutura do Modelo
                    unidades_modelo = modelo.unidades.all()
                    id_map = {} # Antigo ID Modelo -> Nova Instância Unit
                    
                    # 1. Criar as instâncias básicas
                    prefix = org.campus.get_sigla_prefix
                    for um in unidades_modelo:
                        sigla_final = um.sigla_unidade
                        if sigla_final and prefix:
                            sigla_final = f"{prefix}-{sigla_final}"
                        tipo_unidade = None if um.has_flexible_resolution else um.tipo_unidade
                        cargo_funcao_ref = None if um.has_flexible_resolution else um.cargo_funcao_ref
                            
                        new_u = Unit.objects.create(
                            organograma=org,
                            origem_modelo=um,
                            nome_unidade=um.nome_unidade,
                            sigla_unidade=sigla_final,
                            tipo_unidade=tipo_unidade,
                            cargo_funcao_ref=cargo_funcao_ref,
                            cargo_funcao=um.cargo_funcao,
                            sigla_cargo=um.sigla_cargo,
                            atribuicoes=um.atribuicoes,
                            ordem=um.ordem,
                            is_agrupamento=um.is_agrupamento,
                            layout_filhos=um.layout_filhos
                        )
                        id_map[um.id] = new_u
                    
                    # 2. Reconstruir Hierarquia
                    for um in unidades_modelo:
                        if um.unidade_pai_id:
                            new_u = id_map[um.id]
                            new_u.unidade_pai = id_map[um.unidade_pai_id]
                            new_u.save()
                            
                    messages.success(request, f'Organograma criado com sucesso a partir do modelo "{modelo.nome}"!')
                else:
                    messages.success(request, f'Organograma criado com sucesso! O modelo de referência "{modelo.nome}" será usado para validar a estrutura.')
                
                return redirect('organograma_build', pk=org.pk)
    else:
        form = OrganogramaForm(initial={'status': 'RASCUNHO'})
    
    return render(request, 'core/organograma_form.html', {'form': form})

@login_required(login_url='/admin/login/')
def organograma_edit(request, pk):
    organograma = get_object_or_404(Organograma, pk=pk)
    related_solicitacao = _proposal_request(organograma)

    if request.user.is_staff:
        if related_solicitacao and not check_solicitacao_access(request.user, related_solicitacao):
            raise PermissionDenied("Você não tem permissão para editar metadados deste organograma.")

    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if (
            organograma.status != 'PROPOSTA'
            or not related_solicitacao
            or related_solicitacao.status not in ['RASCUNHO', 'DEVOLVIDO_CORRECAO']
            or not profile
            or profile.campus != organograma.campus
            or related_solicitacao.usuario != request.user
        ):
            raise PermissionDenied("Você não tem permissão para editar metadados deste organograma.")
    
    if request.method == 'POST':
        form = OrganogramaForm(request.POST, request.FILES, instance=organograma)
        if form.is_valid():
            org = form.save(commit=False)
            modelo = form.cleaned_data.get('modelo_referencial') or organograma.modelo_referencial_efetivo
            if modelo:
                org.modelo_base = modelo
            org.save()
            messages.success(request, 'Metadados do organograma atualizados com sucesso!')
            next_url = _get_safe_next_url(request)
            if next_url:
                return redirect(next_url)
            if org.status == 'PROPOSTA':
                return redirect('organograma_build', pk=org.pk)
            return redirect('organograma_list')
    else:
        form = OrganogramaForm(instance=organograma)
    
    return render(request, 'core/organograma_form.html', {
        'form': form,
        'is_edit': True,
        'organograma': organograma,
        'related_solicitacao': related_solicitacao,
        'next_url': _get_safe_next_url(request),
    })

@login_required(login_url='/admin/login/')
def organograma_publish(request, pk):
    organograma = get_object_or_404(Organograma, pk=pk, status='RASCUNHO')
    
    # Segurança de Campus
    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != organograma.campus:
            raise PermissionDenied("Sem permissão para publicar.")

    # Validação de Unidades Genéricas antes de publicar
    unidades_genericas = [u for u in organograma.unidades.all() if u.has_pending_definition]
    if unidades_genericas:
        nomes = ", ".join([u.nome_unidade for u in unidades_genericas[:3]])
        if len(unidades_genericas) > 3:
            nomes += "..."
        messages.error(request, f"O organograma não pode ser publicado pois contém unidades genéricas: {nomes}. "
                               f"Por favor, defina cada unidade como 'Setor' ou 'Seção' e ajuste o nome correspondente no construtor.")
        return redirect('organograma_build', pk=pk)

    validacao = validate_organograma_governance(organograma, persist_links=True)
    if validacao['errors']:
        for err in validacao['errors']:
            messages.error(request, err)
        return redirect('organograma_build', pk=pk)

    organograma.status = 'OFICIAL'
    if organograma.modelo_referencial_efetivo:
        organograma.modelo_referencia_atualizado_em = organograma.modelo_referencial_efetivo.data_atualizacao
    organograma.save() # Dispara backup de histórico automaticamente
    
    messages.success(request, f'Organograma do campus {organograma.campus.sigla} publicado com sucesso!')
    return redirect('organograma_list')


@login_required(login_url='/admin/login/')
def organograma_delete(request, pk):
    organograma = get_object_or_404(Organograma, pk=pk, status__in=['RASCUNHO', 'PROPOSTA'])
    
    if request.user.is_staff:
        related_solicitacao = _proposal_request(organograma)
        if related_solicitacao and not check_solicitacao_access(request.user, related_solicitacao):
            raise PermissionDenied("Sem permissão para excluir.")
            
    # Segurança de Campus
    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != organograma.campus:
            raise PermissionDenied("Sem permissão para excluir.")

    if request.method == 'POST':
        status_deleted = organograma.status
        organograma.delete()
        if status_deleted == 'PROPOSTA':
            messages.success(request, 'Proposta excluída com sucesso!')
            return _redirect_with_fallback(request, 'solicitacao_list')
        messages.success(request, 'Rascunho excluído com sucesso!')
        
    return redirect('organograma_list')


def _get_unidades_json_data(unidades):
    unidades_data = []
    for unidade in unidades:
        unidades_data.append({
            'id': str(unidade.id),
            'parentId': str(unidade.unidade_pai.id) if unidade.unidade_pai else "",
            'name': unidade.nome_unidade,
            'sigla': unidade.sigla_unidade or "",
            'tipoUnidadeId': str(unidade.tipo_unidade.id) if unidade.tipo_unidade else "",
            'tipoUnidadeNome': unidade.tipo_unidade.nome if unidade.tipo_unidade else "",
            'cargoFuncaoId': str(unidade.cargo_funcao_ref.id) if unidade.cargo_funcao_ref else "",
            'role': (unidade.cargo_funcao_ref.nome if unidade.cargo_funcao_ref else (unidade.cargo_funcao or "-")).replace("Não Informado", "-"),
            'roleSigla': unidade.cargo_funcao_ref.sigla if unidade.cargo_funcao_ref else (unidade.sigla_cargo or ""),
            'ligacaoIndireta': unidade.ligacao_indireta,
            'is_agrupamento': unidade.is_agrupamento,
            'layout_filhos': unidade.layout_filhos,
            'cargo_funcao': unidade.cargo_funcao or "",
            'sigla_cargo': unidade.sigla_cargo or "",
            'competencias': _competencias_payload(unidade),
            'competenciasCount': unidade.competencias.count(),
            'competenciasStatus': unidade.competencias_status,
            'competenciasStatusLabel': unidade.competencias_status_label,
            'isPendingDefinition': unidade.has_pending_definition,
            'isFlexibleSource': bool(unidade.origem_modelo and unidade.origem_modelo.has_flexible_resolution),
            'allowedTipoIds': unidade.origem_modelo.allowed_tipo_ids if unidade.origem_modelo else [],
            'allowedCargoIds': unidade.origem_modelo.allowed_cargo_ids if unidade.origem_modelo else [],
        })
    return unidades_data


def _get_unidades_modelo_json_data(unidades):
    unidades_data = []
    for unidade in unidades:
        unidades_data.append({
            'id': str(unidade.id),
            'parentId': str(unidade.unidade_pai.id) if unidade.unidade_pai else "",
            'name': unidade.nome_unidade,
            'sigla': unidade.sigla_unidade or "",
            'tipoUnidadeId': str(unidade.tipo_unidade.id) if unidade.tipo_unidade else "",
            'tipoUnidadeNome': unidade.tipo_unidade.nome if unidade.tipo_unidade else "",
            'cargoFuncaoId': str(unidade.cargo_funcao_ref.id) if unidade.cargo_funcao_ref else "",
            'role': (unidade.cargo_funcao_ref.nome if unidade.cargo_funcao_ref else (unidade.cargo_funcao or "-")),
            'roleSigla': unidade.cargo_funcao_ref.sigla if unidade.cargo_funcao_ref else (unidade.sigla_cargo or ""),
            'cargo_funcao': unidade.cargo_funcao or "",
            'sigla_cargo': unidade.sigla_cargo or "",
            'is_agrupamento': unidade.is_agrupamento,
            'layout_filhos': unidade.layout_filhos,
            'competencias': [],
            'competenciasCount': 0,
            'competenciasStatus': 'revisada',
            'competenciasStatusLabel': 'Modelos referenciais não usam competências',
            'isPendingDefinition': unidade.has_pending_definition,
            'isFlexibleSource': unidade.has_flexible_resolution,
            'allowedTipoIds': unidade.allowed_tipo_ids,
            'allowedCargoIds': unidade.allowed_cargo_ids,
            'permiteResolucaoFlexivel': unidade.permite_resolucao_flexivel,
        })
    return unidades_data


@login_required(login_url='/admin/login/')
def organograma_build(request, pk):
    organograma = get_object_or_404(Organograma, pk=pk)
    allow_structure_changes = _allows_structure_changes(organograma)
    
    if request.user.is_staff:
        related_solicitacao = _proposal_request(organograma)
        if related_solicitacao and not check_solicitacao_access(request.user, related_solicitacao):
            raise PermissionDenied("Você não tem permissão para editar este rascunho.")

    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != organograma.campus:
            raise PermissionDenied("Acesso restrito ao Responsável pelo Campus.")

    related_solicitacao = _proposal_request(organograma)
    if related_solicitacao and related_solicitacao.status == 'APROVADO':
        messages.warning(request, 'Solicitações aprovadas não podem mais ser ajustadas.')
        return _redirect_with_fallback(request, 'organograma_detail', pk=organograma.pk)
    unidades = organograma.unidades.all().order_by('ordem', 'id')
    
    # Suporte a Edição
    edit_id = request.GET.get('edit')
    unit_instance = None
    if edit_id:
        unit_instance = get_object_or_404(Unit, pk=edit_id, organograma=organograma)

    if request.method == 'POST':
        if not unit_instance and not allow_structure_changes:
            return _structure_change_blocked_response(request, organograma)
        if unit_instance and not _allows_unit_metadata_changes(organograma):
            return _proposal_locked_response(request, organograma)
        form = UnitForm(request.POST, instance=unit_instance, organograma_id=organograma.id)
        if form.is_valid():
            unit = form.save(commit=False)
            unit.organograma = organograma
            
            # Auto-fill cargo padrao only when empty and the type does not offer a multi-cargo choice
            # (e.g. Diretoria may keep CD-04 on small campuses — do not overwrite with CD-03).
            if unit.tipo_unidade and unit.tipo_unidade.cargo_padrao and not unit.cargo_funcao_ref:
                multi_choice = unit.tipo_unidade.permite_escolha_entre_cargos
                flexible = unit.origem_modelo and unit.origem_modelo.has_flexible_resolution
                if not multi_choice and not flexible:
                    unit.cargo_funcao_ref = unit.tipo_unidade.cargo_padrao
                elif flexible and not unit.tipo_unidade.selecao_cargo_livre and not multi_choice:
                    unit.cargo_funcao_ref = unit.tipo_unidade.cargo_padrao

            if not unit_instance: # Apenas se for nova caixinha
                from django.db.models import Max
                max_ordem = Unit.objects.filter(
                    organograma=organograma,
                    unidade_pai=form.cleaned_data.get('unidade_pai')
                ).aggregate(Max('ordem'))['ordem__max'] or 0
                unit.ordem = max_ordem + 1
                
            unit.save()
            validate_organograma_governance(organograma, persist_links=True)
                    
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                unidades_list = _get_unidades_json_data(organograma.unidades.all().order_by('ordem', 'id'))
                return JsonResponse({'status': 'success', 'data': unidades_list, 'new_node_id': str(unit.id), 'is_edit': bool(unit_instance)})
            
            return redirect('organograma_build', pk=organograma.id)
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    else:
        form = UnitForm(instance=unit_instance, organograma_id=organograma.id)
        
    # Todos os outros organogramas oficiais para o cluster
    outros_orgs = Organograma.objects.filter(status='OFICIAL').exclude(pk=organograma.id).order_by('campus__nome')
    todos_campi_data = [{'sigla': o.campus.sigla, 'url': f"/organograma/{o.id}/"} for o in outros_orgs]

    linked_orgs = _get_organogramas_vinculados_unicos(organograma)

    unidades_data = _get_unidades_json_data(unidades)

    context = {
        'organograma': organograma,
        'unidades': unidades,
        'form': form,
        'unidades_json': json.dumps(unidades_data),
        'todos_campi_json': json.dumps(todos_campi_data),
        'linked_orgs': linked_orgs,
        'sigla_prefix': organograma.campus.get_sigla_prefix,
        'next_url': _get_safe_next_url(request),
        'related_solicitacao': related_solicitacao,
        'allow_structure_changes': allow_structure_changes,
        'competencias_resumo': organograma.competencias_resumo,
        'regimento_competencias': organograma.regimento_competencias_referencia,
        'regimentos_competencias': organograma.regimentos_competencias_referencia,
        'organograma_export_filename': f'organograma-{organograma.campus.sigla}',
    }
    return render(request, 'core/organograma_builder.html', context)


@login_required(login_url='/admin/login/')
def organograma_unit_delete(request, pk, unit_id):
    organograma = get_object_or_404(Organograma, pk=pk)
    unit = get_object_or_404(Unit, pk=unit_id, organograma=organograma)
    if request.method == 'POST':
        if not _allows_structure_changes(organograma):
            return _structure_change_blocked_response(request, organograma)

        def recursive_delete(u):
            for child in u.sub_unidades.all():
                recursive_delete(child)
            u.delete()

        recursive_delete(unit)
        validate_organograma_governance(organograma, persist_links=True)
        messages.success(request, 'Setor e todos os seus ramais dependentes foram removidos da estrutura.')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            unidades_list = _get_unidades_json_data(organograma.unidades.all().order_by('ordem', 'id'))
            return JsonResponse({'status': 'success', 'data': unidades_list})

    return redirect('organograma_build', pk=organograma.id)


@login_required(login_url='/admin/login/')
def organograma_agrupar_unidades(request, pk):
    organograma = get_object_or_404(Organograma, pk=pk)
    
    if request.method == 'POST':
        if not _allows_structure_changes(organograma):
            return _structure_change_blocked_response(request, organograma)

        unidades_ids = request.POST.getlist('unidades_selecionadas')
        nome_grupo = request.POST.get('nome_grupo')
        if not unidades_ids:
            messages.error(request, 'Seleção de unidades é obrigatória.')
            return redirect('organograma_build', pk=organograma.id)

        unidades = Unit.objects.filter(id__in=unidades_ids, organograma=organograma)
        if unidades.count() < 2:
            messages.error(request, 'Selecione pelo menos duas caixas para agrupar.')
            return redirect('organograma_build', pk=organograma.id)

        if not nome_grupo or nome_grupo.strip() == '':
            siglas = [u.sigla_unidade for u in unidades if u.sigla_unidade]
            if siglas:
                nome_grupo = f"Caixa de Agrupamento - {'/'.join(siglas[:3])}"
            else:
                nome_grupo = "Caixa de Agrupamento"

        unidades_id_ints = [int(u_id) for u_id in unidades_ids]
        topo_grupo = None

        for u in unidades:
            tem_ancestral_no_grupo = False
            curr = u.unidade_pai
            while curr:
                if curr.id in unidades_id_ints:
                    tem_ancestral_no_grupo = True
                    break
                curr = curr.unidade_pai
            if not tem_ancestral_no_grupo:
                topo_grupo = u
                break

        if not topo_grupo:
            topo_grupo = unidades.first()

        pai_comum = topo_grupo.unidade_pai

        grupo_virtual = Unit.objects.create(
            organograma=organograma,
            nome_unidade=nome_grupo,
            unidade_pai=pai_comum,
            is_agrupamento=True
        )

        for u in unidades:
            u.unidade_pai = grupo_virtual
            u.save()
        validate_organograma_governance(organograma, persist_links=True)
        messages.success(request, f'Agrupamento "{nome_grupo}" criado e caixinhas vinculadas!')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            unidades_list = _get_unidades_json_data(organograma.unidades.all())
            return JsonResponse({'status': 'success', 'data': unidades_list, 'new_group_id': str(grupo_virtual.id)})

    return redirect('organograma_build', pk=organograma.id)


@login_required(login_url='/admin/login/')
def organograma_desagrupar_unidade(request, pk, unit_id):
    organograma = get_object_or_404(Organograma, pk=pk)
    grupo = get_object_or_404(Unit, pk=unit_id, organograma=organograma, is_agrupamento=True)
    
    if request.method == 'POST':
        if not _allows_structure_changes(organograma):
            return _structure_change_blocked_response(request, organograma)

        pai_original = grupo.unidade_pai

        for filho in grupo.sub_unidades.all():
            filho.unidade_pai = pai_original
            filho.save()

        grupo.delete()
        validate_organograma_governance(organograma, persist_links=True)
        messages.success(request, 'Agrupamento desfeito e caixas desamarradas para seu nível hierárquico.')
        
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        unidades_list = _get_unidades_json_data(organograma.unidades.all())
        return JsonResponse({'status': 'success', 'data': unidades_list})

    return redirect('organograma_build', pk=organograma.id)


@login_required(login_url='/admin/login/')
def organograma_validate_ajax(request, pk):
    organograma = get_object_or_404(Organograma, pk=pk)
    validacao = validate_organograma_governance(organograma, persist_links=True)
    payload = {
        'counts': validacao['counts'],
        'fg_used': validacao['fg_used'],
        'fg_limit': validacao['fg_limit'],
        'fg_remaining': validacao['fg_remaining'],
        'cargo_quotas': validacao.get('cargo_quotas', {}),
    }
    if validacao['errors']:
        return JsonResponse({'status': 'error', 'html': validacao['html'], **payload})
    return JsonResponse({'status': 'success', **payload})


@login_required(login_url='/admin/login/')
def unidade_competencias(request, pk, unit_id):
    organograma = get_object_or_404(Organograma, pk=pk)
    unidade = get_object_or_404(Unit, pk=unit_id, organograma=organograma)
    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != organograma.campus:
            raise PermissionDenied("Acesso restrito ao Responsável pelo Campus.")

    regimentos = organograma.regimentos_competencias_referencia
    regimento = organograma.regimento_competencias_referencia
    if request.method == 'GET':
        return JsonResponse({
            'status': 'success',
            'competencias': _competencias_payload(unidade),
            'competenciasStatus': unidade.competencias_status,
            'competenciasStatusLabel': unidade.competencias_status_label,
            'regimento': _regimento_to_dict(regimento) if regimento else {'id': '', 'nome': '', 'url': ''},
            'regimentos': [_regimento_to_dict(r) for r in regimentos],
        })

    regimento = _resolve_competencia_regimento(request, organograma)
    if not regimento:
        return JsonResponse({'status': 'error', 'errors': {'regimento': ['Defina a fonte normativa vigente para cadastrar competências.']}}, status=400)

    form = CompetenciaUnidadeForm(request.POST)
    if form.is_valid():
        competencia = form.save(commit=False)
        competencia.unidade = unidade
        competencia.regimento = regimento
        competencia.revisada_em = timezone.now()
        competencia.revisada_por = request.user
        max_ordem = unidade.competencias.aggregate(models.Max('ordem'))['ordem__max'] or 0
        competencia.ordem = max_ordem + 1
        competencia.save()
        return JsonResponse({
            'status': 'success',
            'competencia': _competencia_to_dict(competencia),
            'competencias': _competencias_payload(unidade),
            'competenciasStatus': unidade.competencias_status,
            'competenciasStatusLabel': unidade.competencias_status_label,
        })
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)


@login_required(login_url='/admin/login/')
@require_POST
def unidade_competencias_importar(request, pk, unit_id):
    organograma = get_object_or_404(Organograma, pk=pk)
    unidade = get_object_or_404(Unit, pk=unit_id, organograma=organograma)
    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != organograma.campus:
            raise PermissionDenied("Acesso restrito ao ResponsÃ¡vel pelo Campus.")

    regimento = _resolve_competencia_regimento(request, organograma)
    if not regimento:
        return JsonResponse({'status': 'error', 'errors': {'regimento': ['Defina a fonte normativa vigente para importar competÃªncias.']}}, status=400)

    uploaded_file = request.FILES.get('arquivo')
    if not uploaded_file:
        return JsonResponse({'status': 'error', 'errors': {'arquivo': ['Selecione um arquivo .csv ou .txt.']}}, status=400)

    try:
        rows = parse_competencias_file(uploaded_file)
    except ValidationError as error:
        return JsonResponse({'status': 'error', 'errors': {'arquivo': error.messages}}, status=400)

    max_ordem = unidade.competencias.aggregate(models.Max('ordem'))['ordem__max'] or 0
    competencias = []
    now = timezone.now()
    for index, row in enumerate(rows, start=1):
        competencias.append(CompetenciaUnidade(
            unidade=unidade,
            regimento=regimento,
            artigo=row.get('artigo', ''),
            paragrafo=row.get('paragrafo', ''),
            inciso=row.get('inciso', ''),
            alinea=row.get('alinea', ''),
            texto=row['texto'],
            ordem=max_ordem + index,
            revisada_em=now,
            revisada_por=request.user,
        ))
    CompetenciaUnidade.objects.bulk_create(competencias)

    return JsonResponse({
        'status': 'success',
        'importedCount': len(competencias),
        'competencias': _competencias_payload(unidade),
        'competenciasStatus': unidade.competencias_status,
        'competenciasStatusLabel': unidade.competencias_status_label,
    })


@login_required(login_url='/admin/login/')
def unidade_competencia_update(request, pk, unit_id, competencia_id):
    organograma = get_object_or_404(Organograma, pk=pk)
    unidade = get_object_or_404(Unit, pk=unit_id, organograma=organograma)
    competencia = get_object_or_404(CompetenciaUnidade, pk=competencia_id, unidade=unidade)
    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != organograma.campus:
            raise PermissionDenied("Acesso restrito ao Responsável pelo Campus.")

    if request.method == 'POST':
        form = CompetenciaUnidadeForm(request.POST, instance=competencia)
        if form.is_valid():
            competencia = form.save(commit=False)
            regimento = _resolve_competencia_regimento(request, organograma)
            if not regimento:
                return JsonResponse({'status': 'error', 'errors': {'regimento': ['Defina a fonte normativa vigente para atualizar competências.']}}, status=400)
            competencia.regimento = regimento
            competencia.revisada_em = timezone.now()
            competencia.revisada_por = request.user
            competencia.save()
            return JsonResponse({
                'status': 'success',
                'competencia': _competencia_to_dict(competencia),
                'competencias': _competencias_payload(unidade),
                'competenciasStatus': unidade.competencias_status,
                'competenciasStatusLabel': unidade.competencias_status_label,
            })
        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

    if request.method == 'DELETE':
        competencia.delete()
        return JsonResponse({
            'status': 'success',
            'competencias': _competencias_payload(unidade),
            'competenciasStatus': unidade.competencias_status,
            'competenciasStatusLabel': unidade.competencias_status_label,
        })

    return JsonResponse({'status': 'error', 'errors': {'__all__': ['Método inválido.']}}, status=405)


@login_required(login_url='/admin/login/')
def unidade_competencias_reordenar(request, pk, unit_id):
    organograma = get_object_or_404(Organograma, pk=pk)
    unidade = get_object_or_404(Unit, pk=unit_id, organograma=organograma)
    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != organograma.campus:
            raise PermissionDenied("Acesso restrito ao Responsável pelo Campus.")

    ids = request.POST.getlist('competencias[]') or request.POST.getlist('competencias')
    competencias = list(unidade.competencias.filter(id__in=ids))
    by_id = {str(c.id): c for c in competencias}
    for index, competencia_id in enumerate(ids, start=1):
        competencia = by_id.get(str(competencia_id))
        if competencia:
            competencia.ordem = index
            competencia.save(update_fields=['ordem'])
    return JsonResponse({'status': 'success', 'competencias': _competencias_payload(unidade)})


@login_required(login_url='/admin/login/')
def solicitacao_create_select(request):
    campus_options = Campus.objects.filter(organogramas__status='OFICIAL').distinct().order_by('nome')
    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or not profile.campus:
            raise PermissionDenied("VocÃª nÃ£o tem campus vinculado para abrir solicitaÃ§Ãµes.")
        campus_options = campus_options.filter(pk=profile.campus_id)

    if request.method == 'POST':
        campus_id = request.POST.get('campus')
        campus = get_object_or_404(campus_options, pk=campus_id)
        organograma = Organograma.objects.filter(campus=campus, status='OFICIAL').order_by('-id').first()
        if not organograma:
            messages.error(request, 'O campus selecionado nÃ£o possui organograma oficial para alteraÃ§Ã£o.')
            return redirect('solicitacao_create_select')
        return redirect('solicitacao_create', pk=organograma.pk)

    return render(request, 'core/solicitacao_select_campus.html', {'campus_options': campus_options})


@login_required(login_url='/admin/login/')
def solicitacao_create(request, pk):
    org_original = get_object_or_404(Organograma, pk=pk, status='OFICIAL')
    
    if org_original.tem_proposta_ativa:
        messages.warning(request, 'Este organograma já possui uma proposta de alteração em análise.')
        return redirect('organograma_detail', pk=pk)
    
    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != org_original.campus:
            raise PermissionDenied("Você não tem permissão para propor alterações neste Campus.")
    
    if request.method == 'POST':
        justificativa = request.POST.get('justificativa', '')
        
        if not justificativa:
            messages.error(request, 'Por favor, informe uma justificativa para a alteração.')
            return render(request, 'core/solicitacao_form.html', {'organograma': org_original})

        org_proposto = Organograma.objects.create(
            campus=org_original.campus,
            data_vigencia=org_original.data_vigencia,
            documento_aprovacao=org_original.documento_aprovacao,
            nome_documento_aprovacao=org_original.nome_documento_aprovacao,
            modelo_base=org_original.modelo_referencial_efetivo,
            modelo_referencia_atualizado_em=org_original.modelo_referencia_atualizado_em,
            nome_regimento=org_original.nome_regimento,
            regimento_arquivo=org_original.regimento_arquivo,
            nome_regimento_geral=org_original.nome_regimento_geral,
            regimento_geral_arquivo=org_original.regimento_geral_arquivo,
            regimento_referencia=org_original.regimento_referencia,
            regimento_geral_referencia=org_original.regimento_geral_referencia,
            status='PROPOSTA'
        )
        
        unidades_originais = org_original.unidades.all()
        id_map = {}
        
        for u in unidades_originais:
            new_u = Unit.objects.create(
                organograma=org_proposto,
                origem_modelo=u.origem_modelo,
                nome_unidade=u.nome_unidade,
                sigla_unidade=u.sigla_unidade,
                tipo_unidade=u.tipo_unidade,
                cargo_funcao_ref=u.cargo_funcao_ref,
                cargo_funcao=u.cargo_funcao,
                sigla_cargo=u.sigla_cargo,
                ordem=u.ordem,
                ligacao_indireta=u.ligacao_indireta,
                is_agrupamento=u.is_agrupamento,
                layout_filhos=u.layout_filhos,
                oculto_no_organograma=u.oculto_no_organograma,
                atribuicoes=u.atribuicoes,
                source_unit=u
            )
            id_map[u.id] = new_u
            
        for u in unidades_originais:
            if u.unidade_pai_id:
                new_u = id_map[u.id]
                new_u.unidade_pai = id_map[u.unidade_pai_id]
                new_u.save()

        for u in unidades_originais:
            new_u = id_map[u.id]
            for competencia in u.competencias.all():
                CompetenciaUnidade.objects.create(
                    unidade=new_u,
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
                
        # 3. Create Solicitação
        SolicitacaoAlteracao.objects.create(
            organograma_original=org_original,
            organograma_proposto=org_proposto,
            usuario=request.user,
            justificativa=justificativa,
            status='RASCUNHO'
        )
        
        messages.success(request, 'Solicitacao criada como rascunho. Envie para analise quando terminar os ajustes.')
        return redirect('organograma_build', pk=org_proposto.pk)
        
    return render(request, 'core/solicitacao_form.html', {'organograma': org_original})


@login_required(login_url='/admin/login/')
def solicitacao_list(request):
    solicitacoes = SolicitacaoAlteracao.objects.select_related(
        'usuario',
        'organograma_original',
        'organograma_original__campus',
        'organograma_original__resolucao_estrutura',
        'organograma_proposto',
        'organograma_proposto__campus',
        'organograma_proposto__resolucao_estrutura',
    )
    if request.user.is_superuser:
        solicitacoes = solicitacoes.all()
    elif request.user.is_staff:
        solicitacoes = solicitacoes.exclude(status='RASCUNHO', usuario__profile__campus__isnull=False)
    else:
        solicitacoes = solicitacoes.filter(usuario=request.user)

    q = _filter_value(request, 'q')
    status = _filter_value(request, 'status')
    campus = _filter_value(request, 'campus')
    solicitante = _filter_value(request, 'solicitante')
    data_inicio = _filter_value(request, 'data_inicio')
    data_fim = _filter_value(request, 'data_fim')
    proposta = _filter_value(request, 'proposta')
    ordenar = _filter_value(request, 'ordenar')

    if q:
        q_filter = (
            models.Q(organograma_original__campus__nome__icontains=q) |
            models.Q(organograma_original__campus__sigla__icontains=q) |
            models.Q(usuario__username__icontains=q) |
            models.Q(justificativa__icontains=q)
        )
        if q.isdigit():
            q_filter |= models.Q(id=int(q))
        solicitacoes = solicitacoes.filter(q_filter)
    if status:
        solicitacoes = solicitacoes.filter(status=status)
    if campus:
        solicitacoes = solicitacoes.filter(organograma_original__campus_id=campus)
    if (request.user.is_superuser or request.user.is_staff) and solicitante:
        solicitacoes = solicitacoes.filter(usuario_id=solicitante)
    if data_inicio:
        solicitacoes = solicitacoes.filter(data_criacao__date__gte=data_inicio)
    if data_fim:
        solicitacoes = solicitacoes.filter(data_criacao__date__lte=data_fim)
    if proposta == 'com_resolucao':
        solicitacoes = solicitacoes.filter(organograma_proposto__resolucao_estrutura__isnull=False)
    elif proposta == 'sem_resolucao':
        solicitacoes = solicitacoes.filter(organograma_proposto__resolucao_estrutura__isnull=True)
    elif proposta == 'resolucao_diferente':
        solicitacoes = solicitacoes.exclude(
            organograma_proposto__resolucao_estrutura_id=models.F('organograma_original__resolucao_estrutura_id')
        )

    if ordenar == 'antigas':
        solicitacoes = solicitacoes.order_by('data_criacao')
    elif ordenar == 'campus':
        solicitacoes = solicitacoes.order_by('organograma_original__campus__nome', '-data_criacao')
    elif ordenar == 'status':
        solicitacoes = solicitacoes.order_by('status', '-data_criacao')
    else:
        solicitacoes = solicitacoes.order_by('-data_criacao')

    context = {
        'solicitacoes': solicitacoes,
        'filters': request.GET,
        'campus_options': Campus.objects.all().order_by('nome'),
        'solicitante_options': get_user_model().objects.all().order_by('username') if (request.user.is_superuser or request.user.is_staff) else [],
    }
    return render(request, 'core/solicitacao_list.html', context)


@login_required(login_url='/admin/login/')
def solicitacao_approve(request, pk):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, 'Ação administrativa restrita.')
        return _redirect_with_fallback(request, 'solicitacao_list')
        
    solicitacao = get_object_or_404(SolicitacaoAlteracao, pk=pk)
    if not check_solicitacao_access(request.user, solicitacao):
        raise PermissionDenied("Você não tem permissão para acessar esta solicitação.")
    if solicitacao.status not in ['EM_ANALISE', 'ENVIADO_CONSUP']:
        messages.warning(request, 'Essa solicitação já foi processada.')
        return _redirect_with_fallback(request, 'solicitacao_list')

    with transaction.atomic():
        proposal = solicitacao.organograma_proposto
        
        # Trava de Segurança Final: Governança
        validacao = validate_organograma_governance(proposal, persist_links=True)
        if validacao['errors']:
            messages.error(request, 'Não é possível aprovar esta solicitação: Ela viola regras de governança institucional. Revise a proposta no construtor.')
            for e in validacao['errors']: 
                # Se for o relatório HTML, o messages.error suporta safe.
                messages.error(request, e)
            return _redirect_with_fallback(request, 'solicitacao_list')

        # Marcar antigo como histórico
        if solicitacao.status == 'EM_ANALISE':
            solicitacao.status = 'ENVIADO_CONSUP'
            solicitacao.save(update_fields=['status', 'data_atualizacao'])
            messages.success(request, 'Solicitacao enviada para aprovacao no CONSUP. O organograma vigente permanece oficial ate a aprovacao final.')
            return _redirect_with_fallback(request, 'solicitacao_list')

        normative_error = _validate_final_normative_documents(solicitacao)
        if normative_error:
            messages.error(request, normative_error)
            return _redirect_with_fallback(request, 'solicitacao_list')

        Organograma.objects.filter(
            campus=solicitacao.organograma_original.campus, 
            status='OFICIAL'
        ).update(status='HISTORICO')
        
        # Promover proposta
        proposal.status = 'OFICIAL'
        proposal.data_aprovacao_sistema = timezone.now()
        update_fields = ['status', 'data_aprovacao_sistema']
        if not proposal.documento_aprovacao and solicitacao.organograma_original.documento_aprovacao:
            proposal.documento_aprovacao = solicitacao.organograma_original.documento_aprovacao
            update_fields.append('documento_aprovacao')
        if not proposal.nome_documento_aprovacao and solicitacao.organograma_original.nome_documento_aprovacao:
            proposal.nome_documento_aprovacao = solicitacao.organograma_original.nome_documento_aprovacao
            update_fields.append('nome_documento_aprovacao')
        if proposal.modelo_referencial_efetivo:
            proposal.modelo_referencia_atualizado_em = proposal.modelo_referencial_efetivo.data_atualizacao
            update_fields.append('modelo_referencia_atualizado_em')
        proposal.save(update_fields=update_fields)
        
        solicitacao.status = 'APROVADO'
        solicitacao.save()
        
        messages.success(request, f'Alteração aprovada! Novo organograma oficial do campus {proposal.campus.sigla} ativo.')
    
    return _redirect_with_fallback(request, 'solicitacao_list')


@login_required(login_url='/admin/login/')
def solicitacao_reject(request, pk):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, 'Ação administrativa restrita.')
        return _redirect_with_fallback(request, 'solicitacao_list')
        
    solicitacao = get_object_or_404(SolicitacaoAlteracao, pk=pk)
    if not check_solicitacao_access(request.user, solicitacao):
        raise PermissionDenied("Você não tem permissão para acessar esta solicitação.")
    if solicitacao.status not in ['EM_ANALISE', 'ENVIADO_CONSUP']:
        messages.warning(request, 'Essa solicitação já foi processada.')
        return _redirect_with_fallback(request, 'solicitacao_list')

    justificativa_avaliador = (request.POST.get('justificativa_avaliador') or '').strip()
    if not justificativa_avaliador:
        messages.error(request, 'Informe a justificativa do avaliador para rejeitar ou devolver a solicitação.')
        return _redirect_with_fallback(request, 'solicitacao_list')

    acao_rejeicao = request.POST.get('acao_rejeicao')
    if acao_rejeicao == 'devolver_correcao':
        solicitacao.status = 'DEVOLVIDO_CORRECAO'
        message = 'Solicitação devolvida ao demandante para correção.'
    else:
        solicitacao.status = 'REJEITADO'
        message = 'Solicitação de alteração rejeitada.'
    solicitacao.justificativa_avaliador = justificativa_avaliador
    solicitacao.save(update_fields=['status', 'justificativa_avaliador', 'data_atualizacao'])
    messages.warning(request, message)
    return _redirect_with_fallback(request, 'solicitacao_list')
    
    messages.warning(request, 'Solicitação de alteração rejeitada.')
    return _redirect_with_fallback(request, 'solicitacao_list')


@login_required(login_url='/admin/login/')
def solicitacao_resubmit(request, pk):
    solicitacao = get_object_or_404(SolicitacaoAlteracao, pk=pk)

    if solicitacao.status not in ['RASCUNHO', 'DEVOLVIDO_CORRECAO']:
        messages.warning(request, 'Apenas rascunhos ou solicitações devolvidas para correção podem ser enviados para análise.')
        return _redirect_with_fallback(request, 'solicitacao_list')

    if not request.user.is_superuser and solicitacao.usuario != request.user:
        raise PermissionDenied("Apenas o demandante pode enviar esta solicitação para análise.")

    if not request.user.is_staff:
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.campus != solicitacao.organograma_original.campus:
            raise PermissionDenied("Você não tem permissão para reenviar esta solicitação.")

    if SolicitacaoAlteracao.objects.filter(
        organograma_original=solicitacao.organograma_original,
        status__in=['RASCUNHO', 'EM_ANALISE', 'ENVIADO_CONSUP', 'DEVOLVIDO_CORRECAO'],
    ).exclude(pk=solicitacao.pk).exists():
        messages.warning(request, 'Já existe uma proposta em análise para este organograma.')
        return _redirect_with_fallback(request, 'solicitacao_list')

    validacao = validate_organograma_governance(solicitacao.organograma_proposto, persist_links=True)
    if validacao['errors']:
        messages.error(request, 'A solicitação possui pendências de adequação e não pode ser enviada para análise.')
        for erro in validacao['errors']:
            messages.error(request, erro)
        return _redirect_with_fallback(request, 'solicitacao_list')

    solicitacao.status = 'EM_ANALISE'
    solicitacao.save(update_fields=['status', 'data_atualizacao'])

    messages.success(request, 'Solicitação enviada para análise com sucesso!')
    return _redirect_with_fallback(request, 'solicitacao_list')


@login_required(login_url='/admin/login/')
@require_POST
def solicitacao_delete(request, pk):
    solicitacao = get_object_or_404(SolicitacaoAlteracao, pk=pk)

    if not check_solicitacao_access(request.user, solicitacao):
        raise PermissionDenied("Você não tem permissão para acessar esta solicitação.")

    if solicitacao.status not in ['RASCUNHO', 'DEVOLVIDO_CORRECAO']:
        messages.error(request, "Apenas rascunhos ou solicitações devolvidas para correção podem ser excluídos.")
        return _redirect_with_fallback(request, 'solicitacao_list')

    # Apenas o proprietário da solicitação ou o superusuário pode excluir
    if not request.user.is_superuser and solicitacao.usuario != request.user:
        raise PermissionDenied("Você não tem permissão para excluir esta solicitação.")

    solicitacao.delete()
    messages.success(request, "Rascunho de proposta de alteração excluído com sucesso.")
    return _redirect_with_fallback(request, 'solicitacao_list')



@login_required(login_url='/admin/login/')
def organograma_unit_up(request, pk, unit_id):
    organograma = get_object_or_404(Organograma, pk=pk)
    unit = get_object_or_404(Unit, pk=unit_id, organograma=organograma)
    if not _allows_unit_metadata_changes(organograma):
        return _proposal_locked_response(request, organograma)
    
    irmaos = list(Unit.objects.filter(organograma=organograma, unidade_pai=unit.unidade_pai).order_by('ordem', 'id'))
    try:
        idx = irmaos.index(unit)
        if idx > 0:
            vizinho = irmaos[idx - 1]
            if unit.ordem == vizinho.ordem:
                for i, u in enumerate(irmaos):
                    u.ordem = i + 1; u.save()
                unit.refresh_from_db(); vizinho.refresh_from_db()
            
            unit.ordem, vizinho.ordem = vizinho.ordem, unit.ordem
            unit.save(); vizinho.save()
    except ValueError: pass
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        unidades = _get_unidades_json_data(organograma.unidades.all())
        return JsonResponse({'status': 'success', 'data': unidades})
        
    return redirect('organograma_build', pk=pk)


@login_required(login_url='/admin/login/')
def organograma_unit_down(request, pk, unit_id):
    organograma = get_object_or_404(Organograma, pk=pk)
    unit = get_object_or_404(Unit, pk=unit_id, organograma=organograma)
    if not _allows_unit_metadata_changes(organograma):
        return _proposal_locked_response(request, organograma)
    
    irmaos = list(Unit.objects.filter(organograma=organograma, unidade_pai=unit.unidade_pai).order_by('ordem', 'id'))
    try:
        idx = irmaos.index(unit)
        if idx < len(irmaos) - 1:
            vizinho = irmaos[idx + 1]
            if unit.ordem == vizinho.ordem:
                for i, u in enumerate(irmaos):
                    u.ordem = i + 1; u.save()
                unit.refresh_from_db(); vizinho.refresh_from_db()
            
            unit.ordem, vizinho.ordem = vizinho.ordem, unit.ordem
            unit.save(); vizinho.save()
    except ValueError: pass

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        unidades = _get_unidades_json_data(organograma.unidades.all())
        return JsonResponse({'status': 'success', 'data': unidades})

    return redirect('organograma_build', pk=pk)


@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def cargo_list(request):
    cargos = CargoFuncao.objects.all().order_by('sigla', 'nome')
    
    if request.method == 'POST':
        form = CargoFuncaoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cargo criado com sucesso!')
            return redirect('cargo_list')

    form_cargo = CargoFuncaoForm()
    return render(request, 'core/cargo_list.html', {
        'cargos': cargos,
        'form_cargo': form_cargo,
    })


@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def tipo_unidade_list(request):
    tipos = TipoUnidade.objects.all().order_by('cargo_padrao__sigla', 'nome')
    
    if request.method == 'POST':
        form = TipoUnidadeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tipo de Unidade criado com sucesso!')
            return redirect('tipo_unidade_list')

    form_tipo = TipoUnidadeForm()
    return render(request, 'core/tipo_unidade_list.html', {
        'tipos': tipos,
        'form_tipo': form_tipo
    })


@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def resolucao_estrutura_list(request):
    resolucoes = ResolucaoEstruturaOrganizacional.objects.select_related('campus').order_by('campus__nome', '-data_publicacao', '-id')

    if request.method == 'POST':
        form = ResolucaoEstruturaOrganizacionalForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Resolução cadastrada com sucesso!')
            return redirect('resolucao_estrutura_list')
    else:
        form = ResolucaoEstruturaOrganizacionalForm()

    return render(request, 'core/resolucao_estrutura_list.html', {
        'resolucoes': resolucoes,
        'form': form,
    })


@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def resolucao_estrutura_editar(request, pk):
    resolucao = get_object_or_404(ResolucaoEstruturaOrganizacional, pk=pk)
    if request.method == 'POST':
        form = ResolucaoEstruturaOrganizacionalForm(request.POST, request.FILES, instance=resolucao)
        if form.is_valid():
            form.save()
            messages.success(request, 'Resolução atualizada com sucesso!')
            return redirect('resolucao_estrutura_list')
    else:
        form = ResolucaoEstruturaOrganizacionalForm(instance=resolucao)
    return render(request, 'core/configuracoes_form.html', {
        'form': form,
        'title': 'Editar Resolução de Estrutura',
        'object': resolucao,
        'back_url': 'resolucao_estrutura_list',
    })


@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def regimento_campus_list(request):
    regimentos = RegimentoCampus.objects.select_related('campus').order_by('campus__nome', '-vigente', '-data_publicacao', '-id')

    if request.method == 'POST':
        form = RegimentoCampusForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Regimento cadastrado com sucesso!')
            return redirect('regimento_campus_list')
    else:
        form = RegimentoCampusForm()

    return render(request, 'core/regimento_campus_list.html', {
        'regimentos': regimentos,
        'form': form,
    })


@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def regimento_campus_editar(request, pk):
    regimento = get_object_or_404(RegimentoCampus, pk=pk)
    if request.method == 'POST':
        form = RegimentoCampusForm(request.POST, request.FILES, instance=regimento)
        if form.is_valid():
            form.save()
            messages.success(request, 'Regimento atualizado com sucesso!')
            return redirect('regimento_campus_list')
    else:
        form = RegimentoCampusForm(instance=regimento)
    return render(request, 'core/configuracoes_form.html', {
        'form': form,
        'title': 'Editar Regimento',
        'object': regimento,
        'back_url': 'regimento_campus_list',
    })

@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def cargo_editar(request, pk):
    cargo = get_object_or_404(CargoFuncao, pk=pk)
    if request.method == 'POST':
        form = CargoFuncaoForm(request.POST, instance=cargo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cargo atualizado com sucesso!')
            return redirect('cargo_list')
    else:
        form = CargoFuncaoForm(instance=cargo)
    return render(request, 'core/configuracoes_form.html', {'form': form, 'title': 'Editar Cargo', 'object': cargo, 'back_url': 'cargo_list'})

@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def tipo_unidade_editar(request, pk):
    tipo = get_object_or_404(TipoUnidade, pk=pk)
    if request.method == 'POST':
        form = TipoUnidadeForm(request.POST, instance=tipo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tipo de Unidade atualizado com sucesso!')
            return redirect('tipo_unidade_list')
    else:
        form = TipoUnidadeForm(instance=tipo)
    return render(request, 'core/configuracoes_form.html', {
        'form': form, 
        'title': 'Editar Tipo de Unidade', 
        'object': tipo,
        'back_url': 'tipo_unidade_list'
    })

@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def usuario_list(request):
    from django.contrib.auth.models import User
    usuarios = User.objects.all().order_by('username')
    return render(request, 'core/usuario_list.html', {'usuarios': usuarios})

@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def usuario_editar(request, pk=None):
    from django.contrib.auth.models import User
    from .forms import CustomUserForm
    usuario = get_object_or_404(User, pk=pk) if pk else None
    
    if request.method == 'POST':
        form = CustomUserForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()
            messages.success(request, f'Usuário {"atualizado" if pk else "criado"} com sucesso!')
            return redirect('usuario_list')
    else:
        form = CustomUserForm(instance=usuario)
        
    return render(request, 'core/configuracoes_form.html', {
        'form': form, 
        'title': 'Editar Usuário' if pk else 'Novo Usuário', 
        'object': usuario,
        'back_url': 'usuario_list'
    })

@require_POST
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def usuario_excluir(request, pk):
    User = get_user_model()
    usuario = get_object_or_404(User, pk=pk)

    if usuario.pk == request.user.pk:
        messages.error(request, 'Voce nao pode excluir o proprio usuario logado.')
        return redirect('usuario_list')

    username = usuario.username
    usuario.delete()
    messages.success(request, f'Usuario "{username}" excluido com sucesso!')
    return redirect('usuario_list')

@login_required(login_url='/admin/login/')
def custom_logout(request):
    from django.contrib.auth import logout as auth_logout
    auth_logout(request)
    return redirect('organograma_list')

@login_required(login_url='/admin/login/')
def solicitacao_detail(request, pk):
    from django.core.exceptions import PermissionDenied
    solicitacao = get_object_or_404(SolicitacaoAlteracao, pk=pk)
    org_original = solicitacao.organograma_original
    org_proposto = solicitacao.organograma_proposto

    # Segurança
    if not check_solicitacao_access(request.user, solicitacao):
        raise PermissionDenied("Você não tem permissão para visualizar esta solicitação.")

    unidades_originais = org_original.unidades.all()
    unidades_propostas = org_proposto.unidades.all()

    # Calcular Diferenças (Diff)
    added = []
    removed = []
    modified = []

    # 1. Encontrar Adicionados e Modificados
    for up in unidades_propostas:
        if not up.source_unit:
            added.append(up)
        else:
            uo = up.source_unit
            changes = []
            if up.nome_unidade != uo.nome_unidade:
                changes.append({'field': 'Nome', 'old': uo.nome_unidade, 'new': up.nome_unidade})
            if up.sigla_unidade != uo.sigla_unidade:
                changes.append({'field': 'Sigla', 'old': uo.sigla_unidade, 'new': up.sigla_unidade})
            if up.tipo_unidade != uo.tipo_unidade:
                changes.append({'field': 'Tipo de Departamento', 'old': uo.tipo_unidade.nome if uo.tipo_unidade else 'Nenhum', 'new': up.tipo_unidade.nome if up.tipo_unidade else 'Nenhum'})
            if up.cargo_funcao_ref != uo.cargo_funcao_ref:
                changes.append({'field': 'Cargo/Função', 'old': uo.cargo_funcao_ref.nome if uo.cargo_funcao_ref else 'Nenhum', 'new': up.cargo_funcao_ref.nome if up.cargo_funcao_ref else 'Nenhum'})
            # Correção: Comparar pais usando source_unit
            parent_changed = False
            if up.unidade_pai and not uo.unidade_pai:
                parent_changed = True
            elif not up.unidade_pai and uo.unidade_pai:
                parent_changed = True
            elif up.unidade_pai and uo.unidade_pai:
                if up.unidade_pai.source_unit != uo.unidade_pai:
                    parent_changed = True
                    
            if parent_changed:
                changes.append({'field': 'Subordinado a', 'old': uo.unidade_pai.nome_unidade if uo.unidade_pai else 'Raiz', 'new': up.unidade_pai.nome_unidade if up.unidade_pai else 'Raiz'})

            if up.atribuicoes != uo.atribuicoes:
                changes.append({'field': 'Atribuições', 'old': uo.atribuicoes[:50] + '...' if uo.atribuicoes else 'Nenhuma', 'new': up.atribuicoes[:50] + '...' if up.atribuicoes else 'Nenhuma'})

            competencias_originais = _competencias_diff_text(uo)
            competencias_propostas = _competencias_diff_text(up)
            if competencias_propostas != competencias_originais:
                changes.append({'field': 'Competências', 'old': competencias_originais, 'new': competencias_propostas})
                
            if changes:
                modified.append({'unit': up, 'original_unit': uo, 'changes': changes})

    # 2. Encontrar Removidos
    sourced_ids = [up.source_unit.id for up in unidades_propostas if up.source_unit]
    for uo in unidades_originais:
        if uo.id not in sourced_ids:
            removed.append(uo)

    context = {
        'solicitacao': solicitacao,
        'added': added,
        'removed': removed,
        'modified': modified,
        'next_url': _get_safe_next_url(request),
    }
    return render(request, 'core/solicitacao_detail.html', context)
@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def _duplicated_modelo_referencial_build(request, pk):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    unidades = modelo.unidades.all().order_by('ordem', 'id')
    
    edit_id = request.GET.get('edit')
    unit_instance = None
    if edit_id:
        unit_instance = get_object_or_404(UnitModelo, pk=edit_id, modelo=modelo)

    if request.method == 'POST':
        form = UnitModeloForm(request.POST, instance=unit_instance, modelo=modelo)
        if form.is_valid():
            unit = form.save(commit=False)
            unit.modelo = modelo
            
            # Auto-fill cargo padrao only when empty and type is single-cargo
            if (
                unit.tipo_unidade
                and unit.tipo_unidade.cargo_padrao
                and not unit.cargo_funcao_ref
                and not form.cleaned_data.get('permite_resolucao_flexivel')
                and not unit.tipo_unidade.permite_escolha_entre_cargos
            ):
                unit.cargo_funcao_ref = unit.tipo_unidade.cargo_padrao

            if not unit_instance:
                from django.db.models import Max
                max_ordem = UnitModelo.objects.filter(
                    modelo=modelo,
                    unidade_pai=form.cleaned_data.get('unidade_pai')
                ).aggregate(Max('ordem'))['ordem__max'] or 0
                unit.ordem = max_ordem + 1
            unit.save()
            form.save_m2m()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                unidades_list = _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))
                return JsonResponse({'status': 'success', 'data': unidades_list, 'new_node_id': str(unit.id), 'is_edit': bool(unit_instance)})

            return redirect('modelo_referencial_build', pk=modelo.id)
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    else:
        form = UnitModeloForm(instance=unit_instance, modelo=modelo)

    context = {
        'modelo': modelo,
        'form': form,
        'unidades_json': json.dumps(_get_unidades_modelo_json_data(unidades)),
        'is_modelo_builder': True,
        'next_url': reverse('modelo_referencial_list'),
        'allow_structure_changes': True,
        'organograma_export_filename': f'modelo-referencial-{modelo.pk}',
        # Variáveis que o template compartilhado espera
        'todos_campi_json': None,
        'backlinks': [],
        'linked_orgs': [],
        'next_url': reverse('modelo_referencial_list'),
        'allow_structure_changes': True,
        'organograma_export_filename': f'modelo-referencial-{modelo.pk}',
        'sigla_prefix': '' # Modelos não têm prefixo fixo
    }
    return render(request, 'core/organograma_builder.html', context)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def _duplicated_modelo_referencial_unit_delete(request, pk, unit_id):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    unit = get_object_or_404(UnitModelo, pk=unit_id, modelo=modelo)
    
    if request.method == 'POST':
        def recursive_delete(u):
            for child in u.sub_unidades.all():
                recursive_delete(child)
            u.delete()
        recursive_delete(unit)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))})

    return redirect('modelo_referencial_build', pk=pk)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def _duplicated_modelo_referencial_unit_up(request, pk, unit_id):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    unit = get_object_or_404(UnitModelo, pk=unit_id, modelo=modelo)
    irmaos = list(UnitModelo.objects.filter(modelo=modelo, unidade_pai=unit.unidade_pai).order_by('ordem', 'id'))
    try:
        idx = irmaos.index(unit)
        if idx > 0:
            vizinho = irmaos[idx - 1]
            unit.ordem, vizinho.ordem = vizinho.ordem, unit.ordem
            unit.save(); vizinho.save()
    except ValueError: pass
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))})
    return redirect('modelo_referencial_build', pk=pk)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def _duplicated_modelo_referencial_unit_down(request, pk, unit_id):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    unit = get_object_or_404(UnitModelo, pk=unit_id, modelo=modelo)
    irmaos = list(UnitModelo.objects.filter(modelo=modelo, unidade_pai=unit.unidade_pai).order_by('ordem', 'id'))
    try:
        idx = irmaos.index(unit)
        if idx < len(irmaos) - 1:
            vizinho = irmaos[idx + 1]
            unit.ordem, vizinho.ordem = vizinho.ordem, unit.ordem
            unit.save(); vizinho.save()
    except ValueError: pass
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))})
    return redirect('modelo_referencial_build', pk=pk)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def _duplicated_modelo_referencial_agrupar(request, pk):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    if request.method == 'POST':
        unidades_ids = request.POST.getlist('unidades_selecionadas')
        nome_grupo = request.POST.get('nome_grupo', 'Caixa de Agrupamento')
        unidades = UnitModelo.objects.filter(id__in=unidades_ids, modelo=modelo)
        
        topo = unidades.first() # Simplificado para modelos
        pai_comum = topo.unidade_pai if topo else None
        
        grupo = UnitModelo.objects.create(
            modelo=modelo,
            nome_unidade=nome_grupo,
            unidade_pai=pai_comum,
            is_agrupamento=True
        )
        for u in unidades:
            u.unidade_pai = grupo
            u.save()
            
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id')), 'new_group_id': str(grupo.id)})
    return redirect('modelo_referencial_build', pk=pk)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def _duplicated_modelo_referencial_desagrupar(request, pk, unit_id):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    grupo = get_object_or_404(UnitModelo, pk=unit_id, modelo=modelo, is_agrupamento=True)
    if request.method == 'POST':
        pai = grupo.unidade_pai
        for filho in grupo.sub_unidades.all():
            filho.unidade_pai = pai
            filho.save()
        grupo.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))})
    return redirect('modelo_referencial_build', pk=pk)
@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def modelo_referencial_list(request):
    modelos = ModeloReferencial.objects.all().order_by('-data_criacao')
    return render(request, 'core/modelo_referencial_list.html', {'modelos': modelos})

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def modelo_referencial_form(request, pk=None):
    instance = get_object_or_404(ModeloReferencial, pk=pk) if pk else None
    if request.method == 'POST':
        form = ModeloReferencialForm(request.POST, instance=instance)
        if form.is_valid():
            modelo = form.save()
            messages.success(request, f'Modelo "{modelo.nome}" {"atualizado" if pk else "criado"} com sucesso!')
            return redirect('modelo_referencial_build', pk=modelo.pk)
    else:
        form = ModeloReferencialForm(instance=instance)
    
    return render(request, 'core/configuracoes_form.html', {
        'form': form,
        'title': 'Editar Modelo Referencial' if pk else 'Novo Modelo Referencial',
        'back_url': 'modelo_referencial_list'
    })

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def modelo_referencial_build(request, pk):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    unidades = modelo.unidades.all().order_by('ordem', 'id')
    
    edit_id = request.GET.get('edit')
    unit_instance = None
    if edit_id:
        unit_instance = get_object_or_404(UnitModelo, pk=edit_id, modelo=modelo)

    if request.method == 'POST':
        form = UnitModeloForm(request.POST, instance=unit_instance, modelo=modelo)
        if form.is_valid():
            unit = form.save(commit=False)
            unit.modelo = modelo
            
            # Auto-fill cargo padrao only when empty and type is single-cargo
            if (
                unit.tipo_unidade
                and unit.tipo_unidade.cargo_padrao
                and not unit.cargo_funcao_ref
                and not form.cleaned_data.get('permite_resolucao_flexivel')
                and not unit.tipo_unidade.permite_escolha_entre_cargos
            ):
                unit.cargo_funcao_ref = unit.tipo_unidade.cargo_padrao

            if not unit_instance:
                from django.db.models import Max
                max_ordem = UnitModelo.objects.filter(
                    modelo=modelo,
                    unidade_pai=form.cleaned_data.get('unidade_pai')
                ).aggregate(Max('ordem'))['ordem__max'] or 0
                unit.ordem = max_ordem + 1
            unit.save()
            form.save_m2m()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                unidades_list = _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))
                return JsonResponse({'status': 'success', 'data': unidades_list, 'new_node_id': str(unit.id), 'is_edit': bool(unit_instance)})

            return redirect('modelo_referencial_build', pk=modelo.id)
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    else:
        form = UnitModeloForm(instance=unit_instance, modelo=modelo)

    context = {
        'modelo': modelo,
        'form': form,
        'unidades_json': json.dumps(_get_unidades_modelo_json_data(unidades)),
        'is_modelo_builder': True,
        'next_url': reverse('modelo_referencial_list'),
        'allow_structure_changes': True,
        'organograma_export_filename': f'modelo-referencial-{modelo.pk}',
        # Variáveis que o template compartilhado espera
        'todos_campi_json': None,
        'backlinks': [],
        'linked_orgs': [],
        'sigla_prefix': '' # Modelos não têm prefixo fixo
    }
    return render(request, 'core/organograma_builder.html', context)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def modelo_referencial_unit_delete(request, pk, unit_id):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    unit = get_object_or_404(UnitModelo, pk=unit_id, modelo=modelo)
    
    if request.method == 'POST':
        def recursive_delete(u):
            for child in u.sub_unidades.all():
                recursive_delete(child)
            u.delete()
        recursive_delete(unit)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))})

    return redirect('modelo_referencial_build', pk=pk)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def modelo_referencial_unit_up(request, pk, unit_id):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    unit = get_object_or_404(UnitModelo, pk=unit_id, modelo=modelo)
    irmaos = list(UnitModelo.objects.filter(modelo=modelo, unidade_pai=unit.unidade_pai).order_by('ordem', 'id'))
    try:
        idx = irmaos.index(unit)
        if idx > 0:
            vizinho = irmaos[idx - 1]
            unit.ordem, vizinho.ordem = vizinho.ordem, unit.ordem
            unit.save(); vizinho.save()
    except ValueError: pass
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))})
    return redirect('modelo_referencial_build', pk=pk)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def modelo_referencial_unit_down(request, pk, unit_id):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    unit = get_object_or_404(UnitModelo, pk=unit_id, modelo=modelo)
    irmaos = list(UnitModelo.objects.filter(modelo=modelo, unidade_pai=unit.unidade_pai).order_by('ordem', 'id'))
    try:
        idx = irmaos.index(unit)
        if idx < len(irmaos) - 1:
            vizinho = irmaos[idx + 1]
            unit.ordem, vizinho.ordem = vizinho.ordem, unit.ordem
            unit.save(); vizinho.save()
    except ValueError: pass
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))})
    return redirect('modelo_referencial_build', pk=pk)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def modelo_referencial_agrupar(request, pk):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    if request.method == 'POST':
        unidades_ids = request.POST.getlist('unidades_selecionadas')
        nome_grupo = request.POST.get('nome_grupo', 'Caixa de Agrupamento')
        unidades = UnitModelo.objects.filter(id__in=unidades_ids, modelo=modelo)
        
        topo = unidades.first() # Simplificado para modelos
        pai_comum = topo.unidade_pai if topo else None
        
        grupo = UnitModelo.objects.create(
            modelo=modelo,
            nome_unidade=nome_grupo,
            unidade_pai=pai_comum,
            is_agrupamento=True
        )
        for u in unidades:
            u.unidade_pai = grupo
            u.save()
            
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id')), 'new_group_id': str(grupo.id)})
    return redirect('modelo_referencial_build', pk=pk)

@login_required(login_url='/admin/login/')
@user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')
def modelo_referencial_desagrupar(request, pk, unit_id):
    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    grupo = get_object_or_404(UnitModelo, pk=unit_id, modelo=modelo, is_agrupamento=True)
    if request.method == 'POST':
        pai = grupo.unidade_pai
        for filho in grupo.sub_unidades.all():
            filho.unidade_pai = pai
            filho.save()
        grupo.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'status': 'success', 'data': _get_unidades_modelo_json_data(modelo.unidades.all().order_by('ordem', 'id'))})
    return redirect('modelo_referencial_build', pk=pk)


@login_required(login_url='/admin/login/')
def modelo_regras_form(request, pk):
    if not request.user.is_staff:
        raise PermissionDenied("Apenas administradores podem configurar regras de negócio.")

    modelo = get_object_or_404(ModeloReferencial, pk=pk)
    regras, created = RegrasAlteracaoModelo.objects.get_or_create(modelo_referencial=modelo)
    if created:
        regras = apply_rule_defaults(regras)
        regras.save()

    if request.method == 'POST':
        form = RegrasAlteracaoModeloForm(request.POST, instance=regras)
        cotas_formset = ModeloReferencialCotaCargoFormSet(request.POST, instance=modelo, prefix='cotas')
        if form.is_valid() and cotas_formset.is_valid():
            form.save()
            cotas_formset.save()
            messages.success(request, f'Regras para o modelo "{modelo.nome}" salvas com sucesso!')
            return redirect('modelo_regras_editar', pk=modelo.pk)
    else:
        form = RegrasAlteracaoModeloForm(instance=regras)
        cotas_formset = ModeloReferencialCotaCargoFormSet(instance=modelo, prefix='cotas')

    return render(request, 'core/regras_form.html', {
        'form': form,
        'modelo': modelo,
        'cotas_formset': cotas_formset,
    })
