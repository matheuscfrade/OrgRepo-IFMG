"""
Importa competências dos PDFs de regimento vigente para unidades do organograma
OFICIAL cujo nome bate EXATAMENTE com o nome extraído da linha "Compete a/à/ao ...".

Formato gravado (igual aos já existentes):
  - caput: artigo=X, inciso='', texto='Compete à ...' ou texto introdutório
  - itens:  artigo=X, inciso='I'|'II'|..., texto=conteúdo do inciso

Reitoria: processa INTERNO e GERAL (cada competência com regimento correto).
Demais campi: só INTERNO.

Não sobrescreve unidades que já têm competências (n>0).

Uso:
  python scripts/import_competencias_exact_names.py           # aplica
  python scripts/import_competencias_exact_names.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

import django

django.setup()

from django.conf import settings
from django.db import transaction
from pypdf import PdfReader

from core.models import (
    Campus,
    CompetenciaUnidade,
    Organograma,
    RegimentoCampus,
    Unit,
)

MEDIA = Path(settings.MEDIA_ROOT)

# Art. 10 / Art. 10. / Art. 10º / Art. 10º.
ART_SPLIT = re.compile(
    r"(?i)(?:^|\n)\s*Art\.?\s*(\d+[ºo°]?)\s*[\.\-–—:]?\s*"
)
# Compete à/ao/a/o ...
COMPETE_HDR = re.compile(
    r"(?is)Compete\s+(à|ao|a|o|às|aos)\s+(.+?)(?:\s*,\s*vinculad[oa]s?\b|\s*:|\s*$)"
)
# I – text / I - text / I) text
INCISO = re.compile(
    r"(?m)^\s*([IVXLCDM]+)\s*[\-\–—\.\)]\s+(.+?)(?=^\s*[IVXLCDM]+\s*[\-\–—\.\)]\s+|\Z)",
    re.S,
)
ALINEA = re.compile(
    r"(?m)^\s*([a-z])\)\s+(.+?)(?=^\s*[a-z]\)\s+|\Z)",
    re.S,
)


def read_pdf(rel) -> str:
    path = MEDIA / str(rel)
    if not path.exists():
        return ""
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    # join hyphenated line breaks: "Planejamento-\nEducacional" -> "PlanejamentoEducacional" then fix spaces
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"\n+", "\n", text)
    return text


def clean_spaces(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return s.strip()


def exact_name(s: str) -> str:
    """Canonical exact name for matching organogram ↔ regimento."""
    s = clean_spaces(s)
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s).strip()
    # drop trailing punctuation
    s = s.rstrip(" .;:")
    return s


def extract_unit_name_from_compete(body: str) -> str | None:
    """
    From article body starting near Compete..., return unit name only.
    'Compete à Diretoria de Ensino, vinculada ao IFMG – Campus Betim:\\nI – ...'
    → 'Diretoria de Ensino'
    """
    m = re.search(
        r"(?is)Compete\s+(?:à|ao|a|o|às|aos)\s+(.+)",
        body,
    )
    if not m:
        return None
    rest = m.group(1)
    # cut at first newline after start, or at vinculad, or colon
    # take first line-ish
    rest = rest.replace("\n", " ")
    rest = re.sub(r"\s+", " ", rest).strip()
    # stop at vinculad...
    rest = re.split(r",\s*vinculad[oa]s?\b", rest, maxsplit=1, flags=re.I)[0]
    # stop at colon
    if ":" in rest:
        rest = rest.split(":", 1)[0]
    # stop before first inciso marker if glued
    rest = re.split(r"\s+[IVXLCDM]+\s*[\-\–—\.\)]\s+", rest, maxsplit=1)[0]
    return exact_name(rest)


def parse_incisos(block: str) -> list[tuple[str, str]]:
    """Return list of (inciso_roman, texto). Stops before parágrafo único / titles."""
    block = clean_spaces(block)
    # Do not swallow parágrafo único or section titles into the last inciso
    block = re.split(
        r"(?im)^\s*(Parágrafo\s+único|Paragrafo\s+unico|Subseção|Seção|Capítulo|Título|Art\.?\s*\d+)\b",
        block,
        maxsplit=1,
    )[0]
    # Ensure incisos start on own lines: "I - text" or "I. text"
    block = re.sub(r"(?<!\n)\s+([IVXLCDM]+)\s*[\-\–—\.\)]\s+", r"\n\1 – ", block)
    items = []
    for m in re.finditer(
        r"(?m)^\s*([IVXLCDM]+)\s*[\-\–—\.\)]\s+(.+?)(?=^\s*[IVXLCDM]+\s*[\-\–—\.\)]\s+|\Z)",
        block,
        re.S,
    ):
        roman = m.group(1).upper()
        texto = clean_spaces(m.group(2).replace("\n", " "))
        texto = re.sub(r"\s+", " ", texto).strip()
        # Cut if parágrafo único leaked mid-line
        texto = re.split(r"(?i)\s*Parágrafo\s+único\.?", texto, maxsplit=1)[0].strip()
        # Discard SEI footer noise
        texto = re.split(r"\d{1,2}/\d{1,2}/\d{4}.*?SEI/IFMG", texto, maxsplit=1)[0].strip()
        texto = re.split(r"https?://sei\.ifmg\.edu\.br\S*", texto, maxsplit=1)[0].strip()
        if re.match(r"^(Setor|Seção|Secao|Coordenadoria|Diretoria|Núcleo|Nucleo)\b", texto, re.I):
            continue
        if len(texto) < 12:
            continue
        if texto:
            items.append((roman, texto))
    return items


def parse_paragrafo_unico(block: str) -> tuple[str, list[tuple[str, str]]] | None:
    """
    After incisos, optional:
      Parágrafo único. Compete à área de Comunicação...
      a) ...
      b) ...
    Returns (caput_texto, [(alinea, texto), ...]) or None.
    """
    m = re.search(
        r"(?is)Parágrafo\s+único\.?\s*(.+?)(?=\n\s*(?:TÍTULO|CAPÍTULO|Art\.?\s*\d+|Subseção)|\Z)",
        block,
    )
    if not m:
        return None
    body = clean_spaces(m.group(1))
    # caput until first a)
    caput_m = re.match(r"(?s)(.+?)(?=^\s*[a-z]\)\s+|\Z)", body, re.M)
    caput = clean_spaces((caput_m.group(1) if caput_m else body).replace("\n", " "))
    caput = re.sub(r"\s+", " ", caput).strip()
    alines = []
    for am in re.finditer(
        r"(?m)^\s*([a-z])\)\s+(.+?)(?=^\s*[a-z]\)\s+|\Z)",
        body,
        re.S,
    ):
        letra = am.group(1).lower()
        texto = clean_spaces(am.group(2).replace("\n", " "))
        texto = re.sub(r"\s+", " ", texto).strip()
        if texto:
            alines.append((letra, texto))
    return caput, alines


def split_articles(text: str) -> list[tuple[str, str]]:
    """Return list of (artigo_label, body) e.g. ('10', 'Compete...') or ('10º', ...)."""
    parts = ART_SPLIT.split(text)
    # parts: [preamble, num1, body1, num2, body2, ...]
    arts = []
    if len(parts) < 3:
        # no Art. split — whole text as one fake article for GERAL style blocks
        return [("", text)]
    for i in range(1, len(parts), 2):
        num = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        arts.append((num, body))
    return arts


def article_label(num: str) -> str:
    """Normalize to stored form like '10' or '7º' matching existing data."""
    num = num.strip()
    # Prefer keeping ordinal if present
    if re.search(r"[ºo°]$", num, re.I):
        return re.sub(r"[o°]$", "º", num, flags=re.I)
    return num


def parse_regimento_competencias(text: str) -> dict[str, dict]:
    """
    Map exact unit name → {
      'artigo': str,
      'caput': str,  # full Compete... line or intro
      'itens': [(inciso, texto), ...]
    }
    If multiple articles match same name, keep the one with more itens.
    """
    result: dict[str, dict] = {}
    arts = split_articles(text)

    for num, body in arts:
        if not re.search(r"(?i)Compete\s+", body):
            continue
        # may have multiple Compete in one art — take first primary block
        # limit body to this article: until next SEÇÃO/CAPÍTULO if any
        body_use = re.split(
            r"(?i)\n\s*(SEÇÃO|CAPÍTULO|TÍTULO|CAPITULO|Subseção|Subsecao)\b", body
        )[0]
        name = extract_unit_name_from_compete(body_use)
        if not name:
            continue
        # caput text: from Compete through colon or first inciso
        m = re.search(r"(?is)(Compete\s+.+?)(?=\s+[IVXLCDM]+\s*[\-\–—\.\)]\s+|\Z)", body_use)
        if m:
            caput = clean_spaces(m.group(1).replace("\n", " "))
            caput = re.sub(r"\s+", " ", caput).strip()
            if not caput.endswith(":"):
                # ensure style
                if ":" not in caput:
                    caput = caput.rstrip(".") + ":"
        else:
            caput = f"Compete a {name}:"

        # block after caput for incisos
        after = body_use
        cm = re.search(r"(?is)Compete\s+.+?(?=\s+[IVXLCDM]+\s*[\-\–—\.\)]\s+|\Z)", body_use)
        if cm:
            after = body_use[cm.end() :]
        itens = parse_incisos(after)
        par_unico = parse_paragrafo_unico(body_use)
        art = article_label(num) if num else ""
        cand = {
            "artigo": art,
            "caput": caput,
            "itens": itens,
            "paragrafo_unico": par_unico,
            "name": name,
        }
        prev = result.get(name)
        if not prev or len(itens) > len(prev["itens"]):
            result[name] = cand
    return result


def parse_geral_without_art_prefix(text: str) -> dict[str, dict]:
    """
    Regimento Geral often has:
      Art. 14.
      Compete à Procuradoria Federal:
      I – ...
    Already handled by split_articles. Extra: Compete blocks without Art in range —
    also scan standalone Compete headers with following incisos.
    """
    base = parse_regimento_competencias(text)
    # Additional pass: find all Compete headers with position
    for m in re.finditer(r"(?im)^\s*Compete\s+(?:à|ao|a|o|às|aos)\s+.+$", text):
        start = m.start()
        # look back for Art. number within 200 chars
        prev = text[max(0, start - 200) : start]
        am = list(re.finditer(r"Art\.?\s*(\d+[ºo°]?)", prev, re.I))
        art = article_label(am[-1].group(1)) if am else ""
        # body from Compete to next Art. or SEÇÃO
        rest = text[start:]
        rest = re.split(r"(?i)\n\s*Art\.?\s*\d+", rest, maxsplit=1)[0]
        rest = re.split(r"(?i)\n\s*(SEÇÃO|CAPÍTULO|TÍTULO)\b", rest, maxsplit=1)[0]
        name = extract_unit_name_from_compete(rest)
        if not name:
            continue
        caput_m = re.search(
            r"(?is)(Compete\s+.+?)(?=\s+[IVXLCDM]+\s*[\-\–—\.\)]\s+|\Z)", rest
        )
        caput = clean_spaces(caput_m.group(1).replace("\n", " ")) if caput_m else rest.split("\n")[0]
        caput = re.sub(r"\s+", " ", caput).strip()
        after = rest[caput_m.end() :] if caput_m else rest
        itens = parse_incisos(after)
        cand = {"artigo": art, "caput": caput, "itens": itens, "name": name}
        prev = base.get(name)
        if not prev or len(itens) > len(prev["itens"]):
            base[name] = cand
    return base


def build_unit_name_index(units: list[Unit]) -> dict[str, Unit]:
    """Map exact_name(nome) → Unit (first)."""
    idx = {}
    for u in units:
        key = exact_name(u.nome_unidade or "")
        if key and key not in idx:
            idx[key] = u
    return idx


def import_for_campus(campus: Campus, dry_run: bool, replace: bool = False) -> dict:
    org = Organograma.objects.filter(campus=campus, status="OFICIAL").first()
    if not org:
        return {"campus": campus.sigla, "skipped": "sem organograma OFICIAL"}

    units = list(
        Unit.objects.filter(organograma=org, is_agrupamento=False).select_related(
            "tipo_unidade"
        )
    )
    name_index = build_unit_name_index(units)

    # Which regimentos to parse.
    # Reitoria: INTERNO first (detalhe operacional); GERAL fills remaining
    # units only (colegiados / o que o Interno não cobre).
    if campus.sigla == "IFMG":
        reg_types = ["INTERNO", "GERAL"]
    else:
        reg_types = ["INTERNO"]

    stats = {
        "campus": campus.sigla,
        "matched": [],
        "created_comps": 0,
        "skipped_has_text": [],
        "parsed_names": 0,
        "unmatched_reg_names": [],
    }

    for rtipo in reg_types:
        reg = RegimentoCampus.objects.filter(
            campus=campus, tipo=rtipo, vigente=True
        ).first()
        if not reg or not reg.arquivo:
            continue
        text = read_pdf(reg.arquivo)
        if not text:
            continue
        if rtipo == "GERAL":
            parsed = parse_geral_without_art_prefix(text)
        else:
            parsed = parse_regimento_competencias(text)
        stats["parsed_names"] += len(parsed)

        for name, block in parsed.items():
            unit = name_index.get(name)
            if not unit:
                stats["unmatched_reg_names"].append((rtipo, name, block["artigo"]))
                continue
            existing_qs = CompetenciaUnidade.objects.filter(unidade=unit)
            existing = existing_qs.count()
            # Prefer INTERNO: if unit already has any comps (e.g. from Interno pass),
            # do not overwrite with GERAL.
            if existing > 0:
                if rtipo == "GERAL":
                    stats["skipped_has_text"].append(
                        (unit.sigla_unidade, unit.nome_unidade, existing)
                    )
                    continue
                if not replace:
                    stats["skipped_has_text"].append(
                        (unit.sigla_unidade, unit.nome_unidade, existing)
                    )
                    continue

            rows = []
            ordem = 1
            # caput row
            rows.append(
                {
                    "artigo": block["artigo"],
                    "paragrafo": "",
                    "inciso": "",
                    "alinea": "",
                    "texto": block["caput"],
                    "ordem": ordem,
                }
            )
            ordem += 1
            for roman, texto in block["itens"]:
                rows.append(
                    {
                        "artigo": block["artigo"],
                        "paragrafo": "",
                        "inciso": roman,
                        "alinea": "",
                        "texto": texto,
                        "ordem": ordem,
                    }
                )
                ordem += 1
            # Parágrafo único + alíneas (e.g. CRN Art. 24 Comunicação)
            pu = block.get("paragrafo_unico")
            if pu:
                pu_caput, pu_alines = pu
                rows.append(
                    {
                        "artigo": block["artigo"],
                        "paragrafo": "único",
                        "inciso": "",
                        "alinea": "",
                        "texto": pu_caput,
                        "ordem": ordem,
                    }
                )
                ordem += 1
                for letra, texto in pu_alines:
                    rows.append(
                        {
                            "artigo": block["artigo"],
                            "paragrafo": "único",
                            "inciso": "",
                            "alinea": letra,
                            "texto": texto,
                            "ordem": ordem,
                        }
                    )
                    ordem += 1

            stats["matched"].append(
                {
                    "sigla": unit.sigla_unidade,
                    "nome": unit.nome_unidade,
                    "reg": rtipo,
                    "artigo": block["artigo"],
                    "itens": len(block["itens"]),
                    "rows": len(rows),
                }
            )

            if not dry_run:
                with transaction.atomic():
                    if replace and existing > 0:
                        existing_qs.delete()
                    for row in rows:
                        CompetenciaUnidade.objects.create(
                            unidade=unit,
                            regimento=reg,
                            artigo=row["artigo"],
                            paragrafo=row["paragrafo"],
                            inciso=row["inciso"],
                            alinea=row["alinea"],
                            texto=row["texto"],
                            ordem=row["ordem"],
                        )
                stats["created_comps"] += len(rows)
            else:
                stats["created_comps"] += len(rows)

    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace competencias on exact-match units (delete then reimport).",
    )
    parser.add_argument(
        "--campus",
        action="append",
        help="Limit to campus sigla (repeatable). Default: all with OFICIAL org.",
    )
    args = parser.parse_args()

    qs = Campus.objects.order_by("nome")
    if args.campus:
        qs = qs.filter(sigla__in=args.campus)

    print("DRY RUN" if args.dry_run else "APPLYING IMPORT")
    print("Exact name match only; skip units that already have competências.\n")

    total_units = 0
    total_rows = 0
    for campus in qs:
        if not Organograma.objects.filter(campus=campus, status="OFICIAL").exists():
            continue
        st = import_for_campus(campus, dry_run=args.dry_run, replace=args.replace)
        if st.get("skipped"):
            continue
        print(f"=== {st['campus']} ===")
        print(f"  nomes parseados no(s) PDF(s): {st['parsed_names']}")
        print(f"  matches exatos (sem texto prévio): {len(st['matched'])}")
        for m in st["matched"]:
            print(
                f"    + [{m['reg']}] Art.{m['artigo']} {m['sigla'] or '—'} "
                f"{m['nome'][:45]} → {m['rows']} linhas ({m['itens']} incisos)"
            )
        total_units += len(st["matched"])
        total_rows += st["created_comps"]
        # show a few unmatched compete names for transparency
        um = st["unmatched_reg_names"][:8]
        if um:
            print(f"  (regimento cita nomes sem match exato no organograma: {len(st['unmatched_reg_names'])})")
            for rtipo, name, art in um:
                print(f"      · [{rtipo}] Art.{art} {name!r}")

    print(f"\nTOTAL unidades alimentadas: {total_units}")
    print(f"TOTAL linhas de competência: {total_rows}")
    if args.dry_run:
        print("(dry-run — nada gravado)")


if __name__ == "__main__":
    main()
