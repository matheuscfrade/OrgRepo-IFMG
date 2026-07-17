# Guia de Configuração - OrgRepo

## Passo a Passo Recomendado (Após Clonar)

Escolha **Opção A** (fundação limpa) **ou** **Opção B** (dados completos de demonstração).

### Pré-requisitos comuns

```bash
# 1. Clonar e entrar na pasta
git clone <url-do-repositorio>
cd OrgRepo-IFMG

# 2. Criar e ativar ambiente virtual
python -m venv .venv
.\.venv\Scripts\activate          # Windows

# 3. Instalar dependências
pip install -r requirements.txt
```

> **Windows**: se aparecer `No module named 'config.development'`, defina:
> ```powershell
> $env:DJANGO_SETTINGS_MODULE = "config.settings.development"
> ```

---

### Opção A – Fundação limpa (padrão para forks)

Sem organogramas reais de campus — apenas Resolução CONSUP 44 + campi básicos.

```bash
python manage.py migrate
python manage.py load_consup44_modelos
python manage.py createsuperuser
python manage.py runserver
```

Acesse: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)  
Admin: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

### Opção B – Dados completos (organogramas + regimentos + PDFs)

Use o snapshot incluído em `data/full_data.json` e `data/media/`.

**Ordem correta (importante):**

```bash
python manage.py migrate
python manage.py load_full_data
python manage.py load_consup44_modelos
python manage.py sync_cargo_quotas
python manage.py createsuperuser
python manage.py runserver
```

| Passo | Por quê |
|-------|---------|
| `migrate` | Cria o schema (SQLite em `var/db.sqlite3`) |
| `load_full_data` | Importa campi, organogramas, unidades, competências, regimentos e resoluções; copia PDFs para `var/media/`; sincroniza cotas CD/FG |
| `load_consup44_modelos` | Reconstrói os **Modelos Referenciais** normativos da Resolução 44 (após o dump, para não misturar PKs) |
| `sync_cargo_quotas` | Alinha cotas dos modelos/campus com os organogramas OFICIAIS (evita `CD-03: 4 / -` nos cards) |

O `load_full_data` é resiliente a FKs auto-referenciais e a PKs de cargos/tipos diferentes, mas o fluxo acima evita conflitos e é o recomendado.

#### Banco já populado / recomeçar do zero

```bash
# Windows PowerShell
Remove-Item var\db.sqlite3 -ErrorAction SilentlyContinue
# Opcional: limpar mídia local
# Remove-Item var\media -Recurse -Force -ErrorAction SilentlyContinue

python manage.py migrate
python manage.py load_full_data
python manage.py load_consup44_modelos
python manage.py sync_cargo_quotas
```

#### PDFs (resoluções e portarias)

- Arquivos do snapshot ficam em `data/media/` e são copiados para **`var/media/`** (`MEDIA_ROOT`).
- Em desenvolvimento, o Django serve `/media/...` a partir de `MEDIA_ROOT` (ver `config/urls.py` + `DEBUG=True`).
- Se um link de PDF retornar 404:
  1. Confirme que rodou `load_full_data` (sem `--no-media`)
  2. Confirme que `config.settings` define `MEDIA_ROOT = BASE_DIR / 'var' / 'media'`
  3. Confirme que o arquivo existe em `var/media/...` com o mesmo caminho relativo do banco

**Nota sobre o snapshot:** `full_data.json` foi gerado no desenvolvimento e **pode não representar a realidade atual do IFMG**. Serve como ambiente de demonstração.

---

## Banco de Dados

### Opção SQLite (Desenvolvimento Rápido)

Padrão em `config/settings/development.py` → `var/db.sqlite3`.

### Opção PostgreSQL (Recomendado para Produção)

1. Instale o PostgreSQL
2. Crie o banco:
   ```sql
   CREATE DATABASE orgrepo;
   CREATE USER orgrepo WITH PASSWORD 'sua_senha';
   ALTER ROLE orgrepo SET client_encoding TO 'utf8';
   ALTER ROLE orgrepo SET default_transaction_isolation TO 'read committed';
   ALTER ROLE orgrepo SET timezone TO 'America/Sao_Paulo';
   GRANT ALL PRIVILEGES ON DATABASE orgrepo TO orgrepo;
   ```

