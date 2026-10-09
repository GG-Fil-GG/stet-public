# Stage 1 — Milestone 6a Spec: Document viewer — read fidelity

**Status:** Approved — implementing (decisions in [umbrella §2](stage1_M6_spec.md#2-resolved-decisions-2026-06-01))
**Umbrella:** [M6 — Document viewer](stage1_M6_spec.md) · **Next:** [M6b — edit mode](stage1_M6b_spec.md)

---

## 1. Goal

A faithful **read-only** rendering of the open docx in the centre panel, plus a **side comments list**:

- Each body paragraph is its own block; soft line breaks (`<w:br/>`) render as `<br>`. (Fixes the M5 "everything on one line" finding.)
- **Track changes inline:** insertions highlighted, deletions struck through, using the card UI's `diff-insert` / `diff-delete` color language.
- **Comments:** anchored ranges highlighted in the text (incl. overlapping and cross-paragraph), with their threads listed in a right-hand column and **click-linked** both ways.
- **Tables** rendered as legible rows (not run-on text), but not a true `<table>` grid (Stage 3).
- The viewer **refreshes after an agent run** so agent edits/comments appear.

No editing in this half (that's M6b).

---

## 2. Files to create or modify

**Create:**

| File | Purpose |
|------|---------|
| `src/workspace/render.py` | `render_document(model) -> list[Block]`: pure model → ordered blocks with track-change- and comment-aware HTML. |
| `tests/test_document_render.py` | Renderer unit tests (see §5). |

**Modify:**

| File | Change |
|------|--------|
| `src/routes/workspace.py` | `GET /document` returns enriched `blocks` + a `comments` thread list (replaces the flat `paragraphs` stub). |
| `src/workspace/__init__.py` | Export the renderer. |
| `templates/workspace.html` | Document area → scroll container of blocks; add a right-hand comments column. |
| `static/js/workspace.js` | Render blocks (track changes + comment highlights); render the comments list; click-link comment ↔ anchor; point `refreshDocument()` at the enriched payload. |
| `static/css/workspace.css` | Track-change, comment-highlight, comments-list, and table-row styles (reuse `diff-insert` / `diff-delete`). |
| `tests/test_workspace_api.py` | `GET /document` returns `blocks` + `comments`. |
| `tests/test_workspace_page.py` | Comments column anchor present. |
| Glossary / decision log / status table / this spec | Report-step updates. |

---

## 3. Renderer API (`src/workspace/render.py`)

```python
@dataclass
class Block:
    kind: str                 # "paragraph" | "table_row"
    para_id: str              # paragraph id (table_row: first cell's id)
    html: str                 # track-change- and comment-aware inline HTML
    style: str | None         # style id (for headings later)
    comment_ids: list[str]    # comment ids whose anchor touches this block
    cells: list[dict] | None  # table_row only: [{"para_id", "html"}]

def render_document(model: DocumentModel) -> list[Block]: ...
```

**Rendering rules:**

- Walk `model.body.elements` in order (preserves table position among paragraphs).
- **Runs:** inserted → `<ins class="diff-insert">…</ins>`; deleted → `<del class="diff-delete">…</del>` (no longer dropped); normal → existing formatting tags (`<b>/<i>/<u>/<s>/<sup>/<sub>`). Field codes use display text (as `to_display_html`). All text HTML-escaped.
- **Soft breaks:** `<w:br/>` within a run/paragraph → `<br>`.
- **Comments (boundary segmentation):** collect every comment anchor touching the paragraph as `(start_offset, end_offset, comment_id)` (clamped to the paragraph; a cross-paragraph anchor contributes its head/middle/tail to the relevant paragraphs). Compute the sorted set of boundary offsets, split the paragraph's character stream at those boundaries **and** at run-formatting boundaries, and wrap each segment covered by ≥1 comment in `<span class="ws-comment-ref" data-comment-ids="id1 id2">…</span>` (space-joined ids handle overlap/nesting without illegal overlapping tags). Resolved vs open comments get distinct styling via a class.
- **Empty paragraph:** emit an empty block (preserves spacing), not nothing.
- **Table:** one `block.kind == "table_row"` per row; `cells` carries each cell's rendered HTML; `html` is a legible row rendering (cells visually separated) for the non-grid Stage-1 view.

The renderer is pure (no I/O, no session) and unit-tested directly against `DocumentModel` fixtures.

---

## 4. `GET /document` (enriched payload)

```jsonc
{
  "document": { "...": "summary + unsaved_changes, as today" },
  "blocks": [
    { "kind": "paragraph", "para_id": "…", "html": "…", "style": "…", "comment_ids": ["…"] },
    { "kind": "table_row", "para_id": "…", "html": "…", "cells": [ { "para_id": "…", "html": "…" } ], "comment_ids": [] }
  ],
  "comments": [
    { "thread_id": "…", "status": "open|resolved", "author": "…", "referenced_text": "…",
      "comments": [ { "comment_id": "…", "author": "…", "text": "…", "is_reply": false } ] }
  ]
}
```

`comments` reuses the `list_comments` tool's thread shape (filter `"all"`). The flat `paragraphs` array is replaced by `blocks`. (Page test that only checks panel anchors stays valid.)

---

## 5. Client behavior (`workspace.js` / `workspace.html` / `workspace.css`)

- **Render blocks** into the scroll container: paragraphs as block elements (real spacing), `table_row` blocks styled as distinct rows. Insertions/deletions colored; comment-covered spans highlighted (open vs resolved).
- **Comments column** (right side): a card per thread — author, status, referenced text, replies. Order top-to-bottom by anchor position.
- **Click-linking:** click a comment card → scroll the document to its anchor and flash the highlight; click a highlighted span → focus/scroll its card. (Card-to-row vertical alignment + leader lines are best-effort; full balloons are Stage 3.)
- **Refresh after agent run:** `renderResult()` already calls `refreshDocument()`; update it to consume `blocks` + `comments` so agent edits/comments show with the new styling.

---

## 6. Tests

- `tests/test_document_render.py` (pure Python): paragraph → block with block-level separation; inserted run → `diff-insert`; deleted run → `diff-delete` (present, not dropped); soft break → `<br>`; single comment anchor → `ws-comment-ref` span with the right `data-comment-ids`; **overlapping** anchors → segmented spans carrying multiple ids; **cross-paragraph** anchor → highlight spans in both paragraphs; table → `table_row` blocks with `cells`; empty paragraph → empty block.
- `tests/test_workspace_api.py`: `GET /document` returns `blocks` + `comments` with expected shapes; a doc with a known comment surfaces it in `comments` and the anchored block's `comment_ids`.
- Existing full suite stays green, **0 warnings**; card UI at `/` unaffected.
- **Manual QA:** open a real manuscript from `test_data/local/` and synthetic `test.docx`; verify paragraph breaks, a tracked change shows ins/del coloring, an anchored comment is highlighted and readable in the side list, click-linking works, and the viewer refreshes after an agent run.

---

## 7. Out of scope for M6a

- **All editing** → M6b.
- Tables-as-grid and margin-balloon layout → Stage 3 (see [umbrella §4](stage1_M6_spec.md#4-out-of-scope-for-the-whole-milestone)).
