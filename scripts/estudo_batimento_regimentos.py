"""
Estudo (somente leitura): batimento unidades do organograma OFICIAL
x menção nos PDFs de regimentos vigentes.

Reitoria (IFMG): considera Regimento GERAL + INTERNO.
Demais campi: em geral só INTERNO.

Não altera o banco.
"""
from __future__ import annotations

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
from pypdf import PdfReader

from core.models import (
    Campus,
    CompetenciaUnidade,
    Organograma,
    RegimentoCampus,
    Unit,
)

MEDIA = Path(settings.MEDIA_ROOT)
OUT = BASE / "docs" / "estudo_batimento_regimentos.md"

STOP = {
    "ifmg",
    "campus",
    "unidade",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "com",
    "para",
    "ao",
    "à",
    "a",
    "o",
    "no",
    "na",
    "em",
}


def norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)
    repl = str.maketrans(
        "áàâãäéèêëíìîïóòôõöúùûüç",
        "aaaaaeeeeiiiiooooouuuuc",
    )
    s = s.translate(repl)
    s = re.sub(r"[^a-z0-9\-\s/&]", "", s)
    return s.strip()


def pdf_text(rel) -> tuple[str, Path | None]:
    if not rel:
        return "", None
    path = MEDIA / str(rel)
    if not path.exists():
        return "", path
    try:
        t = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        return t, path
    except Exception as e:  # noqa: BLE001
        return f"__ERR__{e}", path


def unit_keys(u: Unit) -> list[str]:
    keys = []
    if u.nome_unidade:
        keys.append(u.nome_unidade)
        n = re.sub(r"^IFMG\s*[-–]?\s*", "", u.nome_unidade, flags=re.I)
        if n != u.nome_unidade:
            keys.append(n)
        # short distinctive tail
        if " de " in n.lower():
            keys.append(n.split(" de ", 1)[-1])
    if u.sigla_unidade and len(u.sigla_unidade) >= 4:
        keys.append(u.sigla_unidade)
    return [k for k in keys if k and len(k.strip()) >= 4]


def find_in_text(keys: list[str], ntext: str) -> tuple[bool, str | None]:
    if not ntext:
        return False, None
    for k in keys:
        nk = norm(k)
        if len(nk) >= 5 and nk in ntext:
            return True, "exact"
    for k in keys:
        nk = norm(k)
        words = [w for w in nk.split() if len(w) > 3 and w not in STOP]
        if len(words) >= 2:
            hit = sum(1 for w in words if w in ntext)
            if hit / len(words) >= 0.75:
                return True, "words"
    return False, None


