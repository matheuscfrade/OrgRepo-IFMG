# Organograma Exportacao Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add complete organogram export in SVG, PNG, and PDF from both the detail view and the builder.

**Architecture:** Use a shared browser-side exporter embedded through a reusable template partial. The exporter clones the rendered D3 SVG, computes the full content bounds from all visible nodes and links, resets the transform for export, and creates SVG/PNG/PDF downloads without relying on the current viewport or zoom.

**Tech Stack:** Django templates/tests, D3-rendered SVG, browser `Blob`, `canvas`, and `window.print`/print document for PDF.

---

### Task 1: Template Coverage Tests

**Files:**
- Modify: `core/tests.py`

- [ ] **Step 1: Write failing tests**

Add Django tests that render `organograma_detail` and `organograma_build`, then assert each page contains:

```python
self.assertContains(response, 'data-org-export-format="svg"')
self.assertContains(response, 'data-org-export-format="png"')
self.assertContains(response, 'data-org-export-format="pdf"')
self.assertContains(response, 'window.OrgChartExporter')
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python manage.py test core.tests.OrganogramaExportTests
```

Expected: fails because export controls and exporter script are not rendered.

### Task 2: Shared Export Partial

**Files:**
- Create: `core/templates/core/includes/organograma_export_controls.html`
- Modify: `core/templates/core/organograma_detail.html`
- Modify: `core/templates/core/organograma_builder.html`

- [ ] **Step 1: Implement partial**

Create a compact export toolbar and `window.OrgChartExporter` with:

```javascript
function getFullBounds(svg, canvasGroup) {
    const bounds = canvasGroup.getBBox();
    return {
        x: bounds.x - 40,
        y: bounds.y - 40,
        width: bounds.width + 80,
        height: bounds.height + 80
    };
}
```

The exporter must clone `#orgChartContainer svg`, set `viewBox` to the full bounds, set explicit `width` and `height`, reset `.canvas-group` transform to `translate(0,0)`, inline CSS needed by node cards, and download SVG/PNG. For PDF, open a print document containing the complete SVG scaled to one page with no overflow clipping.

- [ ] **Step 2: Include partial in both pages**

Add the toolbar near the chart action area and include the script after D3 rendering code so the controls bind after page load.

### Task 3: Verification

**Files:**
- Test: `core/tests.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
python manage.py test core.tests.OrganogramaExportTests
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python manage.py test
```

Expected: pass.
