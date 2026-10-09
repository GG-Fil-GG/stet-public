# Stage 1 — Milestone 9b Report: Workspace config in the settings UI

**Status:** Complete (automated + browser-verified; manual QA pending project owner — see §6)
**Spec:** [stage1_M9_spec.md](stage1_M9_spec.md) §5 (umbrella spec; no separate M9b spec by decision Q1)
**Date:** 2026-06-08

---

## 1. What was built

Exposed the four per-workspace `WorkspaceConfig` keys in the Agent settings modal, closing the M7 QA gap (config was previously only editable by hand-editing `.stet/config.json`). LLM-credential handling is unchanged. UI-only — the config API (`GET`/`PUT /api/workspace/{id}/config`) and its validation/coercion already existed and are tested (M4).

- New **Workspace settings** section in the settings modal with `tool_error_policy` and `checkpoint_policy` (selects) and `max_agent_steps` / `max_checkpoints` (number inputs, `min=1`).
- On open: if a workspace is open, the section loads current values via `GET …/config` and enables the controls; otherwise the controls are disabled (greyed) with an "Open a folder to edit workspace settings." note.
- On save: LLM credentials still go to `localStorage`; if a workspace is open, the four values are sent via `PUT …/config`. A failed PUT shows an error toast and keeps the modal open.

## 2. Files

**Modified**

- `templates/workspace.html` — Workspace settings block in the settings modal (`ws-tool-error-policy`, `ws-checkpoint-policy`, `ws-max-agent-steps`, `ws-max-checkpoints`, plus `ws-workspace-settings-note`).
- `static/js/workspace.js` — `loadWorkspaceSettings()` (GET + populate/enable, or disable+note); `openSettings` calls it; `saveSettings` is now async and `PUT`s config when a workspace is open.
- `tests/test_workspace_page.py` — assert the four controls render.
- `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, the M9 spec.

**No backend change.** `ConfigUpdate` / `get_config` / `update_config` and `coerce_config` were already in place.

## 3. Tests

Full suite: **737 passed, 1 skipped, 0 warnings** (unchanged count — the new assertions extend the existing `test_workspace_page_serves`; the config round-trip is already covered by `test_workspace_config.py`).

| Test | Asserts |
|------|---------|
| `test_workspace_page_serves` | Settings modal markup includes all four workspace-config control ids |
| (existing) `test_workspace_config.py` | `PUT …/config` round-trips `tool_error_policy` / `checkpoint_policy` / `max_agent_steps` / `max_checkpoints`; invalid values coerce to defaults |

Browser-verified (running dev server): the modal renders the Workspace settings section; with no folder open the four controls are disabled and the note shows.

## 4. Deviations from spec

None of substance. The spec said "disable it with a note" for the no-workspace state; implemented exactly that (controls greyed/disabled, note shown) rather than hiding them, so users can see the available knobs. Invalid/blank numbers are sent as `null` and coerced server-side to the per-key default (existing `coerce_config` behavior), matching spec §5.3.

## 5. Decisions logged

See `docs/stage1_decision_log.md` (2026-06-08): controls disabled-with-note (not hidden) when no workspace; a failed config `PUT` aborts the close and toasts the error (credentials, already written to `localStorage`, are not rolled back — the two scopes are independent).

## 6. Manual QA checklist (project owner)

1. With **no folder open**, open settings → the Workspace settings controls are greyed out with the note.
2. **Open a folder**, open settings → the four controls populate from the workspace config and are editable.
3. Change **`tool_error_policy`** to **Stop and ask**, Save → reopen settings to confirm it persisted (and check `.stet/config.json`).
4. Trigger a tool error in an agent run (e.g. ask it to read a non-existent paragraph) → confirm the **stopped** banner appears. *(This is the manual path M7 QA could not exercise — the original reason M9b exists.)*
5. Change **Max checkpoints** / **Max agent steps**, Save, and confirm the next agent run respects them.

## 7. Next

M9c — Pilot + closeout (its own spec, post-pilot): end-to-end pilot, default-route flip, audit/status update, Stage 1 marked complete.
