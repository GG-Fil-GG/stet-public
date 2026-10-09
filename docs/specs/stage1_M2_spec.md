# Stage 1 — Milestone 2 Spec: Domain gaps for agent editing

**Status:** Approved & Implemented 2026-05-29 — see [`stage1_M2_report.md`](stage1_M2_report.md)
**Plan reference:** [Milestone 2](../stage1_implementation_plan.md#milestone-2--domain-gaps-for-agent-editing)

---

## 1. Goal

Close the domain gaps the M1 tool layer cannot yet wrap: creating and removing anchored comments, a **guarded** save/export path (overwrite confirmation + workspace containment), and a snapshot-based **checkpoint** mechanism for agent-edit undo.

---

## 2. Files to create or modify

| File | Change |
|------|--------|
| `src/document_model/comments.py` | Add high-level `CommentStore.add_comment_at(...)` (new anchored root comment) and `CommentStore.remove_comment(...)`. |
| `src/document_model/model.py` | Thin `DocumentModel.add_comment(...)` / `remove_comment(...)` delegating to the store (mirrors existing `add_reply`). |
| `src/document_model/serializer_comments.py` | Extend `_serialize_comment_anchors` to inject anchors for **new root comments** at a character range, and to **strip** anchors/`w:comment` entries for removed comments. |
| `src/checkpoints.py` | New — `CheckpointStore` (save/restore/list/prune) over `DocumentModel.to_dict()`/`from_dict()`. Standalone module (shared by M3 loop and M4 workspace). |
| `src/agent/tools.py` | Add `add_comment`, `remove_comment` tools; add `workspace_root` + `overwrite` guards to `export_document` / `create_document`. |
| `src/agent/tool_schemas.py` | Schemas for the two new tools; add `overwrite` to export/create schemas. |
| `src/agent/registry.py` | Register the two new tools; update export/create injection flags (`requires_workspace_root=True`). |
| `tests/test_comment_write_delete.py` | New — add/remove comment + serializer round-trip. |
| `tests/test_checkpoints.py` | New — checkpoint save/restore/prune + identity. |
| `tests/test_agent_tools.py` | Extend for guarded export/create and the two new tools. |

---

## 3. Public API surface

### 3.1 Model / comment-store domain API

```python
# CommentStore (and a thin DocumentModel delegate)
add_comment_at(para_id: str, start: int, end: int, text: str,
               author: str, timestamp: datetime) -> Comment
#   New ROOT comment anchored to the precise [start, end) character range within
#   para_id. Generates all IDs (comment_id, para_id, durable_id, text_id, rsid),
#   builds a CommentAnchor, registers a single-comment thread.
#   Single-paragraph anchors only in M2 (cross-paragraph ranges are Stage 3).

remove_comment(comment_id: str) -> bool
#   Remove a comment. Removing a ROOT removes the whole thread (root + replies +
#   their anchors); removing a REPLY removes just that reply (Word's behavior).
#   Returns False if the id is unknown.
```

### 3.2 Serializer changes

**Precise range anchoring (Resolved decision 1).** New root-comment anchors are placed at the exact `[start, end)` character range by **reusing the existing offset→run machinery** from the revisions mixin (`serializer_revisions.py`) — the same code path that inserts `<w:ins>`/`<w:del>`:

- `_analyze_runs(para_xml)` maps character offsets to run XML positions.
- `_insert_at_offset(para_xml, offset, content)` inserts at an offset, splitting a run mid-run via `_split_run_and_insert`.

Anchor injection for a root comment whose anchor is not yet in `document.xml`:

1. Insert `<w:commentRangeEnd w:id="X"/>` + a `<w:commentReference w:id="X"/>` run at `end`.
2. Insert `<w:commentRangeStart w:id="X"/>` at `start`.

Insert **end before start** (descending offset) so positions remain valid. The markers carry no `<w:t>` text, so they do not perturb the character-offset map — no new offset logic is required. Both `_serialize_comment_anchors` and these primitives are mixins on the same `DocumentSerializer`, so the comment code calls `self._insert_at_offset(...)` directly.

Also ensure the new root comment is emitted into `comments.xml` and `commentsExtended/Ids/Extensible` (verify whether those parts are regenerated from `model.comments` or patched, and wire accordingly).

**Known risk area — field codes / citations.** Paragraphs containing field codes (EndNote citations, `[CITATION_X]` placeholders) are where the displayed-text offset model and the run/`instrText` structure can diverge. This is explicitly tested (see §4), per the project owner's note that more testing here is acceptable.

**Removal:** strip `<w:comment>` (comments.xml), the matching `<w:commentRangeStart/End>` + `<w:commentReference>` (document.xml), and the `commentsExtended/Ids/Extensible` entries for removed ids.

### 3.3 Checkpoints (`src/checkpoints.py`)

```python
@dataclass
class CheckpointMetadata:
    checkpoint_id: str
    created_at: str          # ISO-8601
    label: str               # e.g. "before: address comment 3"

class CheckpointStore:
    def __init__(self, checkpoints_dir: Path, max_checkpoints: int = 30): ...
    def save(self, model: DocumentModel, label: str = "") -> str       # -> checkpoint_id
    def restore(self, checkpoint_id: str) -> DocumentModel
    def list(self) -> list[CheckpointMetadata]                          # newest-first
    # FIFO prune to max_checkpoints happens inside save()
```

- Each checkpoint is a JSON file (`{checkpoint_id}.json`) holding `model.to_dict()` plus metadata.
- `restore` returns a `DocumentModel` via `from_dict` (Tier 1 item #2 guarantees comment object identity after round-trip).
- **Policy is not enforced here.** `checkpoint_policy` (`per_agent_turn` / `per_mutating_tool`) decides *when* `save` is called — that is the agent loop's job in **M3**. M2 provides the mechanism only.
- `max_checkpoints` defaults to the constant `30`; reading it from `.stet/config.json` is wired in **M4**.

### 3.4 Agent tools (new + changed)

```python
add_comment(model, para_id: str, start: int, end: int, text: str,
            author: str = "Stet") -> dict
#   {"comment_id","thread_id","para_id","start","end"}

remove_comment(model, comment_id: str) -> dict
#   {"removed": true, "comment_id": ...}  (ToolError "not_found" if unknown)

# CHANGED — now guarded:
export_document(model, path, workspace_root, include_track_changes=True,
                overwrite=False) -> dict
create_document(path, workspace_root, overwrite=False) -> dict
```

**Guard semantics (both writers):**

- **Containment:** the resolved target path must lie inside `workspace_root`; otherwise `ToolError("outside_workspace", ...)`.
- **Overwrite:** if the target exists and `overwrite is False` → `ToolError("overwrite_requires_confirmation", ...)`. The caller confirms and re-invokes with `overwrite=True`:
  - **User (UI):** native OS confirm dialog (M5) sets `overwrite=True`.
  - **Agent:** the loop (M3) surfaces the error in chat, waits for an explicit user "yes", then re-calls with `overwrite=True`. Never auto-confirms.
- Writing to a **new** path proceeds without prompting.

This realizes [Resolved decisions §4](../stage1_implementation_plan.md#4-save-export-and-create-document) at the tool layer; the native dialogs and the unified UI button wiring are M5.

---

## 4. Tests to write

- `tests/test_comment_write_delete.py`:
  - `add_comment_at` creates an anchored root comment; export → reparse → comment present and the **reparsed anchor highlights the exact `[start, end)` text** (precise-range proof).
  - **Mid-run / multi-run range:** anchor a range that starts mid-run and/or spans multiple runs; reparse → correct highlighted text (proves run-splitting works).
  - **Field-code paragraph:** anchor a range in a paragraph containing a field code / citation; reparse → anchor lands on the intended displayed text (the known-risk case).
  - `remove_comment` on a root strips the thread; export → reparse → gone (comment + anchors).
  - `remove_comment` on a reply removes only the reply.
  - Unknown id → `False` / `ToolError`.
- `tests/test_checkpoints.py`:
  - save → restore returns equal model state (counts + comment object identity).
  - FIFO prune keeps newest `max_checkpoints`.
  - `list()` newest-first with metadata.
- `tests/test_agent_tools.py` (extend):
  - `export_document` / `create_document`: containment violation raises; existing-path without `overwrite` raises `overwrite_requires_confirmation`; `overwrite=True` succeeds; new path succeeds.
  - `add_comment` / `remove_comment` tool happy-paths + errors.

**Baseline:** full suite green, **0 warnings**.

---

## 5. Out of scope for this milestone

- The agent loop and checkpoint **policy** enforcement (when to snapshot) — **M3**.
- Native folder/save dialogs and the UI Save/Save As buttons — **M5**.
- Reading `max_checkpoints` / `checkpoint_policy` from `.stet/config.json` — **M4** (M2 uses the default constant + constructor arg).
- Cross-paragraph (multi-paragraph) comment anchors — Stage 3 (M2 is single-paragraph anchors).
- RTF/PPTX/txt readers — **M8**.
- Any route, template, or `desktop_app.py` change.

---

## 6. Resolved decisions

All four open questions were resolved with the project owner on 2026-05-29.

1. **`add_comment` anchor granularity → precise range (a).** Implement precise `[start, end)` anchoring by reusing the existing offset→run primitives (`_analyze_runs`, `_insert_at_offset`) that already power track-changes insertion (§3.2). Paragraph-level-only (b) was rejected as a gap we would have to revisit. Field-code paragraphs are the known risk and are explicitly tested (§4).
2. **Checkpoint module location → standalone `src/checkpoints.py`.** No runtime/performance difference between standalone and nested; standalone wins purely on dependency hygiene (avoids agent↔workspace coupling and M3-before-M4 ordering issues).
3. **Overwrite confirmation → `overwrite: bool = False` parameter** with `ToolError("overwrite_requires_confirmation")` when a target exists and `overwrite` is False; caller re-invokes with `True` after confirming.
4. **`remove_comment` of a root with replies → remove the entire thread** (root + replies + all anchors); removing a reply removes only that reply. Mirrors Word's behavior.
