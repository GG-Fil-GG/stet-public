# Stage 1 — M9d Report: Post-pilot correctness & UX fixes

**Status:** Complete (automated; manual re-pilot pending project owner — see §6)
**Spec:** [stage1_M9d_spec.md](stage1_M9d_spec.md) (approved 2026-09-22)
**Origin:** M9c pilot (2026-06-10, diagnosed 2026-06-22) — [pilot checklist §Pilot outcome](stage1_M9c_pilot_checklist.md#pilot-outcome)
**Date:** 2026-09-22

---

## 1. What was built

The three direct fixes from the spec — no new capability, no context-management system, no
streaming/perf rework, no formatting-preserving rewrite. Existing machinery
(`DocumentModel.to_dict`/`from_dict`, the M9a protection seam) was reused rather than rebuilt.

### 1.1 Edit durability — the critical fix (`src/workspace/state.py`, `src/routes/workspace.py`)

The pilot's data loss came from edits living only in RAM: any re-parse (`open_document`, triggered
by a file-tree click, folder re-open, browser reload, or restart) discarded them, so Save wrote an
edit-free document.

- **Working-model snapshot.** After a mutating operation, `WorkspaceSession.persist_working_model()`
  writes the live `DocumentModel` to `.stet/working/<doc-hash>.json` with a header
  `{schema_version, document_path, source_mtime, saved_at}`. `<doc-hash>` is a SHA-1 of the
  workspace-relative document path, so multiple open docs never collide. Serialization reuses
  `DocumentModel.to_dict()` (the same path `CheckpointStore` uses) — no new serializer.
- **Restore-if-unchanged.** `open_document(rel_path)` now checks for a snapshot first: if one exists
  **and** its recorded `source_mtime` still matches the file on disk, it loads the working model
  (edits + `is_dirty=True`) instead of re-parsing. A stale (`source_mtime` mismatch), corrupt, or
  wrong-schema snapshot is ignored — the pristine file is parsed and the event logged. A snapshot can
  never brick a document (mirrors the config-resilience rule).
- **Clear when no longer unsaved-in-RAM.** `sync_working_model()` (persist-if-dirty-else-clear) runs
  after every agent finalize and after checkpoint restore; `persist_working_model()` runs after a
  manual `PATCH` edit; and a **same-path** Save clears the snapshot (edits are now in the file). A
  **save-a-copy** to a different path leaves the original's snapshot intact.
- **Open-guard hardening.** The existing 409 `unsaved_changes` guard on same-path re-open is kept and
  now covered by a test; with persistence in place a `force` re-open or a fresh session *recovers*
  from the snapshot rather than losing edits, so the guard is defence-in-depth rather than the only
  line of defence.

### 1.2 Filename visibility (`static/js/workspace.js`)

`renderNode` now sets a native `title` tooltip on every tree label — the full workspace-relative
path on file rows, the folder name on folder rows — so hovering a truncated entry reveals the full
name. The folder-root path in the header already carried a `title`; there is no separate header
element for the open document (it is shown via tree highlight), so the tree tooltip is the fix. The
resizable/scrolling panel was explicitly left out of M9d (§7 Q3).

### 1.3 Dash protection (`src/agent/unicode_protection.py`, `src/agent/prompts.py`)

Four publishing-punctuation characters the pilot saw corrupted were added to the **agent** protection
map with the usual `__UNICODE_*__` convention: en dash (U+2013), em dash (U+2014), horizontal
ellipsis (U+2026), and non-breaking hyphen (U+2011). The prompt's token-preservation guidance now
names those tokens (in words, so no real symbol leaks into the prompt). The card-UI map
(`src/llm_transport.py`) is untouched — the agent map is now a superset (§5).

## 2. Files

**Modified**

- `src/workspace/state.py` — working-model snapshot: `working_dir`, `_working_path`, `_source_mtime`,
  `persist_working_model`, `clear_working_model`, `sync_working_model`, `_load_working_model`;
  `open_document` restores-if-unchanged.
