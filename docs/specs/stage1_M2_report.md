# Stage 1 — Milestone 2 Report: Domain gaps for agent editing

**Status:** Complete
**Spec:** [`stage1_M2_spec.md`](stage1_M2_spec.md) (approved 2026-05-29)

---

## 1. What was done

Closed the domain gaps the M1 tool layer could not yet wrap:

- **New anchored comments** — `DocumentModel.add_comment(...)` / `CommentStore.add_comment_at(...)` create a root comment highlighting a precise `[start, end)` character range. The serializer injects the `commentRangeStart/End` + reference run at the exact offsets, and the new comment flows into all four comment parts.
- **Comment removal** — `DocumentModel.remove_comment(...)` / `CommentStore.remove_comment(...)`. A root removes its whole thread (root + replies + anchors); a reply removes only itself. The serializer strips removed comments from `document.xml` and all four comment parts at export time.
- **Guarded writers** — `export_document` / `create_document` now require a `workspace_root`, enforce path containment, and refuse to overwrite an existing file unless `overwrite=True`.
- **Checkpoints** — new standalone `src/checkpoints.py` with `CheckpointStore` (save/restore/list/FIFO-prune) over `DocumentModel.to_dict()/from_dict()`.

Two new tools (`add_comment`, `remove_comment`) registered; `export_document` / `create_document` schemas + registry updated.

Commit: _see the M2 commit on `main` (recorded in the plan Status table)._

## 2. Files touched

**Created:**

| File | Purpose |
|------|---------|
| `src/checkpoints.py` | `CheckpointStore` + `CheckpointMetadata`: snapshot save/restore/list/prune. |
| `tests/test_comment_write_delete.py` | 13 tests — add/remove comment + serializer round-trip (incl. field-code paragraph). |
| `tests/test_checkpoints.py` | 7 tests — save/restore/identity/list/FIFO-prune. |

**Modified:**

| File | Change |
|------|--------|
| `src/document_model/comments.py` | `CommentStore.add_comment_at(...)` and `remove_comment(...)`. |
| `src/document_model/model.py` | `DocumentModel.add_comment(...)` (with range validation) / `remove_comment(...)` delegates. |
| `src/document_model/serializer.py` | `_compute_removed_comments(...)` pre-pass; removal state init. |
| `src/document_model/serializer_comments.py` | Root-anchor injection at a precise range (own rPr-preserving splitter); strip removed comments across all parts. |
| `src/agent/tools.py` | `add_comment` / `remove_comment` tools; `_guard_write_target(...)`; guarded `export_document` / `create_document`. |
| `src/agent/tool_schemas.py` | `AddCommentInput`, `RemoveCommentInput`; `overwrite` on create/export. |
| `src/agent/registry.py` | Registered the two new tools; `requires_workspace_root=True` on create/export. |
| `tests/test_agent_tools.py` | Updated guarded create/export calls; added guard + add/remove tool tests. |
| `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, `docs/specs/stage1_M2_spec.md` | Glossary/log/status/spec-status updates. |

## 3. Deviations from spec

All four open questions were resolved before implementation and built as agreed (precise-range anchoring, standalone checkpoint module, `overwrite` bool, Word-style root/reply removal). One implementation **finding** and two minor additive choices:

1. **Finding — shared run-splitter was buggy (reported during M2, fixed in the M2 follow-up).** The spec assumed precise anchoring could reuse the revisions mixin's `_insert_at_offset` → `_split_run_and_insert`. On a mid-run offset, `_split_run_and_insert` emitted `<w:r><w:t...>after</w:r>`, dropping the closing `</w:t>` **and** the run's `<w:rPr>`, producing invalid XML (a reparse fails immediately). Per the architecture rule, M2 first shipped a correct, self-contained splitter in `serializer_comments.py` and reported the bug. **Follow-up (approved before M3):** the shared `_split_run_and_insert` is now fixed (replicates the run opening + `rPr` on both halves, keeps `<w:t>` balanced, well-formed fallback for `<w:t>`-less runs); the redundant local splitter was removed and `_inject_root_anchor` now delegates to `_insert_at_offset`. Regression tests added (`tests/test_serializer.py::TestInsertAtOffsetRunSplit`). The bug was latent (the mid-run branch is only reached by tracked **insertions**, which the revisions suite did not exercise) — see the decision log follow-up entry.

2. **`CheckpointMetadata.sequence` added** (spec listed 3 fields). A monotonic per-store sequence makes `list()` newest-first and FIFO-pruning deterministic even for same-microsecond saves. Logged in the decision log.

3. **Comment removal is diffed at serialize time** (`_compute_removed_comments`) rather than tracked on the model. The model simply no longer contains removed comments; the serializer recovers paraId/durableId from the source parts. Logged in the decision log.

The **field-code risk** the spec flagged did **not** materialize: anchoring inside `47BAD27B` (a citation/field-code paragraph) round-trips with the exact intended text. The displayed-text offset model (`<w:t>`-only, matching the model's `raw_text`) aligns with how anchors are reparsed. Covered by two dedicated tests.

## 4. New names added to the glossary

In [`stage1_glossary.md`](../stage1_glossary.md):

- **Modules:** `src/checkpoints.py`.
- **Agent tools:** `add_comment`, `remove_comment`; `create_document` / `export_document` updated to guarded (`overwrite` param, `workspace_root` injected).
- **Types:** `CheckpointStore`, `CheckpointMetadata`; `AddCommentInput` / `RemoveCommentInput`.

## 5. Decisions made mid-implementation

In [`stage1_decision_log.md`](../stage1_decision_log.md), all 2026-05-29 / Milestone 2:

- Precise anchoring uses a local run-splitter, not the shared (buggy) one.
- Comment removal is diffed at serialize time.
- `CheckpointMetadata` carries a `sequence` field.

## 6. Test results

- New: `tests/test_comment_write_delete.py` — **13 passed**; `tests/test_checkpoints.py` — **7 passed**.
- Extended: `tests/test_agent_tools.py` — **38 passed** (was 29).
- Full suite: **604 passed, 0 failed, 0 skipped, 0 warnings** (run with `-W error`). Legacy card-UI baseline (routes / integration / workflow) intact.

Precise-range proof: clean, start, whole-paragraph, mid-run (both ends split), and **field-code** ranges all reparse to the exact intended substring. Removal proof: root strip removes the comment + its anchors from `document.xml` and `comments.xml`; reply-only removal preserves the thread.

## 7. What to watch in the next milestone

- **M3 (Agent loop):** owns checkpoint **policy** — *when* to call `CheckpointStore.save` (`checkpoint_policy`: `per_agent_turn` vs `per_mutating_tool`) and the `max_agent_steps` cap. Must inject `model` / `workspace_root` per the registry flags, and surface `ToolError("overwrite_requires_confirmation")` in chat, re-calling with `overwrite=True` only after explicit user consent (never auto-confirm).
- **M4 (Workspace backend):** reads `max_checkpoints` / `checkpoint_policy` from `.stet/config.json` (M2 uses the default constant + constructor arg); wires `.stet/checkpoints/` to `CheckpointStore`.
- **Run-splitter cleanup (finding #1): done** — `_split_run_and_insert` is fixed and covered by tests; comment anchoring delegates to it. No further action.
- **Cross-paragraph comment anchors** remain Stage 3 (M2 is single-paragraph anchors only).
