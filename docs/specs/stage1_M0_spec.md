# Stage 1 — Milestone 0 Spec: Baseline and conventions

**Status:** Approved (2026-05-29) — all three open questions answered: include hygiene edits, keep `config_version`, per-workspace config only.
**Plan reference:** [Milestone 0](../stage1_implementation_plan.md#milestone-0--baseline-and-conventions)

---

## 1. Goal

Finalize the workspace on-disk layout, the `.stet/config.json` schema, and the test conventions for Stage 1 — agreeing all boundaries that later milestones depend on, with **no feature code and no user-facing changes**.

---

## 2. Files to create or modify

M0 is documentation/conventions only. No files under `src/` or `tests/` change.

| File | Change |
|------|--------|
| `docs/stage1_implementation_plan.md` | Replace the M0 *Tasks* sketch with a finalized **"Workspace conventions"** subsection (folder layout + config schema + test conventions). Update the **Status** table row for M0. |
| `docs/stage1_glossary.md` | Populate the **Config keys** and **Workspace layout** sections (currently placeholders marked "populated in M0"). |
| `docs/pre_transition_audit.md` | *(Conditional — see Open question 1)* Fix stale references in the "Codebase context" section. |
| `docs/specs/stage1_M0_report.md` | Created after implementation per the report template. |

No `.stet/` files are committed to the repo — `.stet/` is created at runtime per workspace folder (the *code* that writes it is M4). M0 only specifies its shape.

---

## 3. Public API surface

These are the conventions later milestones consume. They are the substantive deliverable of M0.

### 3.1 Workspace folder layout

```
{workspace_folder}/
  manuscript.docx              # user files — any name, any depth
  references/                  # optional; user-organized, not required
    style_guide.pdf
    notes.rtf
  .stet/                       # reserved namespace — Stet owns this dir
    workspace.json             # session state: open doc, chat history, settings (schema finalized in M4)
    config.json                # workspace configuration (schema below)
    checkpoints/               # agent DocumentModel snapshots (FIFO, default max 30)
```

**Rules:**

- `.stet/` is **reserved**. Stet never treats anything inside `.stet/` as a user document. File scans (M1 `list_workspace_files`) exclude `.stet/`.
- User files may live at any depth in the workspace folder; subfolder organization (e.g. `references/`) is a user convention, not enforced.
- Stet **does not modify user files** until a save/export explicitly targets that path.
- `.stet/` is safe to delete (loses session state + undo history, not user documents) and safe to add to a user's `.gitignore`.

### 3.2 `.stet/config.json` schema

Workspace-level configuration. Created with defaults on first workspace open (the writing code is M4). Stage 1 initial key set:

```json
{
  "config_version": 1,
  "max_checkpoints": 30,
  "max_agent_steps": 20,
  "checkpoint_policy": "per_agent_turn"
}
```

| Key | Type | Default | Allowed values / notes |
|-----|------|---------|------------------------|
| `config_version` | int | `1` | Schema version for forward-compatible migrations. |
| `max_checkpoints` | int | `30` | ≥ 1. FIFO prune when checkpoint count exceeds this. |
| `max_agent_steps` | int | `20` | ≥ 1. Hard cap on tool-call iterations per user message. |
| `checkpoint_policy` | str | `"per_agent_turn"` | One of `"per_agent_turn"` (snapshot before each user message) or `"per_mutating_tool"` (snapshot before each mutating tool call; finer undo, more disk). |

**Extensibility:** This is the *initial* set. Later milestones add their own keys under their own milestone (e.g. M3 may add an agent-error-policy key). Each addition is recorded in the glossary by the milestone that introduces it. Unknown keys are ignored (forward-compatible); missing keys fall back to code defaults.

### 3.3 Defaults source of truth

Default values are documented here and in the glossary. The **code constants** that hold these defaults are introduced in M4 (workspace state), not M0. M0 fixes the values and names only.

### 3.4 Test conventions (Stage 1)

- Synthetic, committed fixtures live in `test_data/synthetic/`; local-only fixtures in `test_data/local/` (gitignored).
- New workspace/JSON tests mirror the `tests/test_routes.py` pattern: `TestClient`, JSON-shape assertions, synthetic fixtures, no network/LLM.
- Agent-loop tests mock the LLM transport; real-LLM integration tests are gated on `OPENAI_API_KEY` and skip cleanly when absent.
- The 0-warning baseline from Tier 1 cleanup is maintained: no new `DeprecationWarning`/`ResourceWarning` introduced.

---

## 4. Tests to write

None new. M0 introduces no code.

**Acceptance check:** the existing full suite still passes with the post-Tier-1 baseline (**546 passing, 0 warnings**), confirming the doc-only changes broke nothing.

---

## 5. Out of scope for this milestone

- Any code under `src/` or `tests/` (all feature work starts at M1).
- The detailed `workspace.json` schema — only its location/purpose is fixed here; its fields are finalized in **M4**.
- Code that reads/writes/validates `config.json` or creates `.stet/` — **M4**.
- Config keys beyond the four above — added by the milestones that need them.
- Native folder picker — **M5**.
- Any global (user-level, cross-workspace) configuration file. Stage 1 is per-workspace config + code defaults only (see Open question 3).

---

## 6. Open questions

These need project-owner input before I implement. Per the workflow, I will stop after you read this and proceed once these are answered.

1. **Hygiene scope.** The plan lists an *optional* M0 task: fix stale references in `pre_transition_audit.md`'s "Codebase context" section — specifically the note that `thread_objects` is a live cache (item #3 fixed it; the cache description is now stale) and the line "Many tests depend on `test_data/test.docx` … one known pre-existing test failure in `test_session_utils.py::...test_serialize_dom_session`" (the fixture path is now `test_data/synthetic/test.docx` and the known failure was resolved during Tier 1). **Include these edits in M0, or leave the audit doc as a historical record and skip?** My recommendation: include them — they are low-risk and reduce confusion for future sessions.

2. **`config_version` field.** I propose adding `config_version: 1` now for cheap forward-compatibility (so M4+ can migrate schemas gracefully). **Keep it, or omit until a migration is actually needed?** My recommendation: keep it.

3. **Config scope.** I propose **per-workspace config only** for Stage 1 (each workspace's `.stet/config.json`, with code defaults as fallback) — no global user-level config file. **Confirm, or do you want a global default that per-workspace config overrides?** My recommendation: per-workspace only for now; a global layer can be added later without breaking this.