- `src/routes/workspace.py` — `sync_working_model()` after agent finalize and checkpoint restore;
  `persist_working_model()` after manual `PATCH`; same-path `/save` clears the snapshot.
- `src/agent/unicode_protection.py` — en/em-dash, ellipsis, non-breaking hyphen entries;
  `M9D_AGENT_ADDITIONS`; docstring/parity note updated to "superset".
- `src/agent/prompts.py` — dash/ellipsis/nb-hyphen tokens named in the token-preservation bullet.
- `static/js/workspace.js` — `title` tooltips on file and folder tree labels.
- Tests: `test_workspace_state.py`, `test_workspace_api.py`, `test_agent_unicode.py`.

**Added**

- `docs/specs/stage1_M9d_report.md` (this file).

## 3. Tests

Full suite (M9d spec fixes only): **755 passed, 1 skipped, 4 deselected, 0 warnings** (749 before; 6
new tests). See §7 on the deselected tests. The pilot-driven additions in §7a bring the suite to
**770 passed**.

| Test | Asserts |
|------|---------|
| `TestWorkingModelPersistence::test_edits_restore_in_a_fresh_session` | Snapshot written on mutation; a fresh workspace auto-restores the edited model (`is_dirty`, revision count), not pristine |
| `…::test_stale_snapshot_is_ignored` | Source `mtime` changed → snapshot discarded, pristine parsed (`is_dirty=False`) |
| `…::test_clear_removes_snapshot` | `clear_working_model()` deletes the snapshot file |
| `…::test_sync_clears_when_not_dirty` | `sync_working_model()` clears the snapshot once `is_dirty` is False |
| `…::test_corrupt_snapshot_falls_back_to_disk` | Unparsable snapshot → pristine parse, no crash |
| `TestWorkingModelDurability::test_agent_edits_survive_reopen` | End-to-end: agent run → new session → GET /document shows the restored edits |
| `…::test_same_path_save_clears_snapshot` | After a same-path Save, a fresh open is clean (no stale snapshot) |
| `…::test_same_path_reopen_with_unsaved_is_guarded` | Unforced same-path re-open → 409; `force` re-open recovers the edit from the snapshot |
| `TestProtectRestore::test_dashes_round_trip` | En/em-dash, ellipsis, nb-hyphen protected outbound, restored inbound |
| `…::test_dash_additions_not_in_card_ui` | The added chars are absent from the card-UI map |
| `…::test_map_is_superset_of_card_ui` (relaxed) | Every card-UI entry is present verbatim; the agent map adds exactly `M9D_AGENT_ADDITIONS` |

One existing test (`test_map_matches_card_ui_verbatim`) was **renamed and relaxed** to the superset
form per §7 Q1. The card-UI map and its tests are otherwise untouched; the legacy card UI at `/` is
unaffected.

## 4. Deviations from spec / notes

