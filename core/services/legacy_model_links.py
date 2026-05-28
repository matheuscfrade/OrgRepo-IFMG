"""Helpers for matching legacy units to reference-model units."""

from difflib import SequenceMatcher


GENERIC_PREFIXES = (
    "secao de",
    "seção de",
    "setor de",
    "setor ou secao de",
    "setor ou seção de",
)


def normalize_unit_name(name):
    normalized = (name or "").strip().lower()
    for prefix in GENERIC_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    return normalized


def find_best_model_unit_match(unit, model_units):
    best_match = None
    best_ratio = 0.0
    base_name = normalize_unit_name(unit.nome_unidade)

    for model_unit in model_units:
        model_name = normalize_unit_name(model_unit.nome_unidade)
        ratio = SequenceMatcher(None, base_name, model_name).ratio()

        if model_name and (model_name in base_name or base_name in model_name):
            ratio += 0.2

        if (
            unit.sigla_cargo
            and model_unit.cargo_funcao_ref
            and unit.sigla_cargo == model_unit.cargo_funcao_ref.sigla
        ):
            ratio += 0.3

        if ratio > best_ratio:
            best_ratio = ratio
            best_match = model_unit

    return best_match, best_ratio
