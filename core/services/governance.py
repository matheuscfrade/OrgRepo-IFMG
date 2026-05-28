import unicodedata

from ..models import ModeloReferencial, RegrasAlteracaoModelo, Unit
from .cargo_quotas import get_organograma_cargo_quota_summary


ALTERATION_LABELS = {
    'renomeacao': 'Renomeação',
    'mudanca_vinculo': 'Mudança de vínculo',
    'alteracao_cargo': 'Alteração de cargo',
    'alteracao_tipo_unidade': 'Alteração de tipo de unidade',
    'alteracao_sigla': 'Alteração de sigla',
    'exclusao_unidade_modelo': 'Ausência de unidade prevista no modelo',
    'inclusao_unidade_nova': 'Unidade adicional na estrutura',
    'flexibilizacao_fg': 'Flexibilização utilizada',
    'conforme_modelo': 'Conforme ao modelo',
}

LEGAL_BASIS = {
    'renomeacao': 'Art. 3º, caput: admite flexibilidade de nomenclatura para unidades FG-01 e FG-02, dentro do limite do §1º.',
    'mudanca_vinculo': 'Art. 3º, caput: admite flexibilidade de vinculação hierárquica para unidades FG-01 e FG-02, dentro do limite do §1º.',
    'alteracao_cargo': 'Art. 3º limita a flexibilidade à nomenclatura e/ou vinculação; alteração de cargo/função não é flexibilização prevista.',
    'alteracao_tipo_unidade': 'Art. 2º e Anexo VII exigem observância dos prefixos de nomenclatura; alteração de tipo fora do modelo não é flexibilização prevista.',
    'alteracao_sigla': 'Art. 3º limita a flexibilidade à nomenclatura e/ou vinculação; alteração de sigla não compõe a cota normativa.',
    'exclusao_unidade_modelo': 'Art. 1º aprova os modelos referenciais dos Anexos I a VI; ausência de unidade prevista rompe a aderência ao modelo.',
    'inclusao_unidade_nova': 'Art. 1º aprova os modelos referenciais dos Anexos I a VI; unidade adicional não está prevista na flexibilização ordinária do Art. 3º.',
    'conforme_modelo': 'Art. 1º: unidade aderente ao modelo referencial aprovado nos Anexos I a VI.',
}

ALTERATION_FIELDS = tuple(key for key in ALTERATION_LABELS if key != 'conforme_modelo')
DOCUMENT_REFERENCE = 'Resolução CONSUP nº 44/2025'
TRANSITION_40_26_LIMIT = 5


def strip_accents(value):
    normalized = unicodedata.normalize('NFKD', value or '')
    return ''.join(ch for ch in normalized if not unicodedata.combining(ch))


def canonical_text(value):
    return ' '.join(strip_accents(value).upper().replace('-', ' ').split())


def split_config(value):
    return [item.strip() for item in (value or '').split(',') if item.strip()]


def default_limit_for_dimensionamento(chave):
    if chave == 'POLO':
        return 1
    if chave in {'40_26', '70_45', '90_70_AGRI'}:
        return 3
    if chave in {'150', '150_AGRI'}:
        return 6
    return 3


def effective_fg_limit(organograma, regras):
    base_limit = default_limit_for_dimensionamento(organograma.campus.dimensionamento_chave)
    configured = regras.limite_flexibilizacao_fg or base_limit
    if regras.permite_regra_transicao and organograma.campus.dimensionamento_chave == '40_26':
        return TRANSITION_40_26_LIMIT
    return configured


def apply_rule_defaults(regras):
    base_limit = default_limit_for_dimensionamento(regras.modelo_referencial.dimensionamento.chave)
    regras.limite_flexibilizacao_fg = base_limit
    regras.prefixos_cargos_bloqueados = regras.prefixos_cargos_bloqueados or 'CD'
    regras.prefixos_cargos_flexibilizaveis = regras.prefixos_cargos_flexibilizaveis or 'FG'
    regras.departamentos_intocaveis = (
        regras.departamentos_intocaveis
        or 'Gestão de Pessoas, Tecnologia da Informação, Assuntos Institucionais'
    )
    regras.verificar_sufixo_anexo = True
    return regras


def ensure_rule_set(modelo):
    regras, created = RegrasAlteracaoModelo.objects.get_or_create(modelo_referencial=modelo)
    if created:
        apply_rule_defaults(regras)
        regras.save()
    return regras


