# Guia de Configuração - OrgRepo

## 1. Clonagem e Ambiente

```bash
git clone <url-do-repositorio>
cd OrgRepo

python -m venv .venv
.\.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## 2. Banco de Dados

### Opção A - SQLite (Desenvolvimento Rápido)

```bash
python manage.py migrate
python manage.py load_consup44_modelos
python manage.py createsuperuser
python manage.py runserver
```

### Opção B - PostgreSQL (Recomendado para Produção)

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

## 3. Carregando a Fundação

O comando principal é:

```bash
python manage.py load_consup44_modelos
```

Ele cria:
- Dimensionamentos
- Cargos e Funções
- Tipos de Unidade
- Os 6 Modelos Referenciais oficiais da Resolução CONSUP 44/2025
- Regras de Alteração

## 4. Comandos de Manutenção

### Limpar tudo e voltar apenas para a fundação 44

```bash
python manage.py purge_instance_data --github-minimal --force
python manage.py load_consup44_modelos
```

Útil quando você quer recomeçar do zero mantendo apenas as regras oficiais.

## 5. Estrutura de Pastas Importante

- `var/db.sqlite3` → Banco principal
- `var/manual_test/db.sqlite3` → Banco de testes manuais (sandbox)
- `var/media/` → Arquivos enviados (regimentos, resoluções)

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

## Dicas

- Use o ambiente de teste manual (`scripts/run_manual_test_server.ps1`) para fazer alterações destrutivas sem afetar o banco principal.
- O sistema foi projetado para que a **fundação normativa** (Resolução 44) seja separada dos dados reais dos campi.