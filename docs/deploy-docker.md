# Deploy Docker + PostgreSQL (Produção / TI institucional)

Este guia descreve como subir o **OrgRepo** no servidor com **Docker Compose** (app + PostgreSQL).

O repositório já inclui o snapshot `data/full_data.json` e os PDFs em `data/media/`. Na **primeira** subida, carregue esses dados uma única vez; nas atualizações de código, **não** recarregue o snapshot se o banco de produção já estiver em uso.

## Fluxo recomendado

```
1. Clonar o repositório no servidor
2. Configurar .env (secrets, hosts)
3. docker compose up -d --build
4. Bootstrap ONE-SHOT dos dados (só na primeira carga)
5. Criar superusuário
6. Remover flag de bootstrap e operar normalmente (backups dos volumes)
```

---

## Arquitetura

| Serviço | Imagem / papel |
|---------|----------------|
| `db` | PostgreSQL 16 (volume `postgres_data`) |
| `web` | Django + Gunicorn + WhiteNoise (volume `media_data` → `/app/var/media`) |

- **Static:** WhiteNoise (`collectstatic` no entrypoint)
- **Media (PDFs):** volume Docker + `SERVE_MEDIA=True` (ou proxy da TI em `/media/`)

---

## Pré-requisitos no servidor

- Docker Engine + Docker Compose plugin
- Portas: `8000` (ou a definida em `WEB_PORT`) para a app; Postgres **não** precisa ser exposto ao host
- Arquivo `.env` com secrets (nunca commitado)

---

## Configuração (`.env`)

```bash
cp .env.example .env
# editar SECRET_KEY, POSTGRES_PASSWORD, ALLOWED_HOSTS, etc.
```

| Variável | Obrigatória | Notas |
|----------|-------------|--------|
| `SECRET_KEY` | sim | Aleatória e longa |
| `POSTGRES_PASSWORD` | sim | Forte |
| `ALLOWED_HOSTS` | sim | Domínio/IP do servidor |
| `CSRF_TRUSTED_ORIGINS` | se HTTPS | Ex.: `https://orgrepo.ifmg.edu.br` |
| `SECURE_SSL_REDIRECT` | recomendado | `True` só se TLS chegar na app; se o proxy termina TLS e fala HTTP com o container, use `False` e confie em `USE_X_FORWARDED_PROTO` |
| `RUN_BOOTSTRAP` | só 1ª carga | `full` ou `foundation`; **depois esvaziar** |
| `SERVE_MEDIA` | sim (go-live) | `True` se a app servir PDFs |

Gerar secret:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## Subir a stack

### 1) Build e start (sem dados ainda, se preferir)

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f web
```

### 2) Primeira carga com dados completos (ONE-SHOT)

**Somente depois** do dump atualizado estar no repositório/imagem:

```bash
# No .env, uma única vez:
# RUN_BOOTSTRAP=full

docker compose up -d --build

# Quando terminar com sucesso:
# 1) Remova ou esvazie RUN_BOOTSTRAP no .env
# 2) docker compose up -d
```

Ou execute o bootstrap manualmente (mais seguro para a TI):

```bash
docker compose up -d --build
docker compose exec web python manage.py load_full_data
docker compose exec web python manage.py load_consup44_modelos
docker compose exec web python manage.py sync_cargo_quotas
docker compose exec web python manage.py createsuperuser
```

Ordem recomendada do bootstrap completo:

1. `migrate` (já no entrypoint)
2. `load_full_data`
3. `load_consup44_modelos`
4. `sync_cargo_quotas`
5. `createsuperuser`

### 3) Superusuário

```bash
docker compose exec web python manage.py createsuperuser
```

### 4) Acesse

- App: `http://SERVIDOR:8000/`
- Admin: `http://SERVIDOR:8000/admin/`

---

## Operação no dia a dia

| Ação | Comando |
|------|---------|
| Logs | `docker compose logs -f web` |
| Restart | `docker compose restart web` |
| Migrate após update de código | rebuild + start (entrypoint roda `migrate`) |
| Shell Django | `docker compose exec web python manage.py shell` |

**Atualização de versão (sem re-seed):**

1. `git pull` (ou novo artefato)
2. Confirmar que `RUN_BOOTSTRAP` está **vazio**
3. `docker compose up -d --build`
4. Verificar logs e smoke test

**Nunca** deixe `RUN_BOOTSTRAP=full` permanente — isso recarrega o snapshot a cada start e pode sobrescrever dados operacionais.

---

## Backup

Volumes Docker:

- `postgres_data` — banco
- `media_data` — PDFs

Exemplo de backup Postgres:

```bash
docker compose exec -T db pg_dump -U orgrepo orgrepo > backup_orgrepo_$(date +%Y%m%d).sql
```

Media: copiar o volume ou `docker compose exec web tar -C /app/var/media -czf - . > media_backup.tgz`

---

## HTTPS / proxy institucional

Preferível: TI coloca Nginx/Traefik na frente com certificado.

Sugestão de env atrás de proxy TLS:

```env
SECURE_SSL_REDIRECT=False
USE_X_FORWARDED_PROTO=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
CSRF_TRUSTED_ORIGINS=https://seu-dominio.ifmg.edu.br
ALLOWED_HOSTS=seu-dominio.ifmg.edu.br
```

Se a TI preferir servir PDFs no proxy, monte o volume de media no proxy e defina `SERVE_MEDIA=False`.

---

## Troubleshooting

| Sintoma | Causa provável |
|---------|----------------|
| App não sobe: `SECRET_KEY is missing` | `.env` sem `SECRET_KEY` |
| App não sobe: `ALLOWED_HOSTS is empty` | preencher hosts |
| CSS quebrado | falha no `collectstatic` (ver logs do entrypoint) |
| PDF 404 | volume media vazio ou `SERVE_MEDIA=False` sem proxy; ou bootstrap sem `load_full_data` |
| Login CSRF falha | `CSRF_TRUSTED_ORIGINS` sem o origin HTTPS |
| Dados “antigos” em produção | dump não foi regenerado após edições em dev |
| Dados sumiram após restart | `RUN_BOOTSTRAP=full` ainda ativo ou volume não montado |

---

## Resumo para a TI

1. Receber repo **depois** do time de negócio regenerar `data/full_data.json` + `data/media/`.
2. Criar `.env` a partir de `.env.example`.
3. `docker compose up -d --build`.
4. Bootstrap one-shot (`RUN_BOOTSTRAP=full` **ou** comandos manuais acima).
5. `createsuperuser`.
6. Remover bootstrap; configurar proxy/HTTPS; agendar backup dos volumes.