def get_effective_modelo(organograma):
    if organograma.campus.dispensa_modelo_referencial:
        return None
    if organograma.modelo_base_id:
        return organograma.modelo_base
    if organograma.campus.modelo_referencial_padrao_id:
        return organograma.campus.modelo_referencial_padrao
    chave = organograma.campus.dimensionamento_chave
    if not chave:
        return None
    return ModeloReferencial.objects.filter(
        dimensionamento__chave=chave,
        ativo=True,
    ).order_by('id').first()


def ensure_model_reference(organograma, persist=False):
    modelo = get_effective_modelo(organograma)
    if persist and modelo and organograma.pk and organograma.modelo_base_id != modelo.id:
        organograma.modelo_base = modelo
        organograma.save(update_fields=['modelo_base'])
    return modelo


def get_effective_rules(organograma):
    modelo = ensure_model_reference(organograma, persist=True)
    if not modelo:
        return None, None, None
    regras = ensure_rule_set(modelo)
    return modelo, regras, None


def normalized_name(name, is_root=False):
    text = canonical_text(name)
    if is_root or text.startswith('IFMG CAMPUS') or text.startswith('IFMG POLO'):
        return 'IFMG CAMPUS'
    for prefix in (
        'SETOR OU SECAO DE ',
        'SETOR DE ',
        'SECAO DE ',
        'NUCLEO DE ',
        'DIRETORIA DE ',
        'COORDENADORIA DE ',
        'DEPARTAMENTO DE ',
    ):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def candidate_name_key(name, is_root=False):
    text = normalized_name(name, is_root=is_root)
    return text.replace('GESTAO COM PESSOAS', 'GESTAO DE PESSOAS')


def normalized_sigla(sigla):
    return (sigla or '').upper().strip()


def sigla_without_prefix(sigla, campus_prefix=None):
    normalized = normalized_sigla(sigla)
    prefix = normalized_sigla(campus_prefix)
    if prefix and normalized.startswith(f'{prefix}-'):
        return normalized[len(prefix) + 1:].strip()
    return normalized


def siglas_equivalent(current_sigla, model_sigla, campus_prefix=None):
    current = normalized_sigla(current_sigla)
    model = normalized_sigla(model_sigla)
    if not model:
        return True
    if current == model:
        return True
    if sigla_without_prefix(current_sigla, campus_prefix) == model:
        return True
    return False


def cargo_sigla(unit):
    if unit.cargo_funcao_ref_id:
        return normalized_sigla(unit.cargo_funcao_ref.sigla)
    if unit.sigla_cargo:
        return normalized_sigla(unit.sigla_cargo)
    return normalized_sigla(unit.cargo_funcao)


def cargo_signature(unit):
    sigla = cargo_sigla(unit)
    if sigla:
        return f"SIG:{sigla}"
    nome = unit.cargo_funcao_ref.nome if unit.cargo_funcao_ref_id else unit.cargo_funcao
    return f"TXT:{canonical_text(nome)}"


def tipo_signature(unit):
    if not unit.tipo_unidade_id:
        return ''
    return canonical_text(unit.tipo_unidade.nome)


def cargo_matches_prefix(unit, prefixes):
    sigla = cargo_sigla(unit)
    sigla_canon = canonical_text(sigla).replace(' ', '-')
    for prefix in prefixes:
        prefix_canon = canonical_text(prefix).replace(' ', '-')
        if sigla.startswith(prefix.upper()) or sigla_canon.startswith(prefix_canon):
            return True
    if getattr(unit, 'has_flexible_resolution', False):
        allowed_siglas = unit.cargos_resolucao_permitidos.values_list('sigla', flat=True)
        for allowed_sigla in allowed_siglas:
            allowed_canon = canonical_text(allowed_sigla).replace(' ', '-')
            for prefix in prefixes:
                prefix_canon = canonical_text(prefix).replace(' ', '-')
                if normalized_sigla(allowed_sigla).startswith(prefix.upper()) or allowed_canon.startswith(prefix_canon):
                    return True
    return False


def matches_flexible_tipo(unit, model_unit):
    return model_unit.has_flexible_resolution and unit.tipo_unidade_id in model_unit.allowed_tipo_ids


def matches_flexible_cargo(unit, model_unit):
    return model_unit.has_flexible_resolution and unit.cargo_funcao_ref_id in model_unit.allowed_cargo_ids


