# Stage 1 — Milestone 6b Report: Document viewer — edit mode

**Status:** Complete (manual QA done; see §7)
**Spec:** [stage1_M6b_spec.md](stage1_M6b_spec.md) · **Umbrella:** [stage1_M6_spec.md](stage1_M6_spec.md)
**Date:** 2026-06-01

---

## 1. What was built

In-viewer paragraph editing on top of the M6a read view:

- **`PATCH /api/workspace/{id}/document/paragraph/{para_id}`** — validates the paragraph, snapshots a **pre-edit checkpoint** (`before manual edit {para_id}`), applies `edit_paragraph` (tracked changes on by default, author `"Stet"`), marks the doc dirty, persists session state, and returns `{document, block, unsaved_changes}`. Does **not** write the source file (save stays explicit, M4/M5).
- **Standalone TipTap module** `static/js/doc_editor.js` — `createParagraphEditor(elementId, initialHtml, { onSave, onCancel })` with bold/italic/underline/superscript/subscript toolbar and Save/Cancel. Loaded as an ES module from `workspace.html`; no dependency on `base.html`'s card UI editor.
- **Viewer edit flow** — each paragraph block shows an **Edit** control on hover; clicking swaps the block for the editor seeded with the block's plain text; Save → PATCH → re-render that block + unsaved indicator; Cancel restores the block unchanged.
- **In-session track-change display** — `render_document` now diffs pending `RevisionStore` deletions against current `plain_text` when run markup alone cannot show an edit (the `edit_paragraph` path). Manual and agent edits therefore re-render with `<ins class="diff-insert">` / `<del class="diff-delete">` colouring after save.

## 2. Files

**Created**

- `static/js/doc_editor.js` — reusable workspace paragraph editor factory.
- `tests/test_workspace_api.py` — `TestParagraphEdit` (4 cases).
- `tests/test_document_render.py` — `TestPendingRevisionDiff` (revision-store overlay).

**Modified**

- `src/routes/workspace.py` — `ParagraphEditRequest` + `PATCH …/document/paragraph/{para_id}` + `_block_for_para_id`.
- `src/workspace/render.py` — `_render_pending_revision_diff` / `_diff_to_track_html` for in-session edits; table/paragraph paths pass `DocumentModel`.
- `templates/workspace.html` — load `doc_editor.js` (module) before `workspace.js`.
- `static/js/workspace.js` — edit affordance, open/save/cancel flow, block replacement.
- `static/css/workspace.css` — paragraph edit button + editor container/toolbar styles.
- `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md` — status/decisions.

## 3. Tests

Full suite: **702 passed, 1 skipped, 0 warnings**.

New/extended:

| Test | Asserts |
|------|---------|
| `TestParagraphEdit::test_patch_edits_paragraph` | PATCH edits, dirty flag, re-rendered block, checkpoint created, file not written |
| `TestParagraphEdit::test_patch_unknown_para_404` | Unknown `para_id` → 404 |
| `TestParagraphEdit::test_patch_then_restore` | Checkpoint restore rolls back manual edit |
| `TestParagraphEdit::test_patch_track_changes_in_block_html` | Returned block HTML contains ins/del markup |
| `TestPendingRevisionDiff::test_in_session_edit_renders_ins_del_from_revision_store` | Renderer overlays RevisionStore pending edits |

Card UI at `/` and legacy integration tests unchanged.

## 4. Deviations from spec

None material. Table cells are not given an Edit control (only `kind === "paragraph"` blocks); editing a table cell by `para_id` via the API still works if needed later.

## 5. Decisions logged

See `docs/stage1_decision_log.md` (2026-06-01 M6b entries): standalone `doc_editor.js`, pre-edit checkpoint on manual PATCH, RevisionStore diff overlay in the renderer.

## 6. Manual QA checklist (project owner)

Open `/workspace`, load a real docx from `test_data/local/` (or synthetic `test.docx`):

1. **Edit affordance** — hover a paragraph → **Edit** appears; table rows have no Edit button.
2. **Edit + save** — change text, Save → block updates, **● unsaved** appears in the header.
3. **Track changes** — after save, edited text shows green insertions / red deletions (word-level diff) when `track_changes` is on (default).
4. **Cancel** — Edit → change text → Cancel → block unchanged, no unsaved bump.
5. **File save** — header **Save** persists the edit to disk; re-open confirms.
6. **Checkpoint undo** — after a manual edit, restore the latest checkpoint (via API or a future UI) → edit gone.
7. **Agent refresh** — run a small agent edit → viewer still refreshes correctly alongside manual edits.

## 7. Manual QA outcome + follow-ups

Project-owner QA: edit mode, checkpoints, unsaved state, and track-change colouring all work. Two additional findings:

### 7.1 Table column misalignment (M6b regression — fixed)

**Symptom:** table column borders no longer line up vertically between rows (see QA screenshot).

**Cause:** M6b wrapped every block's HTML in an extra `.ws-para-content` div for the edit UI. Table CSS expects `.ws-cell` elements to be **direct** flex children of `.ws-table-row` (`display: flex` on the row). The wrapper broke that, so each row sized its columns independently.

**Fix:** only paragraph blocks use the `.ws-para-content` wrapper; table rows render cell HTML directly on the row element again (M6a DOM shape).

### 7.2 Agent edit: Unicode mangling (pre-existing — defer to M9)

**Symptom:** during agent testing (“Europe” → “EU”), special characters in the same paragraph were corrupted in the tracked-change view (e.g. `≥18` → garbled `☒68`, `≥140` → `☒6140`). Other edits in that paragraph (including “intention-to-treat” → “ITT”) were **requested earlier** by the project owner and are expected.

**Cause (not introduced by M6b):** the agent's `edit_paragraph` tool takes the **full revised paragraph text** (`new_text`). When the model re-types the paragraph, some LLMs corrupt special Unicode like `≥`. The card UI already protects these via `llm_prompts._protect_unicode` / `llm_transport.UNICODE_PROTECTION_MAP`; the **M3 agent loop has no equivalent**. The viewer correctly displays whatever text the agent wrote as red/green track changes.

**Follow-up:** port Unicode protection into the agent tool path — logged under **M9 — Integration and hardening** in the implementation plan.

## 8. Next

M7 — Agent chat panel enhancements per the implementation plan.
