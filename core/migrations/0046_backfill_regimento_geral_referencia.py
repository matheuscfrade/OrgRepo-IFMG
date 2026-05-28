from django.db import migrations


def _file_name(file_field):
    name = getattr(file_field, "name", "") or ""
    return name.strip()


def backfill_regimento_geral_referencia(apps, schema_editor):
    Organograma = apps.get_model("core", "Organograma")
    RegimentoCampus = apps.get_model("core", "RegimentoCampus")

    organogramas = (
        Organograma.objects.select_related("campus")
        .filter(campus__sigla="IFMG", regimento_geral_referencia__isnull=True)
        .order_by("-data_vigencia", "-id")
    )

    for organograma in organogramas:
        nome = (organograma.nome_regimento_geral or "").strip()
        arquivo = _file_name(organograma.regimento_geral_arquivo)
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
            regimento = RegimentoCampus.objects.filter(
                campus_id=organograma.campus_id,
                tipo="GERAL",
                vigente=True,
            ).order_by("-data_publicacao", "-id").first()

        if regimento:
            organograma.regimento_geral_referencia_id = regimento.id
            organograma.save(update_fields=["regimento_geral_referencia"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0045_organograma_regimento_geral_referencia"),
    ]

    operations = [
        migrations.RunPython(backfill_regimento_geral_referencia, noop_reverse),
    ]
