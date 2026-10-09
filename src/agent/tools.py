"""Agent tool handlers (Stage 1, Milestone 1).

Each function wraps existing document/file code behind a typed, JSON-serializable
interface so the agent loop can call it. Tools split into two families:

- **Filesystem-bound** tools take a ``workspace_root`` and/or a ``path``.
- **Document-bound** tools take an already-loaded ``DocumentModel`` (the open
  document). Resolving a path to an open model, and tracking which document is
  active, is the workspace session's job (Milestone 4); these handlers receive
  the resolved model directly so they stay pure-Python testable.

Success returns are plain JSON-serializable dicts. Failures raise
:class:`~src.agent.errors.ToolError`.

Milestone 2 update: ``export_document`` and ``create_document`` are now
**guarded** — both require a ``workspace_root`` and enforce path containment,
and both refuse to overwrite an existing file unless ``overwrite=True``. The
caller (UI in M5, agent loop in M3) is responsible for confirming and
re-invoking with ``overwrite=True``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Optional

from src.document_model import (
    DocumentModel,
    DocumentSerializer,
    parse_docx,
)
from src.document_model.plain_text_edits import apply_revision_from_plain_text
from .errors import ToolError

# Default author for agent-authored edits and replies. The author is overridable
# per call (the app already supports author-name editing on export); "Stet" is the
# default identity. A configurable default can be added later via .stet/config.json.
DEFAULT_AUTHOR = "Stet"

# Bundled minimal blank template used by create_document.
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
TEMPLATE_PATH = ASSETS_DIR / "template.docx"

# Files/directories the workspace scan never treats as user content.
RESERVED_DIR = ".stet"

# read_file dispatch by extension.
_PDF_EXTS = {".pdf"}
_SPREADSHEET_EXTS = {".xlsx", ".xls", ".csv"}
_DOCX_EXTS = {".docx"}
_RTF_EXTS = {".rtf"}
_PPTX_EXTS = {".pptx"}
_TEXT_EXTS = {".txt", ".md"}

# Plain-text read guards (M8). RTF/PPTX cap inside their own parsers.
_TEXT_ENCODINGS = ("utf-8", "latin-1", "cp1252")
_TEXT_MAX_CHARS = 200_000
_TEXT_TRUNCATION_MARKER = "\n\n[... truncated]"

_WS_RE = re.compile(r"\s+")

# Numeric ranges written with an en dash in the source (e.g. "2013–2017", "30–90").
# The model sometimes drops the protected en-dash token when it rewrites a
# sentence, leaving "2013 2017" or "2013-2017" (M9e finding #2). We restore the
# en dash only for digit–digit pairs that were an en-dash range in the original,
# so prose is never touched.
_NUMERIC_RANGE_RE = re.compile(r"(\d+)\u2013(\d+)")


def _normalize_ws(text: str) -> str:
    """Lowercase and collapse runs of whitespace — for tolerant text matching."""
    return _WS_RE.sub(" ", text).strip().lower()


def _restore_numeric_range_dashes(original_text: str, new_text: str) -> tuple[str, list[str]]:
    """Restore en dashes the model dropped from numeric ranges (M9e).

    Bounded strictly to digit–digit pairs that appeared as an en-dash range in
    ``original_text``: if the revision rendered such a pair as ``a b``, ``a-b``,
    ``a - b`` or ``a‑b`` (non-breaking hyphen), the en dash is put back. Prose
    and any pair that was not an en-dash range in the original are left untouched.

    Returns the (possibly) repaired text and the list of restored ranges.
    """
    ranges = set(_NUMERIC_RANGE_RE.findall(original_text))
    if not ranges:
        return new_text, []
    repaired = new_text
    restored: list[str] = []
    for a, b in ranges:
        good = f"{a}\u2013{b}"
        for bad in (f"{a} - {b}", f"{a} {b}", f"{a}-{b}", f"{a}\u2011{b}"):
            if bad in repaired:
                repaired = repaired.replace(bad, good)
                restored.append(good)
    return repaired, restored


# --------------------------------------------------------------------------- #
# Write guards (shared by export_document / create_document)
# --------------------------------------------------------------------------- #

def resolve_in_workspace(workspace_root: Path | str, path: Path | str) -> Path:
    """Resolve ``path`` against ``workspace_root`` and enforce containment.

    Relative paths resolve against the workspace root; absolute paths are used
    as-is. Either way the result must lie inside the workspace root. This is the
    shared read-side resolver (the agent loop uses it for ``path_args`` tools and
    ``folder.resolve_path`` delegates to it).

    Raises:
        ToolError("outside_workspace"): the resolved path escapes the workspace.
    """
    root = Path(workspace_root).resolve()
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()

    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ToolError(
            "outside_workspace",
            f"Path is outside the workspace: {target}",
        ) from exc
    return target


def _guard_write_target(
    path: Path | str,
    workspace_root: Path | str,
    overwrite: bool,
) -> Path:
    """Resolve a write target and enforce containment + overwrite policy.

    - Relative ``path`` is resolved against ``workspace_root``; absolute paths
      are used as-is. Either way the result must lie inside ``workspace_root``.
    - If the target exists and ``overwrite`` is False, refuse.

    Raises:
        ToolError("outside_workspace"): target escapes the workspace.
        ToolError("overwrite_requires_confirmation"): target exists, no overwrite.
    """
    target = resolve_in_workspace(workspace_root, path)

    if target.exists() and not overwrite:
        raise ToolError(
            "overwrite_requires_confirmation",
            f"{target} already exists. Re-invoke with overwrite=True to replace it.",
        )

    return target


# --------------------------------------------------------------------------- #
# Filesystem-bound tools
# --------------------------------------------------------------------------- #

def list_workspace_files(workspace_root: Path | str) -> dict[str, Any]:
    """List user files in the workspace folder (excludes the .stet/ namespace).

    Returns a dict: ``{"files": [{"name", "path", "type", "size_bytes"}], "count"}``
    where ``path`` is workspace-relative (POSIX). Recurses into subfolders.
    """
    root = Path(workspace_root)
    if not root.is_dir():
        raise ToolError("not_found", f"Workspace folder not found: {root}")

    files: list[dict[str, Any]] = []
    for entry in sorted(root.rglob("*")):
        if not entry.is_file():
            continue
        rel = entry.relative_to(root)
        if RESERVED_DIR in rel.parts:
            continue
        suffix = entry.suffix.lower().lstrip(".")
        files.append({
            "name": entry.name,
            "path": rel.as_posix(),
            "type": suffix or "unknown",
            "size_bytes": entry.stat().st_size,
        })

    return {"files": files, "count": len(files)}


def read_document(path: Path | str) -> dict[str, Any]:
    """Parse a docx and return a summary (no content body).

    Returns ``{"path", "paragraph_count", "comment_count", "thread_count",
    "revision_count", "title", "author"}``.
    """
    docx_path = Path(path)
    if not docx_path.is_file():
        raise ToolError("not_found", f"Document not found: {docx_path}")
    try:
        model = parse_docx(docx_path)
    except Exception as exc:  # noqa: BLE001 - surface parse failures as ToolError
        raise ToolError("parse_failed", f"Could not parse document: {exc}") from exc

    props = model.properties
    return {
        "path": str(docx_path),
        "paragraph_count": model.paragraph_count,
        "comment_count": model.comment_count,
        "thread_count": model.thread_count,
        "revision_count": model.revision_count,
        "title": props.title,
        "author": props.author,
    }


def _read_text_file(file_path: Path) -> str:
    """Read a plain-text file with an encoding fallback + truncation guard."""
    raw = file_path.read_bytes()
    text = None
    for encoding in _TEXT_ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except Exception:  # noqa: BLE001 - try the next encoding
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    if len(text) > _TEXT_MAX_CHARS:
        text = text[:_TEXT_MAX_CHARS] + _TEXT_TRUNCATION_MARKER
    return text


def read_file(path: Path | str) -> dict[str, Any]:
    """Read a reference file and return its extracted text.

    Dispatches by extension to the ``file_parsers`` (PDF, XLSX/XLS/CSV, DOCX,
    RTF, PPTX) or an inline plain-text reader (TXT/MD). Returns
    ``{"path", "file_type", "content", "meta"}``.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise ToolError("not_found", f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    file_type = suffix.lstrip(".") or "unknown"

    if suffix in _PDF_EXTS:
        from src.file_parsers import PDFParser
        parser = PDFParser()
        result = parser.parse(str(file_path))
        return {
            "path": str(file_path),
            "file_type": file_type,
            "content": result.to_markdown(),
            "meta": {"page_count": parser.get_page_count(str(file_path))},
        }

    if suffix in _SPREADSHEET_EXTS:
        from src.file_parsers import SpreadsheetParser
        parser = SpreadsheetParser()
        result = parser.parse(str(file_path))
        if result.error:
            raise ToolError("parse_failed", result.error)
        return {
            "path": str(file_path),
            "file_type": file_type,
            "content": result.to_markdown(),
            "meta": {
                "sheet_count": result.sheet_count,
                "sheet_names": [s.name for s in result.sheets],
            },
        }

    if suffix in _DOCX_EXTS:
        from src.file_parsers import DocxParser
        parser = DocxParser()
        result = parser.parse(str(file_path))
        if result.error:
            raise ToolError("parse_failed", result.error)
        return {
            "path": str(file_path),
            "file_type": file_type,
            "content": result.to_markdown(),
            "meta": {
                "paragraph_count": result.paragraph_count,
                "table_count": result.table_count,
            },
        }

    if suffix in _RTF_EXTS:
        from src.file_parsers import RtfParser
        parser = RtfParser()
        result = parser.parse(str(file_path))
        if result.error:
            raise ToolError("parse_failed", result.error)
        return {
            "path": str(file_path),
            "file_type": file_type,
            "content": result.to_markdown(),
            "meta": {"char_count": len(result.text)},
        }

    if suffix in _PPTX_EXTS:
        from src.file_parsers import PptxParser
        parser = PptxParser()
        result = parser.parse(str(file_path))
        if result.error:
            raise ToolError("parse_failed", result.error)
        return {
            "path": str(file_path),
            "file_type": file_type,
            "content": result.to_markdown(),
            "meta": {
                "slide_count": result.slide_count,
                "total_slides": result.total_slides,
            },
        }

    if suffix in _TEXT_EXTS:
        content = _read_text_file(file_path)
        return {
            "path": str(file_path),
            "file_type": file_type,
            "content": content,
            "meta": {"line_count": content.count("\n") + 1 if content else 0},
        }

    raise ToolError(
        "unsupported_format",
        f"Unsupported file type '{suffix}'. "
        "Supported: pdf, xlsx, xls, csv, docx, rtf, pptx, txt, md.",
    )


def create_document(
    path: Path | str,
    workspace_root: Path | str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a new blank docx from the bundled template (guarded).

    The target must lie inside ``workspace_root`` and must not exist unless
    ``overwrite=True``.
    """
    if not TEMPLATE_PATH.is_file():
        raise ToolError("template_missing", f"Blank template not found: {TEMPLATE_PATH}")
    target = _guard_write_target(path, workspace_root, overwrite)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE_PATH, target)
    return {"path": str(target), "created": True}


# --------------------------------------------------------------------------- #
# Document-bound tools
# --------------------------------------------------------------------------- #

def list_comments(model: DocumentModel, comment_filter: str = "open") -> dict[str, Any]:
    """List comment threads, optionally filtered by status.

    ``comment_filter`` is one of ``"all"``, ``"open"``, ``"resolved"``.
    """
    if comment_filter not in ("all", "open", "resolved"):
        raise ToolError(
            "invalid_argument",
            f"comment_filter must be 'all', 'open', or 'resolved' (got '{comment_filter}').",
        )

    threads_out: list[dict[str, Any]] = []
    for thread in model.comments.threads.values():
        resolved = thread.is_resolved
        if comment_filter == "open" and resolved:
            continue
        if comment_filter == "resolved" and not resolved:
            continue

        referenced_text = ""
        root_anchor = thread.root.anchor
        if root_anchor:
            para = model.get_paragraph(root_anchor.para_id)
            if para:
                raw = para.raw_text
                referenced_text = raw[root_anchor.start_offset:root_anchor.end_offset]

        threads_out.append({
            "thread_id": thread.thread_id,
            "root_comment_id": thread.root.comment_id,
            "status": "resolved" if resolved else "open",
            "author": thread.root.author,
            "referenced_text": referenced_text,
            "comment_count": len(thread.all_comments),
            "comments": [
                {
                    "comment_id": c.comment_id,
                    "author": c.author,
                    "text": c.text,
                    "is_reply": c.is_reply,
                }
                for c in thread.all_comments
            ],
        })

    return {"threads": threads_out, "count": len(threads_out)}


def find_in_document(
    model: DocumentModel, query: str, max_results: int = 10
) -> dict[str, Any]:
    """Find paragraphs whose text contains ``query`` (the para_id discovery tool).

    Matching is case-insensitive and whitespace-normalized, so a sentence pasted
    from the document matches even when spacing differs. Returns paragraphs in
    document order with their ``para_id`` so the caller can then ``read_paragraph``
    or ``edit_paragraph``.

    Returns ``{"query", "matches": [{"para_id", "text", "style"}], "count",
    "truncated"}``.
    """
    if not query or not query.strip():
        raise ToolError("invalid_argument", "query must be a non-empty string.")
    if max_results < 1:
        raise ToolError("invalid_argument", "max_results must be >= 1.")

    needle = _normalize_ws(query)
    matches: list[dict[str, Any]] = []
    total = 0
    for para in model.body.iter_paragraphs():
        if needle in _normalize_ws(para.plain_text):
            total += 1
            if len(matches) < max_results:
                matches.append(
                    {
                        "para_id": para.para_id,
                        "text": para.plain_text,
                        "style": para.style_id,
                    }
                )

    return {
        "query": query,
        "matches": matches,
        "count": total,
        "truncated": total > len(matches),
    }


def read_paragraph(model: DocumentModel, para_id: str) -> dict[str, Any]:
    """Return a paragraph's text, style, formatting summary, comments, revisions."""
    para = model.get_paragraph(para_id)
    if para is None:
        raise ToolError("not_found", f"Paragraph not found: {para_id}")

    formatting_summary = {
        "bold": any(r.formatting.bold for r in para.runs),
        "italic": any(r.formatting.italic for r in para.runs),
        "underline": any(r.formatting.underline for r in para.runs),
        "superscript": any(r.formatting.superscript for r in para.runs),
        "subscript": any(r.formatting.subscript for r in para.runs),
    }

    comment_ids = [
        c.comment_id
        for c in model.comments.comments.values()
        if c.anchor and c.anchor.para_id == para_id
    ]

    has_revisions = bool(model.revisions.get_revisions_in_paragraph(para_id))

    return {
        "para_id": para_id,
        "text": para.plain_text,
        "display_text": para.raw_text,
        "style": para.style_id,
        "formatting_summary": formatting_summary,
        "comment_ids": comment_ids,
        "has_revisions": has_revisions,
    }


def edit_paragraph(
    model: DocumentModel,
    para_id: str,
    new_text: str,
    track_changes: bool = True,
    author: str = DEFAULT_AUTHOR,
    addresses_thread_id: str | None = None,
) -> dict[str, Any]:
    """Replace a paragraph's text via the unified plain-text revision path.

    Wraps ``apply_revision_from_plain_text``, which handles diffing, paragraph
    splits/merges, and field-code preservation. ``track_changes=True`` records
    tracked changes; ``False`` applies a plain edit.

    M9e:
    - **Citation visibility (Layer A).** Any ``[CITATION_n]`` placeholder present
      on the original paragraph but absent from ``new_text`` is reported in
      ``removed_citations``. Removal is *allowed* (a legitimate edit can delete a
      cited sentence); the serializer guarantees a valid document either way. The
      report makes accidental drops visible in the run transcript/QA.
    - **Numeric-range dash repair.** En dashes the model dropped from numeric
      ranges are restored before applying (digit–digit only).
    - **Comment linkage.** ``addresses_thread_id`` records that this edit was made
      to address a specific comment thread; set it only for comment-driven edits.
    """
    paragraph = model.get_paragraph(para_id)
    if paragraph is None:
        raise ToolError("not_found", f"Paragraph not found: {para_id}")

    original_text = paragraph.plain_text

    if addresses_thread_id is not None and model.get_thread(addresses_thread_id) is None:
        raise ToolError(
            "not_found", f"Comment thread not found: {addresses_thread_id}"
        )

    # Layer A: which citation placeholders did the revision drop?
    removed_citations = sorted(
        ph for ph in (paragraph.field_codes or {}) if ph not in new_text
    )

    # Restore en dashes dropped from numeric ranges (bounded to digit–digit).
    new_text, restored_ranges = _restore_numeric_range_dashes(original_text, new_text)

    edits = apply_revision_from_plain_text(
        model,
        [para_id],
        new_text,
        author=author,
        track_changes=track_changes,
    )
    result: dict[str, Any] = {
        "para_id": para_id,
        "applied": True,
        "edit_count": len(edits),
        "track_changes": track_changes,
        "author": author,
    }
    if removed_citations:
        result["removed_citations"] = removed_citations
    if restored_ranges:
        result["restored_ranges"] = restored_ranges
    if addresses_thread_id is not None:
        result["addresses_thread_id"] = addresses_thread_id
    return result


def add_comment_reply(
    model: DocumentModel,
    thread_id: str,
    text: str,
    author: str = DEFAULT_AUTHOR,
) -> dict[str, Any]:
    """Add a reply to an existing comment thread.

    ``thread_id`` is the root comment's id (flat threading); the reply attaches
    to the thread root.
    """
    thread = model.get_thread(thread_id)
    if thread is None:
        raise ToolError("not_found", f"Comment thread not found: {thread_id}")

    reply = model.add_reply(
        parent_comment_id=thread.root.comment_id,
        text=text,
        author=author,
    )
    if reply is None:
        raise ToolError("reply_failed", f"Could not add reply to thread {thread_id}.")

    return {
        "comment_id": reply.comment_id,
        "thread_id": thread_id,
        "author": author,
    }


def add_comment(
    model: DocumentModel,
    para_id: str,
    start: int,
    end: int,
    text: str,
    author: str = DEFAULT_AUTHOR,
) -> dict[str, Any]:
    """Add a new root comment anchored to a [start, end) range in a paragraph.

    Creates a single-comment thread; ``thread_id`` equals the new comment's id.
    """
    try:
        comment = model.add_comment(
            para_id=para_id,
            start=start,
            end=end,
            text=text,
            author=author,
        )
    except ValueError as exc:
        raise ToolError("invalid_argument", str(exc)) from exc

    return {
        "comment_id": comment.comment_id,
        "thread_id": comment.comment_id,
        "para_id": para_id,
        "start": start,
        "end": end,
    }


def remove_comment(model: DocumentModel, comment_id: str) -> dict[str, Any]:
    """Remove a comment. A root removes its whole thread; a reply removes itself."""
    removed = model.remove_comment(comment_id)
    if not removed:
        raise ToolError("not_found", f"Comment not found: {comment_id}")
    return {"removed": True, "comment_id": comment_id}


def export_document(
    model: DocumentModel,
    path: Path | str,
    workspace_root: Path | str,
    include_track_changes: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Serialize the in-memory model to a docx (guarded).

    The target must lie inside ``workspace_root`` and must not exist unless
    ``overwrite=True``.
    """
    output_path = _guard_write_target(path, workspace_root, overwrite)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    DocumentSerializer().serialize(
        model=model,
        output_path=output_path,
        include_track_changes=include_track_changes,
    )
    return {"path": str(output_path), "include_track_changes": include_track_changes}
