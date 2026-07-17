"""
Sync organogram documents + unit trees from IFMG official portal sources
(downloaded under var/media/_sync_ifmg/).

Focus:
- Update resolução / organograma / regimento metadata and PDF files
- Rebuild unit trees for Reitoria, CIP, CIT, CPN from SIORG hierarchical PDFs
- Align document names with portal (e.g. Reitoria Res. 51/2026)

Run:
  .venv\\Scripts\\python.exe scripts\\sync_official_ifmg_docs.py
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

import django

django.setup()

from django.db import transaction
from pypdf import PdfReader

from core.models import (
    Campus,
    CargoFuncao,
    Organograma,
    RegimentoCampus,
    ResolucaoEstruturaOrganizacional,
    TipoUnidade,
    Unit,
)
from core.services.cargo_quotas import get_organograma_cargo_quota_summary

SYNC = BASE / "var" / "media" / "_sync_ifmg"
MEDIA = BASE / "var" / "media"


@dataclass
class Node:
    name: str
    sigla: str
    indent: int
    children: list


def parse_siorg(path: Path, campus_sigla_prefix: str | None = None) -> list[tuple[int, str, str]]:
    """
    Return list of (indent_level, name, sigla).

    SIORG PDF lines look like:
      100914 Instituto ... - IFMG          (root, few spaces after code)
      240920      Centro ... - RE-CREAD    (child, more spaces after code)
    Hierarchy is encoded by the gap between the numeric code and the name.
    """
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    rows: list[tuple[int, str, str]] = []
    started = campus_sigla_prefix is None
    for line in text.splitlines():
        if "Página" in line and "Usuário" in line:
            continue
        m = re.match(r"^(\d+)(\s+)(.+)$", line)
        if not m:
            continue
        gap = len(m.group(2))
        # Map gap width to depth (observed: ~1, ~6, ~11, ~16, ~21)
        if gap <= 2:
            level = 0
        elif gap <= 8:
            level = 1
        elif gap <= 13:
            level = 2
        elif gap <= 18:
            level = 3
        else:
            level = 4
        rest = m.group(3).strip()
        if " - " not in rest:
            continue
        name, sigla = rest.rsplit(" - ", 1)
        name, sigla = name.strip(), sigla.strip().replace(" ", "")
        if campus_sigla_prefix:
            # campus root line like "Campus Ipatinga - CIP-IFMG"
            if not started:
                if sigla.upper() in {
                    f"{campus_sigla_prefix}-IFMG",
                    campus_sigla_prefix,
                } or sigla.upper().startswith(campus_sigla_prefix + "-"):
                    if "Campus" in name or "campus" in name or sigla.endswith("-IFMG"):
                        started = True
                        rows.append((0, name, sigla))
                continue
            # stop at next campus (same level-0 style with Campus in name)
            if level <= 1 and "Campus" in name and sigla != rows[0][2] and sigla.endswith("-IFMG"):
                break
            # force children relative to campus root
            rows.append((max(level, 1) if level == 0 else level, name, sigla))
        else:
            # full IFMG file — only RE-* / IFMG root until first Campus
            if rows and (
                name.startswith("Campus ")
                or (sigla.endswith("-IFMG") and sigla != "IFMG")
            ):
                break
            if not rows:
                if sigla != "IFMG":
                    continue
            rows.append((level, name, sigla))
    return rows


def infer_tipo_cargo(name: str) -> tuple[TipoUnidade | None, CargoFuncao | None]:
    n = name.upper()
    tipos = {t.nome: t for t in TipoUnidade.objects.all()}
    cargos_by_sigla = {}
    for c in CargoFuncao.objects.all():
        cargos_by_sigla.setdefault(c.sigla, []).append(c)

    def cargo(sigla: str, prefer_nome: str | None = None):
        opts = cargos_by_sigla.get(sigla) or []
        if prefer_nome:
            for o in opts:
                if o.nome == prefer_nome:
                    return o
        return opts[0] if opts else None

    if n.startswith("PRÓ-REITORIA") or n.startswith("PRO-REITORIA"):
        return tipos.get("Pró-Reitoria"), cargo("CD-02")
    if "REITORIA" in n and "PRÓ" not in n and "PRO-" not in n and n.strip() in {
        "IFMG - REITORIA",
        "INSTITUTO FEDERAL DE EDUCAÇÃO, CIÊNCIA E TECNOLOGIA DE MINAS GERAIS",
    }:
        return tipos.get("Reitoria"), cargo("CD-01")
    if n.startswith("DIRETORIA"):
        # small-campus style default CD-03; CREAD/DCOM/DRI may be CD-04 in organogram
        return tipos.get("Diretoria"), cargo("CD-03", "Diretor(a)")
    if n.startswith("COORDENADORIA"):
        return tipos.get("Coordenadoria"), cargo("CD-04", "Coordenador(a)")
    if n.startswith("DEPARTAMENTO"):
        return tipos.get("Departamento"), cargo("FG-01")
    if n.startswith("SETOR"):
        return tipos.get("Setor"), cargo("FG-01")
    if n.startswith("SEÇÃO") or n.startswith("SECAO"):
        return tipos.get("Seção"), cargo("FG-02")
    if n.startswith("NÚCLEO") or n.startswith("NUCLEO"):
        return tipos.get("Núcleo"), cargo("FG-03")
    if "CAMPUS" in n and n.startswith("CAMPUS"):
        return tipos.get("Campus"), cargo("CD-02")
    if "POLO" in n:
        return tipos.get("Polo de Inovação"), cargo("CD-02")
    return tipos.get("Outro"), None


# Cargo overrides by sigla from organogram PDF (Res. 51)
REITORIA_CARGO_OVERRIDES = {
    "RE-CREAD": ("CD-04", "Diretor(a)"),
    "RE-DCOM": ("CD-04", "Diretor(a)"),
    "RE-DRI": ("CD-04", "Diretor(a)"),
    "RE-GAB": ("CD-03", "Diretor(a)"),  # Chefe de Gabinete CD-03 on organogram
    "RE-ASINT": ("CD-03", "Diretor(a)"),
    "RE-AUDIN": ("FG-01", "Chefe"),
    "RE-OUV": ("FG-01", "Chefe"),
    "RE-CORREG": ("CD-04", "Coordenador(a)"),
    "RE-PROCF": ("CD-03", "Diretor(a)"),
}


def resolve_cargo(sigla_unit: str, name: str) -> CargoFuncao | None:
    tipo, cargo = infer_tipo_cargo(name)
    ov = REITORIA_CARGO_OVERRIDES.get(sigla_unit)
    if ov:
        sigla, prefer = ov
        for c in CargoFuncao.objects.filter(sigla=sigla):
            if c.nome == prefer or prefer in c.nome:
                return c
        return CargoFuncao.objects.filter(sigla=sigla).first()
    return cargo


def copy_pdf(src: Path, dest_rel: str) -> str:
    dest = MEDIA / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest_rel.replace("\\", "/")


def rebuild_units(organograma: Organograma, rows: list[tuple[int, str, str]], extra_roots: list[tuple[str, str]] | None = None):
    """Delete units and recreate from SIORG rows (level, name, sigla)."""
    Unit.objects.filter(organograma=organograma).delete()
    stack: list[tuple[int, Unit]] = []
    created = []
    for level, name, sigla in rows:
        # normalize root campus name
        tipo, _ = infer_tipo_cargo(name)
        cargo = resolve_cargo(sigla, name)
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        unit = Unit.objects.create(
            organograma=organograma,
            unidade_pai=parent,
            nome_unidade=name,
            sigla_unidade=sigla[:50] if sigla else "",
            tipo_unidade=tipo,
            cargo_funcao_ref=cargo,
            sigla_cargo=cargo.sigla if cargo else "",
            ordem=len(created) + 1,
        )
        stack.append((level, unit))
        created.append(unit)

    # Extra institutional bodies under root (if not already present)
    if extra_roots:
        root = created[0] if created else None
        existing = {u.sigla_unidade for u in created}
        for name, sigla in extra_roots:
            if sigla in existing:
                continue
            tipo, _ = infer_tipo_cargo(name)
            cargo = resolve_cargo(sigla, name)
            u = Unit.objects.create(
                organograma=organograma,
                unidade_pai=root,
                nome_unidade=name,
                sigla_unidade=sigla,
                tipo_unidade=tipo,
                cargo_funcao_ref=cargo,
                sigla_cargo=cargo.sigla if cargo else "",
                ordem=len(created) + 1,
            )
            created.append(u)
    return len(Unit.objects.filter(organograma=organograma))


def apply_reitoria_agrupamentos(organograma: Organograma) -> None:
    """
    Visual layout under Reitoria (L→R):
      CONSUP → IFMG (layout H)
        1. Diretorias de Implantação
        2. Unidades de Assessoramento (incl. Procuradoria)
        3. Pró-Reitorias
        4. Unidades Sistêmicas (GAB, DCOM, DRI, CREAD, CEXP, DTI, DDI, …)
    """
    consup = Unit.objects.filter(organograma=organograma, sigla_unidade="CONSUP").first()
    if not consup:
        consup = Unit.objects.create(
            organograma=organograma,
            nome_unidade="Conselho Superior",
            sigla_unidade="CONSUP",
            tipo_unidade=TipoUnidade.objects.filter(nome="Outro").first(),
            ordem=0,
        )
    ifmg = Unit.objects.filter(organograma=organograma, sigla_unidade="IFMG").first()
    if not ifmg:
        return

    consup.unidade_pai = None
    consup.ordem = 0
    consup.layout_filhos = "V"
    consup.save(update_fields=["unidade_pai", "ordem", "layout_filhos"])
    ifmg.unidade_pai = consup
    ifmg.layout_filhos = "H"
    ifmg.save(update_fields=["unidade_pai", "layout_filhos"])

    def get_or_create_group(nome: str, ordem: int) -> Unit:
        u = Unit.objects.filter(
            organograma=organograma, nome_unidade=nome, is_agrupamento=True
        ).first()
        if not u:
            u = Unit.objects.create(
                organograma=organograma,
                unidade_pai=ifmg,
                nome_unidade=nome,
                sigla_unidade="",
                is_agrupamento=True,
                ordem=ordem,
                layout_filhos="H",
            )
        else:
            u.unidade_pai = ifmg
            u.is_agrupamento = True
            u.ordem = ordem
            u.layout_filhos = "H"
            u.save()
        return u

    implant_group = get_or_create_group("Diretorias de Implantação", 10)
    assess_group = get_or_create_group("Unidades de Assessoramento", 20)
    pro_group = get_or_create_group("Pró-Reitorias", 30)
    sist_group = get_or_create_group("Unidades Sistêmicas", 40)

    for i, sig in enumerate(
        ["RE-DCBH", "RE-DCBD", "RE-DCCG", "RE-DCJM"], start=1
    ):
        u = Unit.objects.filter(organograma=organograma, sigla_unidade=sig).first()
        if u:
            u.unidade_pai = implant_group
            u.ordem = i
            u.save(update_fields=["unidade_pai", "ordem"])

    # Procuradoria com assessoramento (como no layout anterior)
    for i, sig in enumerate(
        ["CODIR", "RE-ASINT", "RE-AUDIN", "RE-CORREG", "RE-OUV", "RE-PROCF"], start=1
    ):
        u = Unit.objects.filter(organograma=organograma, sigla_unidade=sig).first()
        if u:
            u.unidade_pai = assess_group
            u.ordem = i
            u.save(update_fields=["unidade_pai", "ordem"])

    for i, sig in enumerate(
        ["RE-PROAP", "RE-PROEN", "RE-PROEX", "RE-PROGEP", "RE-PRIPPG"], start=1
    ):
        u = Unit.objects.filter(organograma=organograma, sigla_unidade=sig).first()
        if u:
            u.unidade_pai = pro_group
            u.ordem = i
            u.save(update_fields=["unidade_pai", "ordem"])

    for i, sig in enumerate(
        ["RE-GAB", "RE-DCOM", "RE-DRI", "RE-CREAD", "RE-CEXP", "RE-DTI", "RE-DDI"],
        start=1,
    ):
        u = Unit.objects.filter(organograma=organograma, sigla_unidade=sig).first()
        if u:
            u.unidade_pai = sist_group
            u.ordem = i
            u.save(update_fields=["unidade_pai", "ordem"])

    grouped = {
        "RE-DCBH", "RE-DCBD", "RE-DCCG", "RE-DCJM",
        "CODIR", "RE-ASINT", "RE-AUDIN", "RE-CORREG", "RE-OUV", "RE-PROCF",
        "RE-PROAP", "RE-PROEN", "RE-PROEX", "RE-PROGEP", "RE-PRIPPG",
        "RE-GAB", "RE-DCOM", "RE-DRI", "RE-CREAD", "RE-CEXP", "RE-DTI", "RE-DDI",
        "CONSUP", "IFMG",
    }
    for u in Unit.objects.filter(organograma=organograma, unidade_pai=ifmg, is_agrupamento=False):
        if u.sigla_unidade and u.sigla_unidade not in grouped:
            u.unidade_pai = sist_group
            u.save(update_fields=["unidade_pai"])

    for u in Unit.objects.filter(organograma=organograma, unidade_pai__isnull=True).exclude(
        pk=consup.pk
    ):
        if u.pk == ifmg.pk:
            ifmg.unidade_pai = consup
            ifmg.save(update_fields=["unidade_pai"])
        elif not u.is_agrupamento:
            u.unidade_pai = sist_group
            u.save(update_fields=["unidade_pai"])


def update_docs():
    """Update document metadata + files for changed resolutions."""
    updates = [
        # campus_sigla, res_title, res_numero, res_date, src_pdf, dest_name
        (
            "IFMG",
            "Resolução ad referendum nº 51 de 12/06/2026",
            "Resolução ad referendum nº 51 de 12/06/2026",
            date(2026, 6, 12),
            SYNC / "estruturas" / "IFMG_res_51_2026.pdf",
            "documentos_aprovacao/IFMG_resolucao_ad_referendum_51_2026.pdf",
        ),
        (
            "CIP-IFMG",
            "Resolução nº 22 de 27/03/2026",
            "Resolução nº 22 de 27/03/2026",
            date(2026, 3, 27),
            SYNC / "estruturas" / "CIP_res_22_2026.pdf",
            "documentos_aprovacao/CIP_resolucao_22_2026.pdf",
        ),
        (
            "CIT-IFMG",
            "Resolução nº 21 de 27/03/2026",
            "Resolução nº 21 de 27/03/2026",
            date(2026, 3, 27),
            SYNC / "estruturas" / "CIT_res_21_2026.pdf",
            "documentos_aprovacao/CIT_resolucao_21_2026.pdf",
        ),
        (
            "CPN-IFMG",
            "Resolução nº 20 de 27/03/2026",
            "Resolução nº 20 de 27/03/2026",
            date(2026, 3, 27),
            SYNC / "estruturas" / "CPN_res_20_2026.pdf",
            "documentos_aprovacao/CPN_resolucao_20_2026.pdf",
        ),
    ]
    for campus_sigla, title, numero, d, src, dest_rel in updates:
        if not src.exists():
            print(f"  SKIP missing {src}")
            continue
        rel = copy_pdf(src, dest_rel)
        campus = Campus.objects.get(sigla=campus_sigla)
        org = Organograma.objects.filter(campus=campus, status="OFICIAL").first()
        if org:
            org.nome_documento_aprovacao = title
            org.documento_aprovacao = rel
            org.data_vigencia = d
            org.save()
            print(f"  Organograma {campus_sigla}: {title}")
        # update or create resolução
        res = (
            ResolucaoEstruturaOrganizacional.objects.filter(campus=campus)
            .exclude(nome__iexact="teste")
            .order_by("-id")
            .first()
        )
        if res:
            res.nome = f"Estrutura Organizacional - {campus.nome}"
            res.numero = numero
            res.data_publicacao = d
            res.arquivo = rel
            res.save()
        else:
            ResolucaoEstruturaOrganizacional.objects.create(
                campus=campus,
                nome=f"Estrutura Organizacional - {campus.nome}",
                numero=numero,
                data_publicacao=d,
                arquivo=rel,
            )
        # link resolucao on organograma if field exists
        if org and hasattr(org, "resolucao_estrutura") and res:
            org.resolucao_estrutura = res
            org.save(update_fields=["resolucao_estrutura"])

    # Polo regimento PDF refresh
    polo_src = SYNC / "regimentos" / "POLO_4701.pdf"
    if polo_src.exists():
        rel = copy_pdf(polo_src, "regimentos_campus/Portaria_n4701_21_08_2025_Polo.pdf")
        polo = Campus.objects.get(sigla="POLO-IFMG")
        reg = RegimentoCampus.objects.filter(campus=polo, tipo="INTERNO", vigente=True).first()
        if reg:
            reg.arquivo = rel
            reg.numero = "Portaria nº 4701 de 21/08/2025"
            reg.nome = "Regimento Interno - IFMG Polo de Inovação"
            reg.data_publicacao = date(2025, 8, 21)
            reg.save()
            print("  Regimento Polo atualizado")

    # Remove test resolucao
    deleted, _ = ResolucaoEstruturaOrganizacional.objects.filter(nome__iexact="teste").delete()
    if deleted:
        print(f"  Removidas {deleted} resolução(ões) de teste")


def main():
    print("=== 1) Documentos oficiais (resoluções/regimentos) ===")
    with transaction.atomic():
        update_docs()

    print("\n=== 2) Rebuild Reitoria from SIORG + corpos institucionais ===")
    siorg_ifmg = SYNC / "estruturas" / "IFMG_siorg.pdf"
    rows = parse_siorg(siorg_ifmg, campus_sigla_prefix=None)
    # Fix root name
    if rows and rows[0][2] == "IFMG":
        rows[0] = (0, "IFMG - Reitoria", "IFMG")
    # Add implantacao units from organogram PDF (not only Belo Horizonte in SIORG)
    # SIORG has RE-DCBH Belo Horizonte; organogram has Bom Despacho, Contagem, João Monlevade
    # Prefer organogram PDF names for implantação: keep SIORG DCBH if present, add missing
    existing_siglas = {r[2] for r in rows}
    extras = [
        (1, "Diretoria de Implantação campus Bom Despacho", "RE-DCBD"),
        (1, "Diretoria de Implantação campus Contagem", "RE-DCCG"),
        (1, "Diretoria de Implantação campus João Monlevade", "RE-DCJM"),
        (1, "Ouvidoria", "RE-OUV"),
        (1, "Corregedoria", "RE-CORREG"),
        (1, "Procuradoria Federal", "RE-PROCF"),
        (1, "Colégio de Dirigentes", "CODIR"),
        (1, "Conselho Superior", "CONSUP"),
    ]
    # insert extras after root at level 1
    for ex in extras:
        if ex[2] not in existing_siglas:
            rows.append(ex)

    org = Organograma.objects.get(campus__sigla="IFMG", status="OFICIAL")
    with transaction.atomic():
        n = rebuild_units(org, rows)
        apply_reitoria_agrupamentos(org)
        n = Unit.objects.filter(organograma=org).count()
    print(f"  Reitoria units: {n} (com agrupamentos visuais)")

    print("\n=== 3) Rebuild CIP / CIT / CPN from SIORG ===")
    campus_maps = [
        ("CIP-IFMG", "CIP", SYNC / "estruturas" / "CIP_siorg.pdf"),
        ("CIT-IFMG", "CIT", SYNC / "estruturas" / "CIT_siorg.pdf"),
        ("CPN-IFMG", "CPN", SYNC / "estruturas" / "CPN_siorg.pdf"),
    ]
    for campus_sigla, prefix, path in campus_maps:
        if not path.exists():
            print(f"  SKIP {campus_sigla}: no {path}")
            continue
        rows = parse_siorg(path, campus_sigla_prefix=prefix)
        if not rows:
            print(f"  SKIP {campus_sigla}: empty parse")
            continue
        # root name cleanup
        campus = Campus.objects.get(sigla=campus_sigla)
        rows[0] = (0, campus.nome if "Campus" in campus.nome else f"IFMG campus {campus.nome}", campus_sigla)
        org = Organograma.objects.get(campus=campus, status="OFICIAL")
        with transaction.atomic():
            n = rebuild_units(org, rows)
        print(f"  {campus_sigla}: {n} units")

    print("\n=== 4) Sync cargo quotas ===")
    from django.core.management import call_command

    call_command("sync_cargo_quotas")

    print("\n=== Summary official docs ===")
    for o in Organograma.objects.filter(status="OFICIAL").select_related("campus").order_by("campus__sigla"):
        u = Unit.objects.filter(organograma=o).count()
        print(f"  {o.campus.sigla:12} units={u:3} doc={o.nome_documento_aprovacao}")


if __name__ == "__main__":
    main()