def compatible_tipo(unit, model_unit):
    if model_unit.has_flexible_resolution:
        return matches_flexible_tipo(unit, model_unit)
    return tipo_signature(unit) == tipo_signature(model_unit)


def compatible_cargo(unit, model_unit):
    if model_unit.has_flexible_resolution:
        return matches_flexible_cargo(unit, model_unit)
    return cargo_signature(unit) == cargo_signature(model_unit)


def same_model_parent(unit, model_unit):
    unit_parent_model_id = None
    if unit.unidade_pai_id and unit.unidade_pai:
        unit_parent_model_id = unit.unidade_pai.origem_modelo_id
    return unit_parent_model_id == model_unit.unidade_pai_id


def structurally_corresponds(unit, model_unit):
    if not same_model_parent(unit, model_unit):
        return False
    if not preserves_annex_prefix(unit.nome_unidade, model_unit.nome_unidade):
        return False
    if not compatible_tipo(unit, model_unit):
        return False
    if not compatible_cargo(unit, model_unit):
        return False
    return True


def name_corresponds(unit, model_unit, *, use_source=False):
    source = getattr(unit, 'source_unit', None) if use_source else None
    name = source.nome_unidade if source else unit.nome_unidade
    is_root = unit.unidade_pai_id is None
    return candidate_name_key(name, is_root=is_root) == candidate_name_key(model_unit.nome_unidade, is_root=model_unit.unidade_pai_id is None)


def candidate_score(unit, model_unit):
    score = 0
    unit_name = candidate_name_key(unit.nome_unidade, is_root=unit.unidade_pai_id is None)
    model_name = candidate_name_key(model_unit.nome_unidade, is_root=model_unit.unidade_pai_id is None)
    if unit_name == model_name:
        score += 100
    campus_prefix = unit.organograma.campus.get_sigla_prefix if getattr(unit, 'organograma', None) else None
    if normalized_sigla(unit.sigla_unidade) and siglas_equivalent(unit.sigla_unidade, model_unit.sigla_unidade, campus_prefix):
        score += 30
    if unit.tipo_unidade_id and compatible_tipo(unit, model_unit):
        score += 10
    if compatible_cargo(unit, model_unit):
        score += 10
    if unit.unidade_pai_id is None and model_unit.unidade_pai_id is None:
        score += 15
    if unit.unidade_pai_id and unit.unidade_pai and unit.unidade_pai.origem_modelo_id == model_unit.unidade_pai_id:
        score += 20
    return score


def sync_units_with_model(organograma, modelo, persist=False):
    model_units = list(modelo.unidades.filter(is_agrupamento=False).select_related('unidade_pai'))
    current_units = list(
        organograma.unidades.filter(is_agrupamento=False)
        .select_related('unidade_pai', 'tipo_unidade', 'cargo_funcao_ref', 'origem_modelo', 'source_unit')
    )
    changed_units = []

    for unit in current_units:
        if not unit.origem_modelo_id:
            continue
        source = getattr(unit, 'source_unit', None)
        if source and not source.origem_modelo_id and not name_corresponds(unit, unit.origem_modelo, use_source=True):
            unit.origem_modelo = None
            changed_units.append(unit)

    used_model_ids = {unit.origem_modelo_id for unit in current_units if unit.origem_modelo_id}

    pending_units = [unit for unit in current_units if not unit.origem_modelo_id]

    for unit in pending_units:
        candidates = []
        for model_unit in model_units:
            if model_unit.id in used_model_ids:
                continue
            score = candidate_score(unit, model_unit)
            if score >= 100:
                candidates.append((score, model_unit))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score = candidates[0][0]
        best = [item for item in candidates if item[0] == best_score]
        if len(best) != 1:
            continue
        unit.origem_modelo = best[0][1]
        used_model_ids.add(best[0][1].id)
        changed_units.append(unit)

    if persist and changed_units:
        Unit.objects.bulk_update(changed_units, ['origem_modelo'])
    units_by_id = {unit.id: unit for unit in current_units}
    for unit in current_units:
        if unit.unidade_pai_id and unit.unidade_pai_id in units_by_id:
            unit.unidade_pai = units_by_id[unit.unidade_pai_id]
    return current_units


def is_link_only_department(model_unit, regras):
    model_name = canonical_text(model_unit.nome_unidade)
    restricted = [canonical_text(item) for item in split_config(regras.departamentos_intocaveis)]
    return any(item and item in model_name for item in restricted)


