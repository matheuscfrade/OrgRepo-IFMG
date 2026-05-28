from django.db import migrations


def _file_name(file_field):
    name = getattr(file_field, "name", "") or ""
    return name.strip()


def backfill_resolucoes_e_regimento_geral(apps, schema_editor):
    Organograma = apps.get_model("core", "Organograma")
    RegimentoCampus = apps.get_model("core", "RegimentoCampus")
    ResolucaoEstruturaOrganizacional = apps.get_model("core", "ResolucaoEstruturaOrganizacional")

    for organograma in Organograma.objects.select_related("campus").filter(resolucao_estrutura__isnull=True).order_by("campus_id", "-data_vigencia", "-id"):
        nome = (organograma.nome_documento_aprovacao or "").strip()
        arquivo = _file_name(organograma.documento_aprovacao)
        if not nome and not arquivo:
            continue

        resolucao = None
        if arquivo:
            resolucao = ResolucaoEstruturaOrganizacional.objects.filter(
                campus_id=organograma.campus_id,
                arquivo=arquivo,
            ).order_by("-id").first()
        if not resolucao and nome:
            resolucao = ResolucaoEstruturaOrganizacional.objects.filter(
                campus_id=organograma.campus_id,
                nome=nome,
            ).order_by("-id").first()
        if not resolucao:
            resolucao = ResolucaoEstruturaOrganizacional.objects.create(
                campus_id=organograma.campus_id,
                nome=nome or "Resolução da Estrutura Organizacional",
                numero=nome,
                arquivo=arquivo or None,
                observacoes="Criada automaticamente a partir dos metadados legados do organograma.",
            )

        organograma.resolucao_estrutura_id = resolucao.id
        organograma.save(update_fields=["resolucao_estrutura"])

    for organograma in Organograma.objects.select_related("campus").filter(campus__sigla="IFMG").order_by("-data_vigencia", "-id"):
        nome = (organograma.nome_regimento_geral or "").strip()
        arquivo = _file_name(organograma.regimento_geral_arquivo)
        if not nome and not arquivo:
            continue

        regimento = None
        if arquivo:
            regimento = RegimentoCampus.objects.filter(
                campus_id=organograma.campus_id,
                tipo="GERAL",
                arquivo=arquivo,
            ).order_by("-vigente", "-id").first()
        if not regimento and nome:
            regimento = RegimentoCampus.objects.filter(
                campus_id=organograma.campus_id,
                tipo="GERAL",
                nome=nome,
            ).order_by("-vigente", "-id").first()
        if not regimento:
            has_vigente = RegimentoCampus.objects.filter(
                campus_id=organograma.campus_id,
                tipo="GERAL",
                vigente=True,
            ).exists()
            regimento = RegimentoCampus.objects.create(
                campus_id=organograma.campus_id,
                tipo="GERAL",
                nome=nome or "Regimento Geral",
                arquivo=arquivo or None,
                vigente=not has_vigente,
                observacoes="Criado automaticamente a partir dos metadados legados do organograma da Reitoria.",
            )
        if regimento.vigente:
            break


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0043_resolucaoestruturaorganizacional_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_resolucoes_e_regimento_geral, noop_reverse),
    ]