def main():
    lines: list[str] = []
    def w(s=""):
        lines.append(s)

    w("# Estudo de batimento: organogramas × regimentos")
    w("")
    w("**Escopo:** somente leitura — nenhuma alteração no banco.")
    w("")
    w("**Método:** para cada unidade do organograma OFICIAL (exceto agrupamentos),")
    w("busca menção do nome/sigla no texto extraído do(s) PDF(s) de regimento vigente.")
    w("")
    w("**Reitoria (IFMG):** regimentos **GERAL** (Res. 46/2025) e **INTERNO** (Port. 845/2021).")
    w("**Demais campi:** em regra só **INTERNO**.")
    w("")
    w("> **Importante:** unidades **não citadas** no PDF **não são necessariamente erro**.")
    w("> Vários regimentos estão em atualização e a estrutura (SIORG/resolução) pode estar")
    w("> à frente do regimento publicado.")
    w("")
    w("---")
    w("")

    summary_rows = []

    for campus in Campus.objects.order_by("nome"):
        org = Organograma.objects.filter(campus=campus, status="OFICIAL").first()
        if not org:
            continue
        units = list(
            Unit.objects.filter(organograma=org, is_agrupamento=False)
            .select_related("tipo_unidade", "unidade_pai")
            .order_by("ordem", "id")
        )
        regs = list(
            RegimentoCampus.objects.filter(campus=campus, vigente=True).order_by("tipo")
        )
        reg_texts: dict[str, dict] = {}
        for r in regs:
            t, p = pdf_text(r.arquivo)
            ok = bool(t) and not t.startswith("__ERR__")
            reg_texts[r.tipo] = {
                "r": r,
                "ntext": norm(t) if ok else "",
                "chars": len(t) if ok else 0,
                "path": p,
                "err": t if t.startswith("__ERR__") else None,
            }

        found, missing = [], []
        for u in units:
            keys = unit_keys(u)
            hits = []
            for tipo, info in reg_texts.items():
                ok, how = find_in_text(keys, info["ntext"])
                if ok:
                    hits.append((tipo, how))
            ncomp = CompetenciaUnidade.objects.filter(unidade=u).count()
            rec = {
                "sigla": u.sigla_unidade or "",
                "nome": u.nome_unidade or "",
                "tipo": u.tipo_unidade.nome if u.tipo_unidade else "",
                "hits": hits,
                "ncomp": ncomp,
            }
            (found if hits else missing).append(rec)

        total_comp = CompetenciaUnidade.objects.filter(unidade__organograma=org).count()
        with_comp = sum(1 for r in found + missing if r["ncomp"] > 0)
        pct = 100 * len(found) / len(units) if units else 0

        summary_rows.append(
            {
                "sigla": campus.sigla,
                "nome": campus.nome,
                "units": len(units),
                "found": len(found),
                "missing": len(missing),
                "pct": pct,
                "comps": total_comp,
                "with_comp": with_comp,
                "regs": regs,
                "reg_texts": reg_texts,
                "found_list": found,
                "missing_list": missing,
            }
        )

    # Tabela resumo
    w("## 1. Resumo por campus")
    w("")
    w("| Campus | Unidades | Citadas no PDF | % | Sem menção | Textos no app | Regimentos vigentes |")
    w("|--------|----------|----------------|---|------------|---------------|---------------------|")
    for s in summary_rows:
        reg_s = ", ".join(
            f"{r.tipo} ({r.numero or '—'}; {s['reg_texts'][r.tipo]['chars']} chars)"
            for r in s["regs"]
        ) or "—"
        w(
            f"| {s['sigla']} | {s['units']} | {s['found']} | {s['pct']:.0f}% | "
            f"{s['missing']} | {s['comps']} em {s['with_comp']} un. | {reg_s} |"
        )
    w("")

    # Reitoria detalhada
    w("## 2. Reitoria (IFMG) — Geral × Interno")
    w("")
    w("O modelo de dados já permite competências ligadas a **dois** regimentos.")
    w("Abaixo: em qual PDF o **nome da unidade** aparece (não avalia o texto da competência).")
    w("")
    reit = next((s for s in summary_rows if s["sigla"] == "IFMG"), None)
    if reit:
        only_g = only_i = both = none = 0
        w("| Unidade | Sigla | Só Geral | Só Interno | Ambos | Nenhum | Textos app |")
        w("|---------|-------|----------|------------|-------|--------|------------|")
        for r in sorted(reit["found_list"] + reit["missing_list"], key=lambda x: x["nome"]):
            tipos = {h[0] for h in r["hits"]}
            sg = "✓" if tipos == {"GERAL"} else ""
            si = "✓" if tipos == {"INTERNO"} else ""
            sb = "✓" if tipos == {"GERAL", "INTERNO"} else ""
            sn = "✓" if not tipos else ""
            if tipos == {"GERAL"}:
                only_g += 1
            elif tipos == {"INTERNO"}:
                only_i += 1
            elif tipos == {"GERAL", "INTERNO"}:
                both += 1
            else:
                none += 1
            w(
                f"| {r['nome'][:48]} | {r['sigla'] or '—'} | {sg} | {si} | {sb} | {sn} | {r['ncomp']} |"
            )
        w("")
        w(
            f"**Contagem:** só Geral={only_g}, só Interno={only_i}, ambos={both}, "
            f"nenhum PDF={none}. Competências cadastradas na Reitoria: **{reit['comps']}**."
        )
        w("")
        w("### Leitura preliminar (Reitoria)")
        w("")
        w("- Unidades **colegiadas / controle** (CONSUP, CODIR, Auditoria, Ouvidoria,")
        w("  Corregedoria, Procuradoria) tendem a aparecer com mais força no **Regimento Geral**.")
        w("- Unidades **operacionais da Reitoria** (Gabinete, pró-reitorias e subunidades)")
        w("  tendem a ter o detalhamento “Compete a…” no **Regimento Interno (845/2021)**.")
        w("- Caixas **novas ou em implantação** (ex.: Diretorias de Implantação de campi,")
        w("  CEXP) podem **não** constar de nenhum dos dois PDFs vigentes — esperado se o")
        w("  regimento ainda não acompanhou a Res. 51/2026 / SIORG.")
        w("- Hoje a Reitoria está **sem textos importados** no app; o batimento é só de")
        w("  **nomenclatura estrutura × documento**, não de conteúdo de competência.")
        w("")

    # Campi com textos: amostra de aderência
    w("## 3. Campi que já têm textos no app")
    w("")
    w("Todos os textos existentes estão ligados a regimento tipo **INTERNO**.")
    w("Amostra: fração de competências cujo trecho inicial (~60 caracteres) aparece no PDF.")
    w("")
    w("| Campus | Competências | Amostra testada | Trecho achado no PDF | Não achado |")
    w("|--------|--------------|-----------------|----------------------|------------|")
    for s in summary_rows:
        if s["comps"] == 0:
            continue
        campus = Campus.objects.get(sigla=s["sigla"])
        org = Organograma.objects.get(campus=campus, status="OFICIAL")
        ntext = ""
        for tipo, info in s["reg_texts"].items():
            if tipo == "INTERNO" or (not ntext and info["ntext"]):
                ntext = info["ntext"]
        comps = list(
            CompetenciaUnidade.objects.filter(unidade__organograma=org).order_by("id")[:40]
        )
        hit = miss = 0
        for c in comps:
            sn = norm((c.texto or "")[:60])
            if len(sn) < 25:
                continue
            if sn in ntext:
                hit += 1
            else:
                miss += 1
        tested = hit + miss
        w(
            f"| {s['sigla']} | {s['comps']} | {tested} | {hit} | {miss} |"
        )
    w("")
    w("Trechos “não achados” podem ser normalização/OCR, edição humana no app, ou PDF")
    w("diferente da versão usada na digitação original — exige revisão pontual, não")
    w("apagar em massa.")
    w("")

    # Campi sem textos
    w("## 4. Campi sem textos: viabilidade futura de importação")
    w("")
    w("| Campus | Menção de unidades no PDF | Leitura |")
    w("|--------|---------------------------|---------|")
    for s in summary_rows:
        if s["comps"] > 0:
            continue
        if s["sigla"] == "IFMG":
            leitura = (
                "Caso especial: importar de **dois** PDFs (Geral + Interno), "
                "mapeando unidade → fonte; aceitar gaps por regimento desatualizado"
            )
        elif s["pct"] >= 50:
            leitura = "PDF cita boa parte da estrutura — **candidato** a extração do Interno quando estabilizar"
        elif s["pct"] >= 25:
            leitura = "Alinhamento parcial — importar só unidades citadas; gaps esperados"
        else:
            leitura = (
                "Pouca sobreposição estrutura×PDF — **aguardar** atualização do regimento "
                "antes de importar textos"
            )
        w(f"| {s['sigla']} | {s['found']}/{s['units']} ({s['pct']:.0f}%) | {leitura} |")
    w("")

    w("## 5. Listas de unidades sem menção no PDF (por campus)")
    w("")
    w("Interpretação sugerida: **candidato a unidade criada/alterada após o regimento**,")
    w("ou nomenclatura diferente (ex.: SIORG × regimento).")
    w("")
    for s in summary_rows:
        if not s["missing_list"]:
            continue
        w(f"### {s['sigla']}")
        w("")
        for m in s["missing_list"]:
            extra = " _(já tem texto no app)_" if m["ncomp"] else ""
            w(f"- `{m['sigla'] or '—'}` {m['nome']}{extra}")
        w("")

    w("## 6. Conclusões e recomendações (sem executar)")
    w("")
    w("1. **Não alterar dados agora** até revisão humana deste batimento.")
    w("2. **Reitoria:** qualquer carga de atribuições deve distinguir **Regimento Geral** vs")
    w("   **Regimento Interno** e gravar `CompetenciaUnidade.regimento` corretamente;")
    w("   unidades novas (implantação, expansão, etc.) podem ficar sem texto até o")
    w("   regimento acompanhar a estrutura.")
    w("3. **Campi com textos (CBT, CCO, CFO, CGV, CIB, CSA, CSJ, POLO):** manter; fazer")
    w("   auditoria pontual dos trechos que não batem com o PDF.")
    w("4. **Campi sem textos e com boa menção no PDF:** candidatos a importação futura")
    w("   **somente do Interno**, unidade a unidade.")
    w("5. **Campi com baixa menção:** priorizar atualização documental institucional")
    w("   antes de popular competências no sistema.")
    w("6. O batimento por **nome** é aproximado (PDF/OCR/sinônimos); gaps devem ser")
    w("   confirmados abrindo o PDF oficial.")
    w("")
    w("---")
    w("*Gerado por `scripts/estudo_batimento_regimentos.py` (somente leitura).*")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Campi analisados: {len(summary_rows)}")


if __name__ == "__main__":
    main()
