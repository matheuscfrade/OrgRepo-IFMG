# OrgRepo - Repositório de Organogramas do IFMG

Sistema para gerenciamento de estruturas organizacionais (organogramas), modelos referenciais, solicitações de alteração e governança conforme a Resolução CONSUP nº 44/2025.

**Entrega para a TI:** o repositório já inclui aplicação, stack Docker (app + PostgreSQL), snapshot de dados e PDFs. Guia de deploy: **[docs/deploy-docker.md](docs/deploy-docker.md)**.

## ⚠️ Configurações em Camadas (Importante para Windows)

Este projeto utiliza **configurações em camadas** (development / production).

Se você receber o erro `No module named 'config.development'` ao rodar comandos no Windows, execute definindo a variável de ambiente:

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.development"

# Exemplos de uso:
python manage.py migrate
python manage.py load_consup44_modelos
python manage.py runserver
```

Veja o guia completo com mais detalhes em [docs/setup.md](docs/setup.md).

## Objetivo

Este sistema foi desenvolvido para o Instituto Federal de Minas Gerais (IFMG) com o propósito de:

- Manter os **Modelos Referenciais** oficiais por tipo de campus (Resolução CONSUP 44/2025)
- Permitir a criação e gestão de organogramas reais a partir desses modelos
- Controlar alterações através de um motor de governança rigoroso (cotas de flexibilização, regras de alteração, etc.)
- Gerenciar o fluxo completo de solicitações de alteração (Rascunho → Análise → CONSUP)

## Conteúdo do repositório

- **Aplicação Django** e modelos da Resolução CONSUP 44/2025 (dimensionamentos, cargos, tipos de unidade, modelos referenciais, regras de alteração)
- **Snapshot** `data/full_data.json` + PDFs em `data/media/` (organogramas oficiais, regimentos e resoluções)
- **Deploy** com Docker Compose (web + PostgreSQL) — ver [docs/deploy-docker.md](docs/deploy-docker.md)

## Como Iniciar (Após Clonar)

### 1. Configuração Inicial

```bash
# Crie o ambiente virtual
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# Instale as dependências
pip install -r requirements.txt
```

### 2. Escolha **um** caminho de dados

Há **dois fluxos mutuamente recomendados**. Não misture na ordem errada se quiser resultado previsível.

#### Opção A – Fundação limpa (padrão para forks)

Apenas a Resolução CONSUP 44 + lista básica de campi (sem organogramas reais):

```bash
python manage.py migrate
python manage.py load_consup44_modelos
```

#### Opção B – Dados completos de demonstração (organogramas + PDFs)

Use quando quiser o ambiente populado com organogramas oficiais, regimentos e resoluções do snapshot:

```bash
python manage.py migrate
python manage.py load_full_data
python manage.py load_consup44_modelos
python manage.py sync_cargo_quotas
```

O que cada comando faz aqui:

1. `load_full_data` — importa `data/full_data.json`, copia PDFs de `data/media/` para `var/media/` (MEDIA_ROOT), realinha FKs de cargos/tipos e sincroniza cotas CD/FG dos organogramas oficiais.
2. `load_consup44_modelos` — **depois** do dump, reconstrói os Modelos Referenciais normativos da Resolução 44 (recomendado).
3. `sync_cargo_quotas` — re-sincroniza cotas após reconstruir os modelos (evita cards `CD-03: 4 / -`).

> **Importante**
> - `data/full_data.json` é o snapshot versionado no repositório (ponto no tempo).
> - PDFs só abrem se `MEDIA_ROOT` apontar para `var/media` (já configurado) e se `load_full_data` tiver copiado os arquivos.
> - Em Windows, defina `$env:DJANGO_SETTINGS_MODULE = "config.settings.development"` se necessário.

Para gerar o seu próprio dump a partir de outro banco:

```bash
python manage.py dump_full_data --output data/full_data.json
```

### 3. Crie um Superusuário

```bash
python manage.py createsuperuser
```

### 4. Rode o Servidor

```bash
python manage.py runserver
```

Acesse o sistema em: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)  
Admin: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

## Comandos Úteis

| Comando | Descrição |
|---------|-----------|
| `python manage.py load_consup44_modelos` | Carrega/atualiza a fundação (Modelos Referenciais + Campi básicos) |
| `python manage.py dump_full_data --output data/full_data.json` | Gera um dump completo dos dados |
| `python manage.py load_full_data` | Restaura dump completo (`data/full_data.json` + PDFs → `var/media/`) |
| `python manage.py purge_instance_data --github-minimal --force` | Remove dados de campi/organogramas (mantém fundação 44) |

## Arquitetura técnica

- **Backend:** Django 6
- **Banco:** SQLite (desenvolvimento local) / PostgreSQL (produção via Docker Compose)
- **Frontend:** Templates Django + JavaScript (D3.js no construtor de organogramas)
- **Mídia:** `MEDIA_ROOT = var/media/` (regimentos, resoluções e documentos de aprovação)

## Produção (Docker + PostgreSQL)

Guia completo: **[docs/deploy-docker.md](docs/deploy-docker.md)**

```bash
cp .env.example .env
# Edite SECRET_KEY e POSTGRES_PASSWORD

docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

A aplicação fica em http://localhost:8000 (ou na porta definida em `WEB_PORT`).

O Compose sobe:

- PostgreSQL 16 (volume `postgres_data`)
- Django/Gunicorn (volume `media_data` para PDFs)
- `migrate` + `collectstatic` no entrypoint
- Bootstrap de dados **somente** se `RUN_BOOTSTRAP` estiver definido (use só na primeira carga)

## Integrações futuras (TI)

Itens típicos a evoluir no ambiente institucional:

- Autenticação institucional (SSO, LDAP, etc.)
- Logging no padrão IFMG
- Proxy HTTPS / domínio corporativo
- Política de backup dos volumes Docker

## Licença

Uso interno do IFMG.
