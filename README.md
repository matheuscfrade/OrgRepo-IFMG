# OrgRepo - Repositório de Organogramas do IFMG

> **⚠️ Protótipo em desenvolvimento**  
> Este repositório está em estado de protótipo. O objetivo é permitir que a equipe de TI do IFMG faça fork e continue o desenvolvimento, especialmente integrando o sistema de autenticação e logging institucional.

Sistema para gerenciamento de estruturas organizacionais (organogramas), modelos referenciais, solicitações de alteração e governança conforme a Resolução CONSUP nº 44/2025.

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

Este comando cria toda a estrutura normativa da Resolução CONSUP 44/2025.

### 3. Crie um Superusuário

```bash
python manage.py createsuperuser
```

Acesse o admin em `/admin/` para começar a cadastrar Campi, Regimentos, Resoluções e Organogramas.

## Comandos Úteis

| Comando | Descrição |
|---------|-----------|
| `python manage.py load_consup44_modelos` | Carrega/recarrega os modelos referenciais da Resolução 44 |
| `python manage.py purge_instance_data --github-minimal --force` | Remove todos os dados de campi e organogramas (deixa apenas a fundação 44) |

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