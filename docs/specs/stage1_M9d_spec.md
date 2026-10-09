# Stage 1 — M9d Spec: Post-pilot correctness & UX fixes

**Status:** Approved 2026-09-22 (all four §7 questions resolved per recommendations)
**Plan reference:** inserted before [M9c — Pilot + closeout](../stage1_implementation_plan.md#status); M9c closeout resumes after M9d
**Depends on:** M1–M9c-prep
**Origin:** M9c pilot (2026-06-10, diagnosed 2026-06-22) — see [pilot checklist §Pilot outcome](stage1_M9c_pilot_checklist.md#pilot-outcome)

---

## 1. Goal

The first real-manuscript pilot produced correct agent edits that were then **silently lost**, could not be traced to a specific file (truncated filenames), and contained corrupted dashes. M9d fixes the three blocking findings so a clean re-pilot can pass and Stage 1 can close out. Nothing here is new capability — it is making the capability we already have trustworthy.

**Scope discipline:** direct fixes to the three pilot findings only. No new context-management system, no streaming/perf rework, no formatting-preserving rewrite (Stage 2). Leverage existing machinery (`DocumentModel.to_dict`/`from_dict`, already used by checkpoints; the M9a protection seam) rather than building new.

## 2. Findings being addressed (recorded)

| # | Finding | Severity | Fix area |
|---|---------|----------|----------|
| 1 | Agent/manual edits live only in RAM; any re-open re-parses the pristine file and discards them, so Save writes an edit-free document | **Critical (data loss)** | Working-model persistence + open guard |
| 2 | Truncated filenames in the file panel; no tooltip, no resize — user can't tell which doc is open | Medium (usability; contributed to #1) | File-tree tooltip (+ optional resize) |
| 3 | En/em-dashes corrupted by the model (unprotected); returned as control chars | Medium (output quality) | Extend Unicode protection to dashes |

Not in scope here (already logged / deferred): run-formatting loss on agent edits (Stage 2 backlog), image reading (Stage 2 backlog), deeper run performance (see §5).

## 3. Scope — three direct fixes

### 3.1 Edit durability (the critical fix)

**Problem.** `WorkspaceSession.persist()` writes only the open-document pointer, conversation, and chat log to `.stet/workspace.json`. The edited `DocumentModel` is discarded on any re-parse (`open_document`), and re-parse is triggered by a file-tree click, folder re-open, browser reload (new session), or restart.

**Direct fix — persist the working model, restore it instead of re-parsing when it is newer than the source.**

- The model already serializes losslessly: `DocumentModel.to_dict()` / `from_dict()` (the same path `CheckpointStore` uses). Reuse it — no new serializer.
- After any **mutating** operation on the active document (agent run that changed the model, or a manual `PATCH` edit), write the working model to `.stet/working/<doc-hash>.json` alongside a small header: `{schema_version, document_path, source_mtime, saved_at}`. `<doc-hash>` is derived from the workspace-relative document path so multiple open docs don't collide.
- On `open_document(rel_path)`: if a working snapshot exists for that path **and** its `source_mtime` still matches the file on disk (the underlying file hasn't changed under us), load the **working model** (with edits + `is_dirty=True`) instead of re-parsing. Otherwise parse the pristine file as today. A stale/mismatched/corrupt snapshot is ignored (parse pristine) and logged — a snapshot can never brick a document, mirroring the config-resilience rule.
- **Clear the snapshot** when edits are no longer "unsaved-in-RAM-only":
  - on successful **Save**/export **to the same path** (edits are now in the file); and
  - on explicit **discard** (see the guard below) or checkpoint restore to a pristine state.
  - Saving a **copy** to a different path leaves the working snapshot for the original intact (the original still has unsaved edits until saved).
- Persist the snapshot from the same places that already call `session.persist()` after mutation (agent finalize, manual PATCH), so there is one obvious write point per path.

**Hardening the open guard (defense in depth).** The existing 409 `unsaved_changes` guard clearly failed to prevent the loss. Independent of persistence:
- Re-opening the **same** document that has unsaved changes must not silently re-parse; require `force`, same as switching away (today the guard exists but the pilot still lost edits — add/verify a test that a same-path re-open with unsaved changes is guarded).
- With persistence in place, even a `force` re-open or a fresh session recovers from the working snapshot, so the guard becomes a warning rather than the only line of defence.

**Acceptance:** run agent → edits in viewer → click the same/other file / reload the page / reopen the folder → the edits are still there; then Save → open in Word → edits present. No path silently reverts to pristine.

### 3.2 Filename visibility

**Direct fix (primary):** add a `title` attribute (native tooltip) carrying the full name to every file and folder label in the tree (`renderNode` in `static/js/workspace.js`), and to the open-document path element in the header. Hovering reveals the full filename — the user's stated minimum ("hovering brings up the full name").

**Not in M9d (§7 Q3):** a resizable/scrolling file panel or draggable divider. The tooltip satisfies the finding for Stage 1; the panel enhancement may be revisited later. Recorded here so a reader knows it was considered, not forgotten.

**Acceptance:** hovering any tree entry shows its full name; a long name is fully readable without guessing.

### 3.3 Dash protection

**Problem.** En-dash (`–`, U+2013) and em-dash (`—`, U+2014) are absent from `UNICODE_PROTECTION_MAP`, so they reach the model raw and come back corrupted.

**Direct fix:** add `–`/`—` (and, if trivially justified, the horizontal-ellipsis `…` and non-breaking hyphen `‑`, which have the same corruption profile) to the **agent** protection map in `src/agent/unicode_protection.py` with the same `__UNICODE_*__` placeholder convention.

**Map-parity decision (see §7 Q1).** The M9a parity test asserts the agent map equals the card-UI map verbatim (`test_map_matches_card_ui_verbatim`). Recommended: **relax that test to "agent map ⊇ card-UI map"** and add the dash entries agent-side only. This fixes the agent path without editing the card-UI baseline (`src/llm_transport.py`) — respecting the Stage 1 rule to leave the legacy card path untouched. (Alternative: add the same entries to both maps to keep them identical; rejected as an unnecessary edit to the legacy baseline.) Also extend the prompt's token guidance (`prompts.py`) to mention the dash tokens, consistent with the existing `__UNICODE_GTE__` etc. description.

**Acceptance:** an agent edit that includes an en/em-dash round-trips the real character into the tracked change (no control char, no leftover placeholder); the recovered pilot text shows `2013–2017`, not `2013␓2017`.

## 4. Files

| File | Change |
|------|--------|
| `src/workspace/state.py` | Working-model snapshot: write on mutation; restore-if-newer in `open_document`; clear on same-path save/discard; snapshot path helper |
| `src/routes/workspace.py` | Persist snapshot after agent finalize and manual `PATCH`; clear on `/save` to same path; ensure same-path re-open honours the unsaved guard |
| `src/agent/unicode_protection.py` | Add en/em-dash (+ optional `…`, `‑`) entries |
| `src/agent/prompts.py` | Mention dash tokens in the existing token-preservation guidance |
| `static/js/workspace.js` | `title` tooltips on tree labels + header path (optional: resizable/scrolling panel) |
| `tests/` | Durability round-trip + guard tests; dash round-trip test; parity-test relax; snapshot-resilience test |

No changes to `src/document_model/` (reusing existing `to_dict`/`from_dict`) or to the card-UI path.

## 5. Out of scope (explicitly)

- **Deeper agent-run performance** — streaming token output, prompt caching, focused/partial context, parallel tool calls. M9c-prep already made long runs *workable* (visible progress, responsive stop, bounded context). The remaining Cursor-class speed gap is a real but large architectural workstream; it belongs in **Stage 2**, not Stage 1 closeout. (See §7 Q2 if you want it pulled forward.)
- **Formatting-preserving agent edits** (run-level bold etc.) — Stage 2 backlog, unchanged.
- **Image reading** — Stage 2 backlog, unchanged.
- **Auto-saving edits into the source `.docx`** — the fix persists a *working snapshot* in `.stet/`, not silent writes to the user's file; explicit Save/export remains the only thing that touches the document on disk.
- **The default-route flip and Stage 1 closeout** — those are M9c, resumed after M9d passes a clean re-pilot.

## 6. Tests

| Test | Asserts |
|------|---------|
| Durability: run mutation → new session → open | Working snapshot restores the edited model (`is_dirty`, revision count) instead of pristine |
| Durability: save to same path clears snapshot | After Save, a fresh open parses pristine (no stale snapshot) |
| Durability: save-a-copy keeps original snapshot | Original path still restores edits after a copy is saved elsewhere |
| Durability: stale/corrupt snapshot ignored | Mismatched `source_mtime` or unparsable snapshot → parse pristine, logged, no crash |
| Guard: same-path re-open with unsaved edits | Requires `force`; unforced re-open is refused |
| Dash round-trip | `–`/`—` protected outbound, restored inbound; end-to-end `edit_paragraph` keeps the real dash |
| Map parity relaxed | Agent map is a superset of the card-UI map (card map unchanged) |
| Tooltip render | Tree labels carry a `title` with the full name (page/DOM test) |

Full suite stays green, 0 warnings; the card UI at `/` and its tests are untouched.

## 7. Resolved decisions (2026-09-22)

1. **Dash map parity** — **relax** the parity test to "agent map ⊇ card-UI map" and add the dash entries **agent-side only**; the legacy card-UI map (`src/llm_transport.py`) is left untouched.
2. **Slowness** — **deferred to Stage 2.** M9c-prep already cleared the "unworkable" bar; streaming/caching/focused-context/parallelism are a separate Stage 2 workstream, not a Stage 1 closeout blocker.
3. **Filename panel** — the **hover tooltip is sufficient** for Stage 1. The resizable/scrolling panel is not part of M9d (may be revisited later).
4. **Milestone naming** — filed as **M9d** (post-pilot fixes); **M9c** remains pilot + closeout.
