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

Este repositório está configurado para conter **a fundação normativa** da Resolução CONSUP 44/2025:

- Dimensionamentos
- Cargos e Funções
- Tipos de Unidade
- Os 6 Modelos Referenciais oficiais + suas 137 caixas (UnitModelos)
- Regras de Alteração (RegrasAlteracaoModelo) e cotas

Além disso, o repositório inclui opcionalmente o snapshot `data/full_data.json` + PDFs em `data/media/` para quem quiser um ambiente de demonstração com organogramas reais.

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
> - `data/full_data.json` é um snapshot de desenvolvimento e **pode não refletir a situação atual do IFMG**.
> - PDFs só abrem se `MEDIA_ROOT` apontar para `var/media` (já configurado em `config/settings`) e se `load_full_data` tiver copiado os arquivos.
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

## Fluxo de Desenvolvimento Recomendado (Para Forks e Contribuidores)

- O **estado padrão** após clonar é a **fundação limpa** (Opção A).
- Para demo com organogramas reais, use a **Opção B** na ordem documentada (`load_full_data` → `load_consup44_modelos`).
- Siga o estilo de código existente.
- Atualize a documentação quando necessário.
- Abra Pull Requests para contribuir.

Obrigado por contribuir!

## Arquitetura Técnica

- **Backend**: Django 6
- **Banco de dados**: SQLite (desenvolvimento) / PostgreSQL (produção recomendado)
- **Frontend**: Templates Django + JavaScript (D3.js no construtor de organogramas)
- **Mídia**: `MEDIA_ROOT = var/media/` (regimentos, resoluções e documentos de aprovação)

## Preparação para Produção (Docker + PostgreSQL)

Guia completo: **[docs/deploy-docker.md](docs/deploy-docker.md)**

### Ordem importante

1. **Atualizar organogramas e documentos no ambiente de desenvolvimento** (ainda não “fechar” o dump).
2. Gerar snapshot fresco: `dump_full_data` + PDFs em `data/media/`.
3. Subir stack Docker (app + PostgreSQL).
4. Bootstrap **one-shot** dos dados (`RUN_BOOTSTRAP=full` ou comandos manuais).
5. Remover a flag de bootstrap e operar com backups dos volumes.

Não use o `full_data.json` antigo se ainda houver mudanças pendentes nos organogramas.

### Subir localmente a stack de produção (smoke test)

```bash
cp .env.example .env
# Edite SECRET_KEY e POSTGRES_PASSWORD

docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

A aplicação fica em http://localhost:8000

O Compose sobe:
- PostgreSQL 16 (volume `postgres_data`)
- Django/Gunicorn (volume `media_data` para PDFs)
- `migrate` + `collectstatic` no entrypoint
- Bootstrap de dados **somente** se `RUN_BOOTSTRAP` estiver definido

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
