# Guia de Configuração - OrgRepo

## Passo a Passo Recomendado (Após Clonar)

Este é o fluxo mais simples para começar a usar o sistema com a fundação limpa:

```bash
# 1. Clonar e entrar na pasta
git clone <url-do-repositorio>
cd OrgRepo-IFMG

# 2. Criar e ativar ambiente virtual
python -m venv .venv
.\.venv\Scripts\activate          # Windows

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Preparar o banco de dados
python manage.py migrate

# 5. Carregar a fundação (Resolução 44 + Campi básicos)
python manage.py load_consup44_modelos

# 6. Criar usuário administrador
python manage.py createsuperuser

# 7. Rodar o servidor
python manage.py runserver
```

Acesse o admin em: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

## 2. Banco de Dados

### Opção A - SQLite (Desenvolvimento Rápido)

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

## 3. Carregando a Fundação (Padrão após clonar)

O comando principal é:

```bash
python manage.py load_consup44_modelos
```

Esse comando agora carrega:
- Dimensionamentos, Cargos e Tipos de Unidade
- Os 6 Modelos Referenciais oficiais da Resolução CONSUP 44/2025
- Regras de Alteração
- **Lista básica de Campi** (incluindo Reitoria e principais campi do IFMG)

Este é o estado recomendado para forks.

## 4. Carregando Dados Completos (Estado com Dados Reais)

Se você quiser restaurar um estado mais completo (com organogramas reais, regimentos, resoluções, etc.), é possível carregar um dump de dados completo.

### Como gerar o arquivo de dados completo

Em um ambiente que já possua dados reais (por exemplo, a partir de um backup antigo), rode:

```bash
python manage.py dump_full_data --output full_data.json
```

### Como carregar o arquivo de dados completo

```bash
python manage.py load_full_data
```

### ⚠️ Atenção Importante

O arquivo `full_data.json` **foi gerado durante o desenvolvimento** do sistema e **pode não representar a realidade atual do IFMG**.

- Os dados de organogramas, regimentos e resoluções refletem um momento específico do projeto.
- Eles servem principalmente como **exemplo** de como um banco populado se comporta no sistema.
- Após carregar esses dados, é recomendável revisá-los e atualizá-los conforme a realidade atual da instituição.

**O comando `load_full_data` sobrescreve dados existentes.** Use com cautela e sempre a partir de um backup.

## 4. Comandos de Manutenção

### Carregar a fundação limpa (recomendado após clonar)

```bash
python manage.py load_consup44_modelos
```

### Opção B – Carregar dados completos (estado com organogramas reais)

Se quiser restaurar um estado mais completo (com organogramas reais, regimentos, resoluções, etc.) que já vem incluído no repositório, rode simplesmente:

```bash
python manage.py load_full_data
```

Isso carrega automaticamente `data/full_data.json` e copia os PDFs de `data/media/` para `var/media/`.

### Gerar o seu próprio arquivo de dados completo (avançado)

Se você tiver um banco com dados reais e quiser gerar um novo `full_data.json`:

```bash
python manage.py dump_full_data --output data/full_data.json
```

### Limpar tudo e voltar apenas para a fundação 44

```bash
python manage.py purge_instance_data --github-minimal --force
python manage.py load_consup44_modelos
```

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

## Problemas Comuns no Windows

Se você receber o erro:

```
No module named 'config.development'
```

Isso costuma acontecer por causa de como o Python carrega os módulos no Windows. Rode os comandos definindo a variável de ambiente explicitamente:

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.development"

# Exemplos:
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py load_consup44_modelos
.\.venv\Scripts\python.exe manage.py runserver
```

Faça o mesmo para qualquer outro comando do Django.