- **Ellipsis + non-breaking hyphen included.** The spec listed these as optional ("if trivially
  justified"). They share the exact corruption profile of the dashes and cost nothing to add, so all
  four went in together.
- **Header open-doc element.** The spec mentioned tooltipping "the open-document path element in the
  header"; there is no such element (the open doc is indicated by tree highlight), so the tree-label
  tooltips are the complete fix. The folder-root path already had a `title`.
- **Parity guard made count-independent.** Rather than hardcode the card-map size (the M9a docstring's
  "34" was already off — the map has 35 entries), the relaxed test asserts the agent map differs from
  the card map by *exactly* the M9d additions, which won't drift if either map changes.

## 5. Decisions logged

See `docs/stage1_decision_log.md` (2026-09-22): working-model snapshot in `.stet/working/` restored
only when the source is unchanged; same-path Save clears the snapshot, save-a-copy preserves the
original's; Unicode map parity relaxed to a superset (agent-only dash additions); filename tooltip
chosen over a resizable panel for Stage 1; deeper run performance deferred to Stage 2.

## 6. Manual QA (project owner — gates the M9c pilot re-run)

1. Run the agent so it makes edits → the edits show in the viewer. Then **click the same file / another
   file in the sidebar, reload the page, and reopen the folder** → the edits are still there each time.
2. With unsaved edits, **Save** → open the file in Word → the edits are present (no edit-free document).
3. Hover a **truncated filename** in the sidebar → the full name appears in a tooltip.
4. Ask the agent to write text containing an **en/em-dash** (e.g. a year range like `2013–2017`) → the
   saved tracked change shows the real dash, not a control character or a leftover `__UNICODE_*__`
   token.

## 7. Deselected live-API tests (pre-existing, environment)

Four tests that call the **real OpenAI API** fail with a 401 "invalid_api_key" —
`test_integration.py::TestGenerateAndAccept` (3, card-UI path) and
`test_agent_integration.py::TestOpenAILive::test_summarise_open_comments` (1). Verified on the
pre-M9d commit (`984c964`): they fail there too, so this is **not** an M9d regression — the `.env`
`OPENAI_API_KEY` has expired over the ~3-month gap since M9c-prep. Unlike the live-Ollama test
(gated behind `RUN_OLLAMA_TESTS`), these OpenAI live tests are **not** gated behind an env flag, so
they run (and fail) whenever the key is absent/expired. **Reported, not fixed** (per Stage 1 scope
discipline): the project owner can either refresh the key or decide whether to gate these live tests
behind an opt-in flag as a follow-up. They were excluded from the green count via `--deselect`.

## 7a. Pilot-driven additions (not in the M9d spec)

The M9d re-pilot surfaced two problems beyond the three spec findings. Both were fixed at the project
owner's request and recorded in the decision log (2026-09-22); they are logged here so the report
reflects what actually shipped in this milestone.

**1. OpenAI retries 0 → 3 (`src/agent/llm_tools.py`).** The re-pilot died on **step 1** twice with
`APIConnectionError: Server disconnected without sending a response`. M9c-prep's `_OPENAI_MAX_RETRIES = 0`
(set for responsive Stop) surfaced a single transient drop as a fatal 500. Raised to 3 (timeout still
120 s); retries fire only on failure with short backoff, so Stop stays responsive. Test
`TestOpenAIClientConfig` updated. **Caveat:** two rapid step-1 failures on a small request may be
environmental (VPN/proxy, or the bleeding-edge Python 3.14 + httpx stack), not pure OpenAI flakiness —
to revisit if retries don't clear it.

**2. Agent run transcript + wired-up logging (diagnostic).** The pilot showed the agent making dozens
of tool calls with no edits, and there was no way to see why: the M9c-prep per-step logs were silently
dropped (no logging was ever configured) and the step trace only persists on clean finalize, so
stopped/crashed runs left nothing.
- `src/logging_config.py` — `configure_logging()` (called from `main.py`): enables INFO for `src.*` and
  filters the `/agent/progress` poll out of the access log. Per-step logs now include a bounded arg
  summary and each tool's ok/ERROR.
- `src/agent/run_transcript.py` — `RunTranscript` writes one flushed JSONL file per run under
  `.stet/runs/` (`run_start`/`assistant`/`tool_result`/`run_end`, args/results size-bounded). The route
  attaches one per run and writes `run_end` **even on crash**, so a stopped/crashed run is fully
  reviewable. `loop.py` gained an optional `transcript` sink.
- Tests: `test_run_transcript.py`, `test_logging_config.py`, `TestTranscriptSink` (loop),
  `TestRunTranscriptRoute` (route, incl. a crashed-run-records-error case). Suite now **770 passed**.

These are diagnostic tooling, not new product capability; logging can never break a run (all
transcript/file errors are swallowed and logged).

## 8. Next

Resume **M9c — Pilot + closeout**: re-run the pilot task on the real manuscript
(`test_data/local/stage1_M9c`) with the durability, tooltip, and dash fixes in place; confirm edits
persist end-to-end; then the default-route flip, docs audit, and Stage 1 closeout.
