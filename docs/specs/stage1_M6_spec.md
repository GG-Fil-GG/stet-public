# Stage 1 — Milestone 6 Spec: Document viewer (umbrella)

**Status:** Split into **M6a** (read fidelity) + **M6b** (edit mode); decisions resolved 2026-06-01.
**Plan reference:** [Milestone 6](../stage1_implementation_plan.md#milestone-6--document-viewer)
**Sub-specs:** [M6a — read fidelity](stage1_M6a_spec.md) · [M6b — edit mode](stage1_M6b_spec.md)

This umbrella holds what is common to both halves: the goal, the resolved up-front decisions, the codebase design constraints, and what's out of scope for the whole milestone. The two sub-specs hold the per-half files, API surface, and tests.

---

## 1. Goal

Replace the M5 read-only **stub** in the centre panel with a faithful document viewer that shows the open docx the way an editor expects — paragraph structure, soft breaks, **inline track changes**, and **anchored comments** — and lets the user **edit paragraphs** in place. This is the milestone that makes the workspace usable for reviewing and editing, not just for driving the agent.

Because it is the largest Stage-1 milestone, it is split:

| Half | Scope | Output |
|------|-------|--------|
| **M6a — Read fidelity** | `render_document` renderer (paragraph blocks, soft breaks, track-change ins/del coloring, comment range highlighting incl. overlap + cross-paragraph), table-row legibility, enriched `GET /document`, **side comments list** with click-linking, refresh-after-agent-run. **Pure viewing.** | A genuinely useful read-only viewer. |
| **M6b — Edit mode** | Reusable TipTap editor module, per-paragraph edit/save via `PATCH /document/paragraph/{para_id}` → `edit_paragraph`, pre-edit checkpoint. | In-viewer editing. |

M6a lands and is fully testable before M6b begins.

---

## 2. Resolved decisions (2026-06-01)

Answers to the original open questions, now binding for both sub-specs:

1. **Renderer location:** `src/workspace/render.py`, kept **pure** (`render_document(model) -> list[Block]`, no session state) so it is trivially movable later. The card UI will not reuse it (different rendering need — per-thread suggestion diffs — and it is being retired).
2. **Comments layout:** a right-hand **side list** of comment cards (per the Word review-pane screenshot), with anchored text highlighted in the document and **click-linking** both ways. Precise card-to-row vertical alignment + persistent leader lines are **best-effort in M6**, full margin-balloon polish is **Stage 3**.
3. **Overlapping comments:** done **properly** via boundary segmentation (`CommentAnchor` carries `start_offset`/`end_offset`, and `end_para_id` for cross-paragraph spans), not simplified.
4. **Editor packaging:** build a **standalone** workspace editor; **do not** refactor the card UI onto it (the card UI is being obsoleted — no maintenance investment).
5. **Manual-edit author:** keep the default author **"Stet"** for now; a real **user identity** is the preferred default once that concept exists (noted for a future milestone).
6. **Checkpoint on manual edit:** **yes** — a manual paragraph save snapshots **before** applying the edit (mirrors the agent's per-turn checkpoint) so manual and agent edits share one undo model.
7. **Phasing:** **split into M6a + M6b** (this document).

These supersede §7 of the original draft.

---

## 3. Shared design constraints (from the codebase)

- **The model already has the data.** `model.body.elements` is an ordered list of `Paragraph` and `Table`; `Table.rows` → cells (each a `Paragraph`); each `Run` carries `revision_type` with `is_inserted()` / `is_deleted()`. Comments live in `model.comments`; `CommentAnchor` has `para_id`, `start_offset`, `end_offset`, and `end_para_id` (cross-paragraph). So the viewer is a **rendering** problem, not a parsing one.
- **The M5 stub uses the wrong renderer.** `Paragraph.to_html()` / `to_display_html()` *skip* deleted runs, don't mark inserted runs, emit no block wrapper, and ignore comments. M6a needs a **new renderer**.
- **HTML generation is server-side in this codebase** (`src/diff_html.py`, `src/routes/helpers.py`, `build_paragraph_cache_from_model()`). M6 follows suit: a testable Python renderer, reusing the card UI's `diff-insert` / `diff-delete` CSS color language.
- **The card UI's track-change rendering is diff-based, not model-based** (it colors a diff of *original vs suggested* text). The open document's **own** tracked changes (`w:ins`/`w:del`) render straight from `Run.revision_type` — new code, even though it reuses the visual classes.
- **TipTap loads once in `base.html`** (`window.createTipTapEditor`), used by the cards. `workspace.html` is **standalone** (does not extend `base.html`), so M6b's editor loads its own TipTap and is a clean break (decision 4).
- **The workspace API + viewer are JSON/standalone.** `GET /api/workspace/{id}/document` already returns `{document, paragraphs:[…]}`; M6a enriches it. The `/workspace` page + `workspace.{js,css}` are extended; the card UI at `/` is untouched. Save/`is_dirty`/checkpoint machinery (M2/M4) is reused unchanged.

---

## 4. Out of scope for the whole milestone

- **Tables as real HTML `<table>` grids → Stage 3.** M6a renders rows *legibly* (distinct rows, not run-on text), not as a true grid.
- **Margin-balloon comment layout** (Word-style aligned balloons + leader lines) → Stage 3; M6a uses inline highlights + a side list + click-linking.
- **Headings/outline navigation, images, footnotes/endnotes.**
- **Rich comment authoring UI** (creating/resolving comments by selecting text) — the agent can already add/remove/reply; a manual comment UI is later.
- **Accept/reject individual tracked changes from the viewer** — later; M6 only *displays* them.
