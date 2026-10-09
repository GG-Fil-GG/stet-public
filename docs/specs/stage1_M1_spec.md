# Stage 1 — Milestone 1 Spec: Tool layer

**Status:** Approved & implemented (2026-05-29) — all four open questions answered with the recommended options; see [report](stage1_M1_report.md).
**Plan reference:** [Milestone 1](../stage1_implementation_plan.md#milestone-1--tool-layer)

---

## 1. Goal

Build a layer of callable **agent tools** that wrap existing document/file code, each testable from pure Python with typed inputs and JSON-serializable outputs — **no LLM and no browser required**.

---

## 2. Files to create or modify

| File | Change |
|------|--------|
| `src/agent/__init__.py` | New package; export the public tool registry surface. |
| `src/agent/tools.py` | New — the nine tool handler functions. |
| `src/agent/tool_schemas.py` | New — one canonical JSON Schema (via Pydantic) per tool (provider-neutral; per-provider translation is M3). |
| `src/agent/registry.py` | New — `name → (handler, schema)` registry with lookup helpers. |
| `src/agent/errors.py` | New — `ToolError` exception type. |
| `assets/blank.docx` | New *(conditional — Open question 2)* — bundled minimal blank template for `create_document`. |
| `tests/test_agent_tools.py` | New — unit tests per tool against synthetic fixtures. |
| `docs/stage1_glossary.md` | Populate **Modules**, **Agent tools**, **Types** sections (in the M1 report). |

No existing `src/` modules are modified; tools **wrap** existing code, they do not change it.

---

## 3. Public API surface

### 3.1 Two handler families (document binding)

Until the workspace session exists (M4), tools split by what they operate on:

- **Filesystem-bound** tools take a `workspace_root: Path` and/or a `path: str`.
- **Document-bound** tools take an already-loaded `model: DocumentModel` (the "open document").

The LLM never passes a Python object: the **schemas** (§3.3) expose only JSON params (`path`, `para_id`, `new_text`, …). Binding the active `DocumentModel` and resolving a `path`→open-model is the **loop's / workspace session's** job (M3/M4). M1 handlers receive the resolved `model` directly so they are unit-testable. *(See Open question 1.)*

### 3.2 Tool handlers (signatures + return shapes)

All success returns are JSON-serializable `dict`s. Failures raise `ToolError(code: str, message: str)` (the M3 loop decides how to surface errors to the LLM).

```python
# Filesystem-bound
list_workspace_files(workspace_root: Path) -> dict
#   {"files": [{"name","path","type","size_bytes"}], "count": int}
#   path is workspace-relative; excludes the .stet/ namespace; recurses.

read_document(path: str | Path) -> dict
#   Parse a docx via parse_docx() and summarize:
#   {"path","paragraph_count","comment_count","thread_count","revision_count","title","author"}

read_file(path: str | Path) -> dict
#   Dispatch by extension to existing file_parsers/* (reuses attachments.py logic):
#   {"path","file_type","content": str, "meta": {...}}
#   M1 formats: pdf, xlsx, xls, csv, docx. (rtf/pptx → M8; txt → M8.)

create_document(path: str | Path) -> dict
#   Create a new blank docx at path (from bundled template). M1: UNGUARDED.
#   {"path","created": true}

# Document-bound
list_comments(model: DocumentModel, comment_filter: str = "open") -> dict
#   comment_filter in {"all","open","resolved"}.
#   {"threads": [{"thread_id","root_comment_id","status","author",
#                 "referenced_text","comment_count",
#                 "comments": [{"comment_id","author","text","is_reply"}]}],
#    "count": int}

read_paragraph(model: DocumentModel, para_id: str) -> dict
#   {"para_id","text","display_text","style","formatting_summary",
#    "comment_ids": [...], "has_revisions": bool}
#   text = Paragraph.plain_text (citation placeholders); display_text = raw_text.

edit_paragraph(model: DocumentModel, para_id: str, new_text: str,
               track_changes: bool = True) -> dict
#   Wraps apply_revision_from_plain_text(model, [para_id], new_text, track_changes=...).
#   {"para_id","applied": true,"edit_count": int,"track_changes": bool}

add_comment_reply(model: DocumentModel, thread_id: str, text: str,
                  author: str = "Stet") -> dict
#   Resolve thread_id → root comment id, then model.add_reply(...).
#   {"comment_id","thread_id","author"}

export_document(model: DocumentModel, path: str | Path,
                include_track_changes: bool = True) -> dict
#   Wraps DocumentSerializer().serialize(model, output_path=path, ...). M1: UNGUARDED.
#   {"path","include_track_changes": bool}
```

**"UNGUARDED" means:** M1 ships `export_document` / `create_document` as functional writers with **no overwrite confirmation and no strict workspace-containment check** — those guards are explicitly **M2** (per the plan's "Defer to Milestone 2"). *(See Open question 3.)*

### 3.3 Schemas and registry

- `tool_schemas.py`: one canonical schema per tool as a Pydantic model (input params only, JSON-Schema-emittable). Provider-specific translation (OpenAI/Ollama formats) is **M3**.
- `registry.py`: a `ToolSpec` record (`name`, `handler`, `schema`, `description`) and a registry dict with `get_tool(name) -> ToolSpec` and `list_tools() -> list[ToolSpec]`.

### 3.4 Defaults / constants

- Edit/reply author defaults to the constant `"Stet"` (matches existing `apply_revision_from_plain_text`). A config key can be added later if needed. *(See Open question 4.)*

---

## 4. Tests to write

`tests/test_agent_tools.py`, using synthetic fixtures in `test_data/synthetic/` (mirrors `tests/test_file_parsers.py` / `tests/test_serializer.py` patterns; no LLM, no network):

- **list_workspace_files:** temp dir with docx + pdf + a `.stet/` dir → correct file list, `.stet/` excluded, workspace-relative paths.
- **read_document:** `test.docx` → expected paragraph/comment/thread counts.
- **list_comments:** `test.docx` → thread/comment shapes; `open` vs `resolved` vs `all` filtering.
- **read_paragraph:** known `para_id` → text, comment_ids, formatting summary; unknown id → `ToolError`.
- **edit_paragraph:** tracked edit produces a revision; plain edit changes text without revision; re-serialize round-trip reflects the change.
- **add_comment_reply:** reply added to an existing thread; unknown thread → `ToolError`.
- **read_file:** one fixture per supported format → non-empty `content`, correct `file_type`.
- **export_document:** serialize to a temp path → file exists and re-parses with the edit present.
- **create_document:** new blank docx at a temp path → exists and parses to an empty/near-empty model.
- **registry:** every tool is registered; `get_tool`/`list_tools` behave; each schema emits valid JSON Schema.

**Baseline:** full suite stays green with **0 warnings**.

---

## 5. Out of scope for this milestone

- `add_comment` / `remove_comment` (new anchored comments, deletion) — **M2**.
- Overwrite confirmation and strict workspace-containment for writes — **M2**.
- Agent checkpoints / undo — **M2**.
- The agent loop, provider-specific schema translation, and `llm_transport` changes — **M3**.
- Open-document registry and `path`→active-`model` resolution (workspace session) — **M4**.
- RTF, PPTX, and plain-text (`.txt`) readers — **M8**.
- Any UI, route, or `desktop_app.py` change.

---

## 6. Open questions

Per the workflow I will stop after you read this and proceed once these are answered.

1. **Document binding (§3.1).** Confirm M1 handlers take an explicit `model: DocumentModel` (document-bound) and `workspace_root: Path` / `path` (filesystem-bound), with the open-document registry and `path`→model resolution **deferred to M4**. *Recommendation: yes — keeps M1 pure-Python testable and avoids pre-building M4's session.*

2. **Blank template for `create_document`.** There is **no** blank `.docx` in the repo today. I propose committing a minimal `assets/blank.docx` (generated once via the existing `python-docx` dependency, standard styles, no content) as the bundled template. *Recommendation: yes.* Alternative: generate a blank doc in code on each call (no committed asset) — simpler repo, but less control over the baseline styles.

3. **Export/create in M1 vs M2.** The plan lists `export_document` and `create_document` under both M1 (tools) and M2 (guarded save/export path). I propose M1 ships them **functional but unguarded** (no overwrite prompt, no containment check), with the guards added in M2 — so the agent loop demo after M4 can already write files. *Recommendation: yes.* Alternative: defer both tools wholly to M2 (M1 becomes read/edit-only).

4. **Default author.** Use the constant `"Stet"` for agent edits and replies in M1, revisiting a configurable `track_changes_author` later? *Recommendation: yes.*
