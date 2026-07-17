# Deploy Docker + PostgreSQL

Guia para a TI subir o **OrgRepo** no servidor com **Docker Compose** (aplicação + PostgreSQL).

O repositório já inclui o código, o snapshot de dados (`data/full_data.json`) e os PDFs (`data/media/`).

## O que sobe

| Serviço | Função |
|---------|--------|
| `db` | PostgreSQL 16 (volume `postgres_data`) |
| `web` | Django + Gunicorn (volume `media_data` para PDFs) |

- Arquivos estáticos: WhiteNoise (`collectstatic` automático no start)
- PDFs: volume Docker; com `SERVE_MEDIA=True` a app serve `/media/` (incluindo com `DEBUG=False`). Alternativa: proxy institucional em `/media/` e `SERVE_MEDIA=False`
- Snapshot: organogramas e documentos oficiais; **competências de unidades vêm vazias** neste release (importação posterior se necessário)
- Contas: o snapshot **não** inclui usuários; criar admin com `createsuperuser`

## Pré-requisitos

- Docker Engine + plugin Docker Compose
- Porta `8000` liberada (ou outra via `WEB_PORT`)
- PostgreSQL **não** precisa ser exposto na rede do host

## 1. Clonar e configurar

```bash
git clone https://github.com/matheuscfrade/OrgRepo-IFMG.git
cd OrgRepo-IFMG
cp .env.example .env
```

Edite o `.env` (obrigatório):

| Variável | Notas |
|----------|--------|
| `SECRET_KEY` | String longa e aleatória |
| `POSTGRES_PASSWORD` | Senha forte do banco |
| `ALLOWED_HOSTS` | Domínio ou IP do servidor (ex.: `orgrepo.ifmg.edu.br,10.0.0.10`) |

Recomendado em produção:

| Variável | Notas |
|----------|--------|
| `CSRF_TRUSTED_ORIGINS` | Se houver HTTPS, ex.: `https://orgrepo.ifmg.edu.br` |
| `SERVE_MEDIA` | `True` se a app servir os PDFs |
| `RUN_BOOTSTRAP` | Só na **primeira** carga (ver abaixo); depois deixar vazio |

Gerar um `SECRET_KEY` (com Python no host ou em qualquer ambiente com Django):

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## 2. Subir a stack

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f web
```

No start, o container `web` já executa `migrate` e `collectstatic`.

## 3. Primeira carga de dados (uma vez só)

Escolha **uma** das formas abaixo. Não deixe bootstrap ativo de forma permanente.

### Opção A — Comandos manuais (recomendada)

```bash
docker compose exec web python manage.py load_full_data
docker compose exec web python manage.py load_consup44_modelos
docker compose exec web python manage.py sync_cargo_quotas
docker compose exec web python manage.py createsuperuser
```

### Opção B — Variável no `.env`

1. Defina `RUN_BOOTSTRAP=full` no `.env`
2. `docker compose up -d --build`
3. Aguarde o start concluir com sucesso
4. **Remova** `RUN_BOOTSTRAP` (ou deixe vazio) e rode `docker compose up -d` de novo
5. Crie o superusuário:

```bash
docker compose exec web python manage.py createsuperuser
```

> **Importante:** não deixe `RUN_BOOTSTRAP=full` permanente. Cada restart reexecuta import/sync (a maioria das linhas existentes é ignorada, arquivos de mídia são reescritos e os modelos referenciais são reconstruídos). Não é operação de produção idempotente.

Smoke test após a carga:

```bash
# App responde
curl -fsS "http://SERVIDOR:8000/" >/dev/null && echo OK

# PDF (exemplo — ajuste o caminho se necessário)
# curl -fsSI "http://SERVIDOR:8000/media/regimentos_campus/..." | head -n1
```

## 4. Acessar

- Aplicação: `http://SERVIDOR:8000/`
- Admin: `http://SERVIDOR:8000/admin/` (após `createsuperuser`)

## 5. Atualização de versão (sem recarregar dados)

```bash
git pull
# Confirme que RUN_BOOTSTRAP está vazio no .env
docker compose up -d --build
docker compose logs -f web
```

## Operação

| Ação | Comando |
|------|---------|
| Logs | `docker compose logs -f web` |
| Reiniciar app | `docker compose restart web` |
| Shell Django | `docker compose exec web python manage.py shell` |

## Backup

Volumes:

- `postgres_data` — banco de dados
- `media_data` — PDFs e uploads

Postgres:

```bash
docker compose exec -T db pg_dump -U orgrepo orgrepo > backup_orgrepo_$(date +%Y%m%d).sql
```

Mídia:

```bash
docker compose exec web tar -C /app/var/media -czf - . > media_backup.tgz
```

## HTTPS / proxy

Recomendado: Nginx ou Traefik na frente, com certificado institucional.

Exemplo de variáveis com proxy que termina TLS:

```env
SECURE_SSL_REDIRECT=False
USE_X_FORWARDED_PROTO=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
CSRF_TRUSTED_ORIGINS=https://seu-dominio.ifmg.edu.br
ALLOWED_HOSTS=seu-dominio.ifmg.edu.br
```

Se a TI servir PDFs pelo proxy, monte o volume de mídia no proxy e use `SERVE_MEDIA=False`.

## Problemas comuns

| Sintoma | O que verificar |
|---------|-----------------|
| `SECRET_KEY is missing` | Preencher `SECRET_KEY` no `.env` |
| `ALLOWED_HOSTS is empty` | Preencher `ALLOWED_HOSTS` |
| CSS quebrado | Logs do start (`collectstatic`) |
| PDF 404 | Rodar `load_full_data` (com mídia); `SERVE_MEDIA=True`; volume `media_data` montado |
| Erro de CSRF no login | `CSRF_TRUSTED_ORIGINS` com a URL HTTPS completa |
| Dados somem após restart | `RUN_BOOTSTRAP=full` ainda ativo no `.env` |

## Checklist rápido

1. Clonar o repositório  
2. Criar `.env` a partir de `.env.example`  
3. `docker compose up -d --build`  
4. Carregar dados **uma vez** (`load_full_data` + demais comandos, ou `RUN_BOOTSTRAP=full`)  
5. `createsuperuser`  
6. Remover bootstrap; configurar HTTPS/proxy; agendar backup dos volumes  
