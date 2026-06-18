# OrgRepo - Repositório de Organogramas do IFMG

> **⚠️ Protótipo em desenvolvimento**  
> Este repositório está em estado de protótipo. O objetivo é permitir que a equipe de TI do IFMG faça fork e continue o desenvolvimento, especialmente integrando o sistema de autenticação e logging institucional.

Sistema para gerenciamento de estruturas organizacionais (organogramas), modelos referenciais, solicitações de alteração e governança conforme a Resolução CONSUP nº 44/2025.

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

## Estado Atual do Repositório (GitHub)

Este repositório está configurado para conter **apenas a fundação normativa** da Resolução CONSUP 44/2025:

- Dimensionamentos
- Cargos e Funções
- Tipos de Unidade
- Os 6 Modelos Referenciais oficiais + suas 137 caixas (UnitModelos)
- Regras de Alteração (RegrasAlteracaoModelo) e cotas

**Não contém** dados reais de campi, organogramas vigentes, regimentos ou resoluções.

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

### 2. Carregue a Fundação (Resolução 44)

```bash
python manage.py migrate
python manage.py load_consup44_modelos
```

> **Nota para usuários Windows**:  
> Se aparecer o erro `No module named 'config.development'`, defina a variável de ambiente antes de rodar os comandos:
> ```powershell
> $env:DJANGO_SETTINGS_MODULE = "config.settings.development"
> .\venv\Scripts\python.exe manage.py runserver
> ```
> Veja mais detalhes em [docs/setup.md](docs/setup.md).

Este comando cria toda a estrutura normativa da Resolução CONSUP 44/2025 (incluindo a lista básica de Campi).

### Opção B – Carregue Dados Completos (Opcional)

Se quiser restaurar um estado mais completo (com organogramas reais, regimentos, resoluções etc.) que já vem incluído no repositório, rode simplesmente:

```bash
python manage.py load_full_data
```

Isso carrega automaticamente o arquivo `data/full_data.json` + os PDFs de `data/media/` (copiados para `var/media/`).

**Importante**: O arquivo `data/full_data.json` foi criado durante o desenvolvimento do projeto e **pode não refletir a situação atual do IFMG**. Ele serve principalmente como exemplo de um ambiente populado.

Caso você queira gerar o seu próprio arquivo `full_data.json` a partir de outro banco:

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

Acesse o sistema em: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

## Comandos Úteis

| Comando | Descrição |
|---------|-----------|
| `python manage.py load_consup44_modelos` | Carrega a fundação (Modelos Referenciais + Campi básicos) |
| `python manage.py dump_full_data --output full_data.json` | Gera um dump completo dos dados (para backup ou compartilhamento) |
| `python manage.py load_full_data` | Restaura um dump completo de dados (data/full_data.json + PDFs) |
| `python manage.py purge_instance_data --github-minimal --force` | Remove todos os dados de campi e organogramas (deixa apenas a fundação 44) |

## Fluxo de Desenvolvimento Recomendado (Para Forks e Contribuidores)

- O **estado padrão** do projeto após clonar deve ser a **fundação limpa** (Resolução 44 + Campi básicos).
- Use `python manage.py load_consup44_modelos` para restaurar a fundação.
- Se precisar trabalhar com dados completos (organogramas reais, regimentos, etc.), use `load_full_data`.
- Siga o estilo de código existente.
- Atualize a documentação quando necessário.
- Abra Pull Requests para contribuir.

Obrigado por contribuir!

## Arquitetura Técnica

- **Backend**: Django 6
- **Banco de dados**: SQLite (desenvolvimento) / PostgreSQL (produção recomendado)
- **Frontend**: Templates Django + JavaScript (D3.js no construtor de organogramas)

## Preparação para Produção

Consulte a documentação em `docs/` para:
- Configuração em camadas (base/dev/prod)
- Migração para PostgreSQL
- Docker e deploy

### Usando Docker (Recomendado)

```bash
# Copie as variáveis de ambiente
cp .env.example .env

# Suba o ambiente com PostgreSQL
docker-compose up --build

# A aplicação estará disponível em http://localhost:8000
```

O `docker-compose.yml` inclui:
- PostgreSQL 16
- Migrações automáticas
- Carregamento automático da fundação Resolução 44

## Licença

Uso interno do IFMG.

---

**Nota**: Este repositório foi preparado para ser compartilhado de forma limpa. A fundação normativa (Resolução 44) está separada dos dados institucionais reais.

---

## Para a Equipe de TI do IFMG (Fork & Continuação)

Este protótipo foi limpo intencionalmente para facilitar o fork. O que falta / é esperado que a equipe implemente:

- Integração com o sistema de autenticação institucional (SSO, LDAP, etc.)
- Logging no formato padrão do IFMG
- Possivelmente migração para PostgreSQL em produção
- Ajustes de segurança e variáveis de ambiente para o ambiente corporativo

Sinta-se à vontade para fazer fork e evoluir o projeto a partir da fundação atual (Resolução CONSUP 44/2025).