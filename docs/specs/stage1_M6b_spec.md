# Stage 1 — Milestone 6b Spec: Document viewer — edit mode

**Status:** Approved — implemented 2026-06-01 (manual QA pending)
**Umbrella:** [M6 — Document viewer](stage1_M6_spec.md) · **Depends on:** [M6a — read fidelity](stage1_M6a_spec.md)

---

## 1. Goal

In-viewer editing on top of the M6a read view: click a paragraph → edit it in TipTap → save → the change applies to the `DocumentModel` as a tracked change, snapshots an undo checkpoint, and the block re-renders. The TipTap setup is a **standalone** reusable module (the card UI is left alone — decision 4).

---

## 2. Files to create or modify

**Create:**

| File | Purpose |
|------|---------|
| `static/js/doc_editor.js` | Reusable TipTap factory `createParagraphEditor(elementId, initialHtml, { onSave, onCancel })`, decoupled from card/session selectors. Loads/initialises TipTap for the standalone `/workspace` page. |
| `tests/` additions | API tests for the paragraph-edit endpoint (see §5). |

**Modify:**

| File | Change |
|------|--------|
| `src/routes/workspace.py` | `PATCH /document/paragraph/{para_id}` → pre-edit checkpoint + `edit_paragraph`; returns updated summary + re-rendered block. |
| `templates/workspace.html` | Load TipTap (standalone); per-paragraph edit affordance + editor container. |
| `static/js/workspace.js` | Edit affordance per block; open `doc_editor` seeded with the paragraph HTML; Save → PATCH → re-render block + refresh unsaved state; Cancel reverts. |
| `static/css/workspace.css` | Editor container + toolbar styles. |
| Glossary / decision log / status table / this spec | Report-step updates. |

---

## 3. `PATCH /document/paragraph/{para_id}`

```python
class ParagraphEditRequest(BaseModel):
    new_text: str
    track_changes: bool = True
    author: str = "Stet"   # default; a real user identity is the ideal once introduced (decision 5)
```

Handler:
1. `_require_document(session)`; resolve the paragraph (404 / `not_found` if unknown).
2. **Pre-edit checkpoint:** `session.checkpoint_store.save(session.document, label=f"before manual edit {para_id}")` — so manual edits are undoable like agent turns (decision 6).
3. `tools.edit_paragraph(session.document, para_id, new_text, track_changes, author)`.
4. Mark dirty (the edit path already does), `session.touch()` / `persist()` as appropriate; **no** implicit file write (save stays explicit, M4/M5).
5. Return `{ "document": <summary>, "block": <re-rendered Block for para_id>, "unsaved_changes": true }`.

Checkpoint pruning (FIFO at `max_checkpoints`) and the existing `/checkpoints` + `/checkpoint/restore` endpoints cover manual-edit undo with no new surface.

---

## 4. Editor module + client behavior

- **`doc_editor.js`** exposes `createParagraphEditor(elementId, initialHtml, { onSave, onCancel })`: builds a TipTap editor (bold/italic/underline/superscript/subscript — the existing capabilities), a small toolbar, and Save/Cancel. `onSave(newText)` returns the edited paragraph's plain text (revision diffing happens server-side in `edit_paragraph`). It must not reference card/session globals.
- **TipTap loading:** since `/workspace` is standalone, `workspace.html` loads TipTap (ESM via esm.sh, as `base.html` does) and `doc_editor.js` consumes it. No dependency on `base.html`'s `createTipTapEditor`.
- **Edit flow (`workspace.js`):** an "Edit" control per paragraph block swaps the block for an editor seeded with the block's HTML; Save → `PATCH …/paragraph/{para_id}` → replace the block with the returned re-rendered `block`, update the unsaved indicator; Cancel restores the block unchanged.
- **Track changes:** edits default to `track_changes=true` attributed to "Stet"; the re-rendered block therefore shows the new ins/del coloring from M6a.

---

## 5. Tests

- `tests/test_workspace_api.py`: `PATCH /document/paragraph/{id}` edits via `edit_paragraph`, marks the doc dirty, returns the re-rendered block, and creates a checkpoint (assert `/checkpoints` count increments and `/checkpoint/restore` rolls the edit back); unknown `para_id` → 404 / `not_found`; edit does not write the source file on disk (save stays explicit).
- Existing full suite stays green, **0 warnings**; card UI at `/` unaffected.
- **Manual QA:** edit a paragraph in the viewer, save → it shows as a tracked change; the unsaved indicator appears; Save (file) persists it; a checkpoint restore undoes the manual edit; Cancel discards in-editor changes.

---

## 6. Out of scope for M6b

- Selecting text to create/resolve **comments** in the viewer (manual comment authoring) — later.
- Accept/reject individual tracked changes — later.
- Refactoring the card UI onto the shared editor (decision 4 — the card UI is being retired).
- Tables-as-grid / margin balloons → Stage 3.
