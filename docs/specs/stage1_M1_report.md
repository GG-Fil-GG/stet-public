# Stage 1 — Milestone 1 Report: Tool layer

**Status:** Complete
**Spec:** [`stage1_M1_spec.md`](stage1_M1_spec.md) (approved 2026-05-29)

---

## 1. What was done

Built the `src/agent/` tool layer: nine callable, JSON-serializable tools wrapping existing document/file code, with canonical provider-neutral schemas, a registry, and a structured error type. All testable in pure Python (no LLM, no browser). Added a bundled blank template for document creation and a 29-test suite.

Commit: _see the M1 commit on `main` (recorded in the plan Status table)._

## 2. Files touched

**Created:**

| File | Purpose |
|------|---------|
| `src/agent/__init__.py` | Public surface: `ToolError`, `ToolSpec`, `TOOLS`, `get_tool`, `list_tools`. |
| `src/agent/errors.py` | `ToolError(code, message)` with `to_dict()`. |
| `src/agent/tools.py` | Nine tool handlers (4 filesystem-bound, 5 document-bound). |
| `src/agent/tool_schemas.py` | Nine Pydantic input schemas (LLM-facing params only). |
| `src/agent/registry.py` | `ToolSpec` dataclass + `TOOLS` registry + lookup helpers. |
| `assets/template.docx` | Bundled blank template (relocated from repo root). |
| `tests/test_agent_tools.py` | 29 unit tests. |

**Modified:** `docs/stage1_glossary.md` (Modules / Agent tools / Types populated), `docs/stage1_decision_log.md` (3 M1 entries), `docs/stage1_implementation_plan.md` (Status row), `docs/specs/stage1_M1_spec.md` (status header).

No existing `src/` modules were changed — tools wrap existing code.

## 3. Deviations from spec

None. All four open questions were answered with the spec's recommended options:

1. Document binding via explicit `model` / `workspace_root`, registry+resolution deferred to M4. ✓
2. Bundled `assets/template.docx` (owner-created, verified, relocated from root). ✓
3. `export_document` / `create_document` shipped functional-but-unguarded; guards → M2. ✓
4. Default author `"Stet"`, overridable per call (`author` param on `edit_paragraph` and `add_comment_reply`). ✓

**Note on #4:** the spec listed `author` only on `add_comment_reply`; per the owner's note that author should be editable, `edit_paragraph` also takes an `author` param (default `"Stet"`). Minor additive expansion, in the spirit of the answer.

## 4. New names added to the glossary

In [`stage1_glossary.md`](../stage1_glossary.md):

- **Modules:** `src/agent/`, `tools.py`, `tool_schemas.py`, `registry.py`, `errors.py`.
- **Agent tools:** all nine (`list_workspace_files`, `read_document`, `read_file`, `create_document`, `list_comments`, `read_paragraph`, `edit_paragraph`, `add_comment_reply`, `export_document`).
- **Types:** `ToolError`, `ToolSpec`, `*Input` schema models.

## 5. Decisions made mid-implementation

In [`stage1_decision_log.md`](../stage1_decision_log.md), all 2026-05-29 / Milestone 1:

- Document binding (explicit `model` / `workspace_root`; resolution deferred to M4).
- `export_document` / `create_document` shipped unguarded (guards → M2).
- Blank template location (`assets/template.docx`).

## 6. Test results

- New: `tests/test_agent_tools.py` — **29 passed**.
- Full suite: **575 passed, 0 failed, 0 skipped, 0 warnings** (was 546; +29). Baseline maintained.

Template verification (pre-implementation): `template.docx` parses to 1 empty paragraph, 0 comments/threads/revisions, and round-trips through the serializer cleanly.

## 7. What to watch in the next milestone

- **M2 (Domain gaps):** add `add_comment` / `remove_comment`; wrap `export_document` / `create_document` in the **guarded** save/export path (mandatory overwrite confirmation, path-inside-workspace containment) and the unified UI/agent API; build the checkpoint save/restore stack. Register the new tools in `src/agent/registry.py` and add their schemas.
- **Injection seam:** M3/M4 must populate `model` (document-bound) and `workspace_root` (filesystem-bound) using the registry's `requires_model` / `requires_workspace_root` flags. The LLM supplies only schema params.
- **`read_file`:** RTF/PPTX/txt deliberately raise `unsupported_format` until M8.
- **PDF reads** parse all pages; if large reference PDFs become a problem, consider a page-range/default-cap param (not needed yet).