def nomenclature_prefixes(name):
    text = canonical_text(name)
    if text.startswith('SETOR OU SECAO'):
        return {'SETOR', 'SECAO'}
    for prefix in ('IFMG CAMPUS', 'IFMG POLO', 'DIRETORIA', 'COORDENADORIA', 'DEPARTAMENTO', 'SETOR', 'SECAO', 'NUCLEO'):
        if text.startswith(prefix):
            return {prefix}
    return set()


def preserves_annex_prefix(current_name, model_name):
    expected = nomenclature_prefixes(model_name)
    if not expected:
        return True
    if expected <= {'SETOR', 'SECAO'}:
        current_prefixes = nomenclature_prefixes(current_name)
        return bool(current_prefixes & {'SETOR', 'SECAO'})
    current = canonical_text(current_name)
    return any(current.startswith(prefix) for prefix in expected)


def parent_origin_id(unit):
    if unit.unidade_pai_id and unit.unidade_pai:
        return unit.unidade_pai.origem_modelo_id
    return None


def build_detail_map(unit, origin, campus_prefix):
    changes = []
    details = {}
    normalized_unit_name = normalized_name(unit.nome_unidade, is_root=unit.unidade_pai_id is None)
    normalized_origin_name = normalized_name(origin.nome_unidade, is_root=origin.unidade_pai_id is None)
    prefix_changed = (
        not origin.has_flexible_resolution
        and canonical_text(unit.nome_unidade) != canonical_text(origin.nome_unidade)
        and nomenclature_prefixes(unit.nome_unidade) != nomenclature_prefixes(origin.nome_unidade)
    )
    if normalized_unit_name != normalized_origin_name or prefix_changed:
        changes.append('renomeacao')
        details['renomeacao'] = f"Nome atual: {unit.nome_unidade or '---'} | Modelo: {origin.nome_unidade or '---'}"
    if parent_origin_id(unit) != origin.unidade_pai_id:
        changes.append('mudanca_vinculo')
        pai_atual = unit.unidade_pai.nome_unidade if unit.unidade_pai_id and unit.unidade_pai else 'Raiz'
        pai_modelo = origin.unidade_pai.nome_unidade if origin.unidade_pai_id and origin.unidade_pai else 'Raiz'
        details['mudanca_vinculo'] = f"Vinculo atual: {pai_atual} | Modelo: {pai_modelo}"
    return changes, details


def append_legal_basis(entry, change, text):
    legal = entry.setdefault('fundamentos', {}).setdefault(change, [])
    if text and text not in legal:
        legal.append(text)


def legal_basis_for_entry(entry):
    basis = entry.get('fundamentos', {})
    parts = []
    for change in entry.get('tipos', []):
        items = basis.get(change) or [LEGAL_BASIS.get(change)]
        for item in items:
            if item and item not in parts:
                parts.append(item)
    return parts


