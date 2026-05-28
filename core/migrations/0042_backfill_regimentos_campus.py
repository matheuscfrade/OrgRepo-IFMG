from django.db import migrations


def _file_name(file_field):
    name = getattr(file_field, "name", "") or ""
    return name.strip()


def backfill_regimentos_campus(apps, schema_editor):
    Organograma = apps.get_model("core", "Organograma")
    RegimentoCampus = apps.get_model("core", "RegimentoCampus")

    organogramas = (
        Organograma.objects.select_related("campus")
        .filter(regimento_referencia__isnull=True)
        .order_by("campus_id", "-data_vigencia", "-id")
    )

    by_campus = {}
    for organograma in organogramas:
        nome = (organograma.nome_regimento or "").strip()
        arquivo = _file_name(organograma.regimento_arquivo)
        if not nome and not arquivo:
            continue
        by_campus.setdefault(organograma.campus_id, []).append((organograma, nome, arquivo))

    for campus_id, items in by_campus.items():
        vigente_existente = RegimentoCampus.objects.filter(campus_id=campus_id, vigente=True).first()

        for index, (organograma, nome, arquivo) in enumerate(items):
            regimento = None

            if arquivo:
                regimento = RegimentoCampus.objects.filter(
                    campus_id=campus_id,
                    arquivo=arquivo,
                ).order_by("-vigente", "-id").first()

            if not regimento and nome:
                regimento = RegimentoCampus.objects.filter(
                    campus_id=campus_id,
                    nome=nome,
                ).order_by("-vigente", "-id").first()

            if not regimento:
                regimento = RegimentoCampus.objects.create(
                    campus_id=campus_id,
                    nome=nome or "Regimento Interno",
                    arquivo=arquivo or None,
                    vigente=(not vigente_existente and index == 0),
                    observacoes="Criado automaticamente a partir dos metadados legados do organograma.",
                )
                if regimento.vigente:
                    vigente_existente = regimento

            organograma.regimento_referencia_id = regimento.id
            organograma.save(update_fields=["regimento_referencia"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0041_regimentocampus_competenciaunidade_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_regimentos_campus, noop_reverse),
    ]
