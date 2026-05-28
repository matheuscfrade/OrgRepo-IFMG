import csv
import os
from io import StringIO

from django.core.exceptions import ValidationError


SUPPORTED_EXTENSIONS = {'.csv', '.txt'}
STRUCTURED_FIELDS = ('artigo', 'inciso', 'alinea', 'paragrafo', 'texto')


def parse_competencias_file(uploaded_file):
    extension = os.path.splitext(uploaded_file.name or '')[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValidationError('Envie um arquivo .csv ou .txt.')

    content = uploaded_file.read()
    text = _decode_content(content)
    if extension == '.txt':
        return _parse_txt(text)
    return _parse_csv(text)


def _decode_content(content):
    for encoding in ('utf-8-sig', 'latin-1'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError('Nao foi possivel ler a codificacao do arquivo.')


def _parse_txt(text):
    rows = [{'texto': line.strip()} for line in text.splitlines() if line.strip()]
    if not rows:
        raise ValidationError('O arquivo nao possui competencias para importar.')
    return rows


def _parse_csv(text):
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;')
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValidationError('O CSV precisa conter cabecalho com a coluna texto.')

    field_map = {_normalize_header(name): name for name in reader.fieldnames if name}
    if 'texto' not in field_map:
        raise ValidationError('O CSV precisa conter a coluna texto.')

    rows = []
    for raw_row in reader:
        row = {}
        for field in STRUCTURED_FIELDS:
            source = field_map.get(field)
            row[field] = (raw_row.get(source) or '').strip() if source else ''
        if row['texto']:
            rows.append(row)

    if not rows:
        raise ValidationError('O arquivo nao possui competencias para importar.')
    return rows


def _normalize_header(value):
    return (value or '').strip().lower()