def validate_organograma_governance(organograma, persist_links=False):
    modelo, regras, override = get_effective_rules(organograma)
    cargo_quotas = get_organograma_cargo_quota_summary(organograma)
    cargo_quota_errors = cargo_quotas['errors']
    if not modelo:
        if organograma.campus.dispensa_modelo_referencial:
            return {
                'errors': cargo_quota_errors,
                'html': "<br>".join(cargo_quota_errors),
                'counts': {key: 0 for key in ALTERATION_FIELDS},
                'entries': [],
                'report_entries': [],
                'blocking_entries': [],
                'fg_limit': 0,
                'fg_used': 0,
                'fg_remaining': 0,
                'quota_exceeded': False,
                'total': 0,
                'modelo': None,
                'regras': None,
                'override': None,
                'cargo_quotas': cargo_quotas,
                'cargo_quota_errors': cargo_quota_errors,
                'cargo_quota_exceeded': cargo_quotas['has_exceeded'],
                'cargo_quota_unallocated': cargo_quotas['has_unallocated'],
            }
        return {
            'errors': ["O campus precisa ter um Modelo Referencial associado antes de validar o organograma."],
            'html': "O campus precisa ter um Modelo Referencial associado antes de validar o organograma.",
            'counts': {key: 0 for key in ALTERATION_FIELDS},
            'entries': [],
            'total': 0,
            'cargo_quotas': cargo_quotas,
            'cargo_quota_errors': cargo_quota_errors,
            'cargo_quota_exceeded': cargo_quotas['has_exceeded'],
            'cargo_quota_unallocated': cargo_quotas['has_unallocated'],
        }

    current_units = sync_units_with_model(organograma, modelo, persist=persist_links)
    campus_prefix = organograma.campus.get_sigla_prefix
    cd_prefixes = split_config(regras.prefixos_cargos_bloqueados) or ['CD']
    fg_prefixes = split_config(regras.prefixos_cargos_flexibilizaveis) or ['FG']
    counts = {key: 0 for key in ALTERATION_FIELDS}
    entries = []
    report_entries = []
    blocking_entries = []
    matched_model_ids = set()
    errors = []

    def mark_blocking(entry):
        if entry not in blocking_entries:
            blocking_entries.append(entry)

    for unit in current_units:
        origin = unit.origem_modelo
        if not origin:
            counts['inclusao_unidade_nova'] += 1
            entry = {
                'unidade': unit.nome_unidade,
                'modelo': '---',
                'tipos': ['inclusao_unidade_nova'],
                'fundamentos': {'inclusao_unidade_nova': [LEGAL_BASIS['inclusao_unidade_nova']]},
            }
            entries.append(entry)
            report_entries.append(entry)
            errors.append(
                f"{unit.nome_unidade}: unidade adicional não prevista no modelo referencial. A proposta deve manter as unidades do modelo e aplicar apenas as flexibilizações previstas na {DOCUMENT_REFERENCE}."
            )
            mark_blocking(entry)
            continue

        matched_model_ids.add(origin.id)
        unit_changes, detail_map = build_detail_map(unit, origin, campus_prefix)
        if not unit_changes:
            continue

        for change in unit_changes:
            counts[change] += 1
        entry = {
            'unidade': unit.nome_unidade,
            'modelo': origin.nome_unidade,
            'tipos': unit_changes,
            'detalhes': detail_map,
            'fundamentos': {change: [LEGAL_BASIS.get(change)] for change in unit_changes if LEGAL_BASIS.get(change)},
        }
        entries.append(entry)
        report_entries.append(entry)

        if cargo_matches_prefix(origin, cd_prefixes) or cargo_matches_prefix(unit, cd_prefixes):
            errors.append(
                f"{origin.nome_unidade}: unidades com cargo de direção (CD) não são passíveis de flexibilização, conforme {DOCUMENT_REFERENCE}."
            )
            for change in unit_changes:
                append_legal_basis(entry, change, 'Art. 3º, §2º: unidades organizacionais com cargos de direção (CD) constantes dos modelos referenciais não são passíveis de flexibilidade.')
            mark_blocking(entry)
            continue

        disallowed_link_only = [item for item in unit_changes if item != 'mudanca_vinculo']
        if is_link_only_department(origin, regras) and disallowed_link_only:
            errors.append(
                f"{origin.nome_unidade}: esta unidade é flexível apenas quanto à vinculação, conforme {DOCUMENT_REFERENCE}."
            )
            for change in disallowed_link_only:
                append_legal_basis(entry, change, 'Art. 3º, §3º: Gestão de Pessoas, Tecnologia da Informação e Assuntos Institucionais são passíveis de flexibilidade apenas de vinculação.')
            mark_blocking(entry)

        if 'renomeacao' in unit_changes and regras.verificar_sufixo_anexo and not preserves_annex_prefix(unit.nome_unidade, origin.nome_unidade):
            errors.append(
                f"{unit.nome_unidade}: a nomenclatura deve preservar o prefixo previsto no Anexo VII da {DOCUMENT_REFERENCE}."
            )
            append_legal_basis(entry, 'renomeacao', 'Art. 2º e Art. 3º, §1º: nomenclaturas devem manter os prefixos constantes do Anexo VII.')
            mark_blocking(entry)

        if cargo_matches_prefix(origin, fg_prefixes) and any(item in unit_changes for item in ('renomeacao', 'mudanca_vinculo')):
            entry['elegivel_flexibilizacao_fg'] = True
            entry['grupo_flexibilizacao_fg'] = 'presente'

    for model_unit in modelo.unidades.filter(is_agrupamento=False):
        if model_unit.id in matched_model_ids:
            continue
        counts['exclusao_unidade_modelo'] += 1
        entry = {
            'unidade': '---',
            'modelo': model_unit.nome_unidade,
            'tipos': ['exclusao_unidade_modelo'],
            'detalhes': {'exclusao_unidade_modelo': f"Unidade prevista no modelo e ausente na estrutura: {model_unit.nome_unidade}"},
            'fundamentos': {'exclusao_unidade_modelo': [LEGAL_BASIS['exclusao_unidade_modelo']]},
        }
        entries.append(entry)
        report_entries.append(entry)
        errors.append(
            f"{model_unit.nome_unidade}: unidade prevista no modelo referencial ausente na proposta. A proposta deve manter as unidades do modelo e aplicar apenas as flexibilizações previstas na {DOCUMENT_REFERENCE}."
        )
        mark_blocking(entry)

    eligible_fg_entries = [
        entry for entry in entries
        if (
            entry.get('elegivel_flexibilizacao_fg')
            and entry not in blocking_entries
        )
    ]
    for entry in eligible_fg_entries:
        entry['conta_flexibilizacao_fg'] = True
    counts['flexibilizacao_fg'] = len(eligible_fg_entries)

    fg_limit = effective_fg_limit(organograma, regras)
    fg_used = counts['flexibilizacao_fg']
    fg_remaining = max(fg_limit - fg_used, 0)
    quota_exceeded = fg_used > fg_limit
    if quota_exceeded:
        errors.append(
            f"Limite de flexibilização excedido: {fg_used} diferenças permitidas contabilizadas para limite de {fg_limit}, conforme {DOCUMENT_REFERENCE}."
        )

    errors.extend(cargo_quota_errors)

    cargo_quota_alert = ""
    if cargo_quota_errors:
        quota_items = "".join(
            f"<li style=\"margin: 3px 0;\">{error}</li>"
            for error in cargo_quota_errors
        )
        cargo_quota_alert = (
            "<div style=\"margin-top: 12px; padding: 12px 14px; border-radius: 8px; "
            "border: 1px solid #dc2626; background:#fff5f5; color:#7f1d1d; font-size:13px; text-align:left;\">"
            "<strong>Cota de cargos/funcoes do Modelo Referencial excedida.</strong>"
            f"<ul style=\"margin: 8px 0 0 18px; padding: 0;\">{quota_items}</ul>"
            "</div>"
        )

    rows = []
    for entry in report_entries:
        is_blocking = entry in blocking_entries
        labels = "<br>".join(
            f"<strong>{ALTERATION_LABELS[item]}</strong><br><span style=\"font-size: 12px; color: #666;\">{entry.get('detalhes', {}).get(item, '')}</span>"
            for item in entry['tipos']
        )
        legal_basis = legal_basis_for_entry(entry)
        if legal_basis:
            labels += (
                "<br><span style=\"display:block; margin-top: 6px; font-size: 12px; color:#475467;\">"
                "<strong>Base legal:</strong> "
                + " ".join(legal_basis)
                + "</span>"
            )
        if is_blocking:
            labels = (
                "<span style=\"display:inline-block; margin-bottom: 6px; padding: 3px 8px; border-radius: 999px; "
                "background:#fee2e2; color:#991b1b; font-weight:700; font-size: 12px;\">Impeditivo</span><br>"
                + labels
            )
        if entry.get('conta_flexibilizacao_fg'):
            status_note = (
                "<br><span style=\"display:block; margin-top:4px; font-size:11px; color:#92400e;\">CompÃµe o somatÃ³rio excedido</span>"
                if quota_exceeded
                else ""
            )
            if quota_exceeded:
                status_note = "<br><span style=\"display:block; margin-top:4px; font-size:11px; color:#92400e;\">Compoe o somatorio excedido</span>"
            status = (
                "<span style=\"display:inline-block; padding: 3px 8px; border-radius: 999px; background:#fff4e5; color:#92400e; font-weight:700;\">Sim</span>"
                + status_note
            )
        else:
            status = "<span style=\"display:inline-block; padding: 3px 8px; border-radius: 999px; background:#eef2f7; color:#344054; font-weight:700;\">Não</span>"
        row_style = (
            "border-bottom: 1px solid #f2b8b8; background:#fff5f5; border-left: 4px solid #dc2626;"
            if is_blocking
            else "border-bottom: 1px solid #eee;"
        )
        text_color = "#7f1d1d" if is_blocking else "#2c3e50"
        model_color = "#991b1b" if is_blocking else "#7f8c8d"
        rows.append(
            f"<tr style=\"{row_style}\">"
            f"<td style=\"padding: 10px; color: {text_color}; font-weight: 600;\">{entry['unidade']}</td>"
            f"<td style=\"padding: 10px; color: {model_color};\">{entry['modelo']}</td>"
            f"<td style=\"padding: 10px;\">{labels}</td>"
            f"<td style=\"padding: 10px;\">{status}</td>"
            "</tr>"
        )

    html = ""
    if report_entries:
        quota_alert = ""
        if quota_exceeded:
            quota_alert = (
                "<div style=\"margin-top: 12px; padding: 12px 14px; border-radius: 8px; "
                "border: 1px solid #f59e0b; background:#fffbeb; color:#78350f; font-size:13px; text-align:left;\">"
                "<strong>Cota de flexibilizaÃ§Ã£o excedida.</strong> "
                f"O problema estÃ¡ no somatÃ³rio: <b>{fg_used}</b> unidades contam na cota, mas o limite Ã© <b>{fg_limit}</b>. "
                f"Reduza pelo menos <b>{fg_used - fg_limit}</b> unidade(s) contabilizada(s). "
                "As linhas marcadas com <b>Sim</b> apenas compÃµem esse cÃ¡lculo; elas nÃ£o sÃ£o impeditivas isoladamente."
                "</div>"
            )
        if quota_exceeded:
            quota_alert = (
                "<div style=\"margin-top: 12px; padding: 12px 14px; border-radius: 8px; "
                "border: 1px solid #f59e0b; background:#fffbeb; color:#78350f; font-size:13px; text-align:left;\">"
                "<strong>Cota de flexibilizacao excedida.</strong> "
                f"O problema esta no somatorio: <b>{fg_used}</b> unidades contam na cota, mas o limite e <b>{fg_limit}</b>. "
                f"Reduza pelo menos <b>{fg_used - fg_limit}</b> unidade(s) contabilizada(s). "
                "As linhas marcadas com <b>Sim</b> apenas compoem esse calculo; elas nao sao impeditivas isoladamente."
                "</div>"
            )
        html = (
            "<div class='audit-report' style='color: #2c3e50;'>"
            "<b>Pendências de Adequação ao Modelo Referencial</b>"
            f"<p style=\"margin: 8px 0 0; font-size: 13px; color: #666; text-align: left;\">Lista apenas as pendências identificadas em relação ao modelo vigente da {DOCUMENT_REFERENCE}. A coluna de contabilização indica se a diferença permitida entra na cota de flexibilização.</p>"
            + quota_alert +
            cargo_quota_alert +
            "<div style=\"margin-top: 15px; border-radius: 8px; overflow: hidden; border: 1px solid #ddd; font-family: sans-serif;\">"
            "<table style=\"width: 100%; border-collapse: collapse; font-size: 13px;\">"
            "<thead><tr style=\"background: #2E8B57; color: white; text-align: left;\">"
            "<th style=\"padding: 10px;\">Sua Estrutura</th>"
            "<th style=\"padding: 10px;\">Modelo Referencial</th>"
            "<th style=\"padding: 10px;\">Comparação</th>"
            "<th style=\"padding: 10px;\">Conta na cota?</th>"
            "</tr></thead><tbody>"
            + "".join(rows) +
            "</tbody></table></div>"
            f"<p style=\"margin-top: 10px; font-size: 13px; color: #666; text-align: left;\">Flexibilização utilizada: <b>{fg_used}</b> de <b>{fg_limit}</b>. Saldo: <b>{fg_remaining}</b>.</p>"
            "</div>"
        )
    elif cargo_quota_alert:
        html = (
            "<div class='audit-report' style='color: #2c3e50;'>"
            "<b>Pendências de Adequação ao Modelo Referencial</b>"
            + cargo_quota_alert +
            "</div>"
        )
    return {
        'errors': errors,
        'html': html if html else "<br>".join(errors),
        'counts': counts,
        'entries': entries,
        'report_entries': report_entries,
        'blocking_entries': blocking_entries,
        'fg_limit': fg_limit,
        'fg_used': fg_used,
        'fg_remaining': fg_remaining,
        'quota_exceeded': quota_exceeded,
        'total': fg_used,
        'modelo': modelo,
        'regras': regras,
        'override': override,
        'cargo_quotas': cargo_quotas,
        'cargo_quota_errors': cargo_quota_errors,
        'cargo_quota_exceeded': cargo_quotas['has_exceeded'],
        'cargo_quota_unallocated': cargo_quotas['has_unallocated'],
    }