3. Configure as variáveis de ambiente (veja `.env.example`)

4. Rode as migrações normalmente.

---

## Comandos de Manutenção

### Fundação limpa (Resolução 44)

```bash
python manage.py load_consup44_modelos
```

### Dados completos de demonstração

```bash
python manage.py load_full_data
```

Flags úteis:

```bash
python manage.py load_full_data --only-oficial   # só organogramas OFICIAL
python manage.py load_full_data --no-media       # não copiar PDFs
python manage.py load_full_data -v 2             # detalhes de skips
```

### Gerar o seu próprio dump

**Faça isso somente depois de finalizar as edições de organogramas** (o dump é o que a produção carrega).

```bash
python manage.py dump_full_data --output data/full_data.json
# Copie também os arquivos de MEDIA_ROOT para data/media/ se for versionar
# Copy-Item var\media\* data\media\ -Recurse -Force
```

Para deploy institucional com Docker + PostgreSQL, veja [deploy-docker.md](deploy-docker.md).

### Voltar só à fundação 44

```bash
python manage.py purge_instance_data --github-minimal --force
python manage.py load_consup44_modelos
```

---

## Estrutura de Pastas Importante

| Caminho | Conteúdo |
|---------|----------|
| `var/db.sqlite3` | Banco principal (dev) |
| `var/media/` | **MEDIA_ROOT** — PDFs servidos em `/media/` |
| `data/full_data.json` | Snapshot opcional de dados completos |
| `data/media/` | PDFs do snapshot (fonte para `load_full_data`) |
| `var/manual_test/db.sqlite3` | Banco de testes manuais (sandbox) |

---

## Usando Docker

### Desenvolvimento com Docker

```bash
# Subir com hot-reload (usa SQLite por padrão)
docker-compose up --build

# Subir com PostgreSQL (mais próximo de produção)
docker-compose -f docker-compose.yml up --build
```

### Produção com Docker

1. Configure as variáveis no `.env`:
   - `SECRET_KEY`
   - `ALLOWED_HOSTS`
   - `DATABASE_URL` (ou use as variáveis individuais do Postgres)

2. Rode:
   ```bash
   docker-compose -f docker-compose.yml up -d --build
   ```

---

## Dicas

- Use o ambiente de teste manual (`scripts/run_manual_test_server.ps1`) para alterações destrutivas sem afetar o banco principal.
- A **fundação normativa** (Resolução 44) fica separada dos dados reais dos campi.
- Para demo completa, prefira **Opção B** na ordem documentada.

---

## Problemas Comuns no Windows

### `No module named 'config.development'`

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.development"

.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py load_full_data
.\.venv\Scripts\python.exe manage.py load_consup44_modelos
.\.venv\Scripts\python.exe manage.py runserver
```

### PDFs de resoluções/portarias não abrem (404)

1. `MEDIA_ROOT` deve ser `var/media` (já definido em `config/settings/base.py`).
2. Rode `python manage.py load_full_data` para copiar de `data/media/`.
3. Reinicie o `runserver` após mudar settings.
4. Teste uma URL direta, por exemplo:  
   `http://127.0.0.1:8000/media/regimentos_campus/CBA_PORTARIA_N214_DE_23_02_2023.pdf`

### Unidades/cargos “faltando” após load_full_data

Use a **Opção B** em banco limpo (`migrate` → `load_full_data` → `load_consup44_modelos` → `sync_cargo_quotas`).  
O loader atual faz multi-pass e remapeia cargos/tipos, mas um DB misturado com tentativas antigas pode ficar inconsistente — nesse caso, apague `var/db.sqlite3` e recarregue.

### Cards com `CD-03: 4 / -` (ou similar)

Significa uso do cargo **sem cota cadastrada** no modelo/campus. Rode:

```bash
python manage.py sync_cargo_quotas
```

Isso redefine as cotas a partir dos organogramas oficiais carregados.
