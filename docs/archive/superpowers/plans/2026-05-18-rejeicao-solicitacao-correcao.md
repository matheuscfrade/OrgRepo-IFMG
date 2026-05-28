# Rejeicao de Solicitacao com Correcao Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o avaliador rejeite definitivamente ou devolva uma solicitacao para correcao, sempre com justificativa obrigatoria.

**Architecture:** A propria `SolicitacaoAlteracao` guarda o parecer do avaliador e diferencia rejeicao definitiva de devolucao por status. As views validam a justificativa no POST e os templates enviam a acao desejada com campo de parecer.

**Tech Stack:** Django models, migrations, class-based test runner via `manage.py test`, templates Django.

---

### Task 1: Modelo e Comportamento

**Files:**
- Modify: `core/models.py`
- Create: `core/migrations/0049_solicitacao_rejeicao_correcao.py`
- Test: `core/tests.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert an evaluator cannot reject without `justificativa_avaliador`, can reject definitively with status `REJEITADO`, can return for correction with status `DEVOLVIDO_CORRECAO`, and only returned requests can be resubmitted.

- [ ] **Step 2: Run tests to verify failure**

Run: `python manage.py test core.tests.CompetenciasUnidadeTests`
Expected: failure because `justificativa_avaliador` and `DEVOLVIDO_CORRECAO` are not implemented.

- [ ] **Step 3: Implement model fields**

Add `('DEVOLVIDO_CORRECAO', 'Devolvido para Correcao')` to `STATUS_CHOICES` and `justificativa_avaliador = models.TextField("Justificativa do Avaliador", blank=True, default="")`.

- [ ] **Step 4: Create migration**

Run: `python manage.py makemigrations core`
Expected: migration adding the field and altering choices.

### Task 2: Views and Templates

**Files:**
- Modify: `core/views.py`
- Modify: `core/templates/core/solicitacao_detail.html`
- Modify: `core/templates/core/solicitacao_list.html`
- Modify: `core/templates/core/organograma_detail.html`

- [ ] **Step 1: Update reject view**

Read `justificativa_avaliador` and `acao_rejeicao` from POST. If justification is blank, add an error and keep the status unchanged. Use `REJEITADO` for definitive rejection and `DEVOLVIDO_CORRECAO` for correction return.

- [ ] **Step 2: Update resubmit view**

Permit resubmission only from `DEVOLVIDO_CORRECAO`.

- [ ] **Step 3: Update edit lock**

Allow proposal metadata changes while status is `EM_ANALISE` or `DEVOLVIDO_CORRECAO`.

- [ ] **Step 4: Update templates**

Show evaluator justification when present. Add required textarea and two reject buttons in admin actions. Show the resubmit button only for `DEVOLVIDO_CORRECAO`.

### Task 3: Verification

**Files:**
- Test: `core/tests.py`

- [ ] **Step 1: Run targeted tests**

Run: `python manage.py test core.tests.CompetenciasUnidadeTests`
Expected: all tests pass.

- [ ] **Step 2: Run full test suite**

Run: `python manage.py test core`
Expected: all tests pass.
