import re


CD_FG_RE = re.compile(r'^(CD|FG)[\s-]*0*(\d+)$', re.IGNORECASE)


def normalize_cargo_sigla(sigla):
    value = (sigla or '').strip().upper()
    match = CD_FG_RE.match(value)
    if not match:
        return value
    return f"{match.group(1).upper()}-{int(match.group(2))}"


def is_cd_fg_sigla(sigla):
    return bool(CD_FG_RE.match((sigla or '').strip()))


def _sort_key(item):
    normalized = normalize_cargo_sigla(item.get('sigla') or item.get('display_sigla'))
    match = CD_FG_RE.match(normalized)
    if not match:
        return (2, normalized, 0)
    prefix_order = 0 if match.group(1).upper() == 'CD' else 1
    return (prefix_order, '', int(match.group(2)))


def _unit_cargo_sigla(unit):
    if unit.cargo_funcao_ref_id:
        return unit.cargo_funcao_ref.sigla
    if unit.sigla_cargo:
        return unit.sigla_cargo
    return unit.cargo_funcao


def _quota_rows_for_organograma(organograma):
    if organograma.campus.sigla == 'IFMG':
        return organograma.campus.cotas_cargos.select_related('cargo_funcao')
    modelo = organograma.modelo_referencial_efetivo
    if not modelo:
        return []
    return modelo.cotas_cargos.select_related('cargo_funcao')


def get_organograma_cargo_quota_summary(organograma):
    quotas = {}
    for quota in _quota_rows_for_organograma(organograma):
        sigla = quota.cargo_funcao.sigla
        if not is_cd_fg_sigla(sigla):
            continue
        key = normalize_cargo_sigla(sigla)
        current = quotas.setdefault(key, {
            'sigla': sigla,
            'limit': 0,
        })
        current['limit'] += quota.quantidade

    used = {}
    units = organograma.unidades.filter(is_agrupamento=False).select_related('cargo_funcao_ref')
    for unit in units:
        sigla = _unit_cargo_sigla(unit)
        if not is_cd_fg_sigla(sigla):
            continue
        key = normalize_cargo_sigla(sigla)
        current = used.setdefault(key, {
            'sigla': sigla,
            'used': 0,
        })
        current['used'] += 1

    items = []
    keys = set(quotas) | set(used)
    for key in keys:
        quota = quotas.get(key, {})
        usage = used.get(key, {})
        limit = quota.get('limit', 0)
        used_count = usage.get('used', 0)
        missing_quota = used_count > 0 and limit == 0
        status = 'ok'
        if used_count > limit:
            status = 'exceeded'
        elif used_count < limit:
            status = 'unallocated'
        items.append({
            'key': key,
            'sigla': quota.get('sigla') or usage.get('sigla') or key,
            'used': used_count,
            'limit': limit,
            'remaining': max(limit - used_count, 0),
            'exceeded': used_count > limit,
            'unallocated': used_count < limit,
            'missing_quota': missing_quota,
            'status': status,
        })

    items.sort(key=_sort_key)
    errors = []
    for item in items:
        if not item['exceeded']:
            continue
        if item['missing_quota']:
            errors.append(
                f"Cargo/funcao {item['sigla']} usado {item['used']} vez(es), mas nao possui cota cadastrada."
            )
        else:
            errors.append(
                f"Limite de cargo/funcao excedido para {item['sigla']}: {item['used']}/{item['limit']}."
            )
    return {
        'items': items,
        'errors': errors,
        'has_exceeded': any(item['exceeded'] for item in items),
        'has_unallocated': any(item['unallocated'] for item in items),
    }
