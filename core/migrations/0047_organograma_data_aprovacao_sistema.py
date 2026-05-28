import re
from datetime import datetime, time

from django.db import migrations, models
from django.utils import timezone


DATE_PATTERNS = [
    re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})'),
    re.compile(r'(\d{1,2})[-_](\d{1,2})[-_](\d{4})'),
]


def _aware_start_of_day(value):
    dt = datetime.combine(value, time.min)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _date_from_text(*values):
    for value in values:
        if not value:
            continue
        for pattern in DATE_PATTERNS:
            match = pattern.search(str(value))
            if not match:
                continue
            day, month, year = [int(part) for part in match.groups()]
            try:
                return _aware_start_of_day(datetime(year, month, day).date())
            except ValueError:
                continue
    return None


def backfill_data_aprovacao_sistema(apps, schema_editor):
    Organograma = apps.get_model('core', 'Organograma')
    SolicitacaoAlteracao = apps.get_model('core', 'SolicitacaoAlteracao')

    for organograma in Organograma.objects.select_related('resolucao_estrutura').filter(
        status__in=['OFICIAL', 'HISTORICO'],
        data_aprovacao_sistema__isnull=True,
    ):
        solicitacao = (
            SolicitacaoAlteracao.objects
            .filter(organograma_proposto_id=organograma.id, status='APROVADO')
            .order_by('-data_atualizacao', '-id')
            .first()
        )
        if solicitacao:
            data_aprovacao = solicitacao.data_atualizacao
        elif organograma.data_vigencia:
            data_aprovacao = _aware_start_of_day(organograma.data_vigencia)
        elif organograma.resolucao_estrutura_id and organograma.resolucao_estrutura.data_publicacao:
            data_aprovacao = _aware_start_of_day(organograma.resolucao_estrutura.data_publicacao)
        else:
            resolucao = organograma.resolucao_estrutura
            data_aprovacao = _date_from_text(
                organograma.nome_documento_aprovacao,
                resolucao.numero if resolucao else '',
                resolucao.nome if resolucao else '',
            )

        if data_aprovacao:
            Organograma.objects.filter(pk=organograma.pk).update(data_aprovacao_sistema=data_aprovacao)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0046_backfill_regimento_geral_referencia'),
    ]

    operations = [
        migrations.AddField(
            model_name='organograma',
            name='data_aprovacao_sistema',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Data de Aprovação no Sistema'),
        ),
        migrations.RunPython(backfill_data_aprovacao_sistema, migrations.RunPython.noop),
    ]
