# Stage 1 — Milestone 0 Report: Baseline and conventions

**Status:** Complete
**Spec:** [`stage1_M0_spec.md`](stage1_M0_spec.md) (approved 2026-05-29)

---

## 1. What was done

Finalized the Stage 1 workspace conventions — no feature code, no user-facing changes — and applied the approved documentation hygiene:

- **Workspace folder layout** finalized in the implementation plan: `.stet/` as Stet's reserved namespace (`workspace.json`, `config.json`, `checkpoints/`), user files untouched until an explicit save/export.
- **`.stet/config.json` schema** finalized with the initial four keys (`config_version`, `max_checkpoints`, `max_agent_steps`, `checkpoint_policy`), per-workspace only.
- **Test conventions** documented (synthetic vs local fixtures, `test_routes.py` JSON pattern, mocked-LLM agent tests, 0-warning baseline).
- **Glossary** Config-keys and Workspace-layout sections populated (were M0 placeholders).
- **Audit hygiene** applied to `pre_transition_audit.md` per Open question 1.
- **Decision log** updated with the three M0 decisions.

Commit: _docs-only; see the M0 commit on `main` (recorded in the plan Status table)._

## 2. Files touched

| File | Change |
|------|--------|
| `docs/stage1_implementation_plan.md` | Replaced M0 *Tasks* sketch with a finalized "Workspace conventions" subsection (layout + config schema + test conventions); marked tasks done; updated the Status table row for M0. |
| `docs/stage1_glossary.md` | Populated **Config keys** (4 keys) and **Workspace layout** (4 paths). |
| `docs/pre_transition_audit.md` | Corrected "Codebase context": stale `thread_objects` cache → on-demand `get_thread_object()`; test note → `test_data/synthetic/test.docx` and removed the resolved known-failure note. |
| `docs/stage1_decision_log.md` | Added three M0 entries. |
| `docs/specs/stage1_M0_spec.md` | Marked Approved. |
| `docs/specs/stage1_M0_report.md` | This report (new). |

No `src/` or `tests/` files changed.

## 3. Deviations from spec

None. All three open questions were answered with the spec's recommended options (include hygiene edits; keep `config_version`; per-workspace config only).

## 4. New names added to the glossary

In [`stage1_glossary.md`](../stage1_glossary.md):

- **Config keys:** `config_version`, `max_checkpoints`, `max_agent_steps`, `checkpoint_policy`.
- **Workspace layout:** `.stet/`, `.stet/workspace.json`, `.stet/config.json`, `.stet/checkpoints/`.

No new module, tool, route, or type names (M0 introduces no code).

## 5. Decisions made mid-implementation

In [`stage1_decision_log.md`](../stage1_decision_log.md), all dated 2026-05-29 / Milestone 0:

- Include `config_version` field from the start.
- Per-workspace config only (no global config) for Stage 1.
- Include the audit-doc hygiene edits in M0.

## 6. Test results

Full suite run (doc-only changes; confirms nothing broke):

- **546 passed, 0 failed, 0 skipped, 0 warnings** — matches the post-Tier-1 baseline.

## 7. What to watch in the next milestone

- **M1 (Tool layer)** introduces the first code under `src/agent/`. The glossary's **Modules**, **Agent tools**, and **Types** sections move from placeholder to populated — keep names consistent with the plan's M1 tool table.
- `list_workspace_files` (M1) must honor the M0 rule: **exclude `.stet/`** from scans.
- The detailed **`workspace.json` schema** is still deferred to M4; M1–M3 should not hard-code its shape.
- Code constants holding the config defaults are an **M4** deliverable; M1–M3 reference the documented values, not a config file.
- Minor stale number noticed but not changed (out of approved scope): `pre_transition_audit.md` still says "~490 test functions" in the directory-tree comment; actual count is 546. Flag for a future opportunistic edit.
