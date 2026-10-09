"""Document rendering for the agentic workspace (Stage 1, Milestone 6a).

Pure ``DocumentModel`` → ordered render :class:`Block` list. Unlike
``Paragraph.to_display_html`` (which drops deleted runs, doesn't mark inserted
runs, emits no block wrapper, and ignores comments), this renderer is
track-change- and comment-aware:

- each body paragraph becomes its own block (fixes the M5 "everything on one
  line" issue, where inline HTML was concatenated with no separators);
- inserted runs are wrapped in ``<ins class="diff-insert">`` and deleted runs
  in ``<del class="diff-delete">`` (reusing the card UI's CSS colour language);
- anchored comment ranges are wrapped in ``<span class="ws-comment-ref"
  data-comment-ids="…">`` via boundary segmentation, so overlapping and
  cross-paragraph anchors render correctly (space-joined ids avoid illegal
  overlapping tags);
- tables become one ``table_row`` block per row, rendered legibly (distinct
  cells) rather than as run-on text.

The renderer is pure (no I/O, no session state) and unit-tested directly
against ``DocumentModel`` fixtures.

Note: true Word soft breaks (``<w:br/>``) are not preserved by the parser today
(it captures only ``<w:t>`` text), so they are not rendered here; that requires
parser + serializer support and is deferred (see the M6a report). Any newline
already present in run text is rendered as ``<br>`` defensively.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.diff_core import DiffOperation, compute_diff
from src.document_model.model import DocumentModel, Table
from src.document_model.paragraph import Paragraph, RevisionType, Run


# --------------------------------------------------------------------------- #
# Block
# --------------------------------------------------------------------------- #

@dataclass
class Block:
    """One rendered unit of the document, in document order.

    ``kind`` is ``"paragraph"`` or ``"table_row"``. ``comment_ids`` are the
    thread ids (root comment ids) whose anchor touches this block. ``cells`` is
    only populated for ``table_row`` blocks.
    """

    kind: str
    para_id: str
    html: str
    text: str
    style: Optional[str] = None
    comment_ids: list[str] = field(default_factory=list)
    cells: Optional[list[dict]] = None

    def to_dict(self) -> dict:
        data = {
            "kind": self.kind,
            "para_id": self.para_id,
            "html": self.html,
            "text": self.text,
            "style": self.style,
            "comment_ids": self.comment_ids,
        }
        if self.cells is not None:
            data["cells"] = self.cells
        return data


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def render_document(model: DocumentModel) -> list[Block]:
    """Render ``model`` into an ordered list of :class:`Block`."""
    order = {para.para_id: i for i, para in enumerate(model.body.iter_paragraphs())}
    intervals = _collect_comment_intervals(model, order)

    blocks: list[Block] = []
    for element in model.body.elements:
        if isinstance(element, Table):
            blocks.extend(_render_table(element, intervals, model))
        else:  # Paragraph
            blocks.append(
                _render_paragraph(element, intervals.get(element.para_id, []), model)
            )
    return blocks


# --------------------------------------------------------------------------- #
# Comment anchor intervals (boundary segmentation source data)
# --------------------------------------------------------------------------- #

# (start_offset, end_offset, comment_id) in a paragraph's raw-text space.
Interval = tuple[int, int, str]


def _collect_comment_intervals(
    model: DocumentModel, order: dict[str, int]
) -> dict[str, list[Interval]]:
    """Map para_id → comment intervals, splitting cross-paragraph anchors.

    A single-paragraph anchor contributes one interval to its paragraph. A
    cross-paragraph anchor contributes a head (start paragraph), a tail (end
    paragraph), and full-width coverage to any paragraphs strictly between them.
    Offsets are clamped to each paragraph's raw-text length.
    """
    result: dict[str, list[Interval]] = {}

    def add(pid: str, start: int, end: int, cid: str) -> None:
        if end <= start:
            return
        result.setdefault(pid, []).append((start, end, cid))

    for comment in model.comments.comments.values():
        anchor = comment.anchor
        if not anchor:
            continue
        cid = anchor.comment_id  # == root comment id == thread id

        if not anchor.spans_paragraphs:
            para = model.get_paragraph(anchor.para_id)
            if para is None:
                continue
            n = len(para.raw_text)
            add(anchor.para_id, _clamp(anchor.start_offset, n), _clamp(anchor.end_offset, n), cid)
            continue

        # Cross-paragraph anchor.
        start_para = model.get_paragraph(anchor.para_id)
        if start_para is not None:
            n = len(start_para.raw_text)
            add(anchor.para_id, _clamp(anchor.start_offset, n), n, cid)

        end_para = model.get_paragraph(anchor.end_para_id) if anchor.end_para_id else None
        if end_para is not None:
            n = len(end_para.raw_text)
            add(anchor.end_para_id, 0, _clamp(anchor.end_offset, n), cid)

        si = order.get(anchor.para_id)
        ei = order.get(anchor.end_para_id)
        if si is not None and ei is not None and ei > si + 1:
            for pid, idx in order.items():
                if si < idx < ei:
                    mid = model.get_paragraph(pid)
                    if mid is not None:
                        add(pid, 0, len(mid.raw_text), cid)

    return result


def _clamp(value: int, length: int) -> int:
    return max(0, min(value, length))


# --------------------------------------------------------------------------- #
# Paragraph / table rendering
# --------------------------------------------------------------------------- #

def _render_paragraph(para: Paragraph, intervals: list[Interval], model: DocumentModel) -> Block:
    return Block(
        kind="paragraph",
        para_id=para.para_id,
        html=_render_paragraph_html(para, intervals, model),
        text=para.plain_text,
        style=para.style_id,
        comment_ids=_unique_ids(intervals),
    )


def _render_paragraph_html(para: Paragraph, intervals: list[Interval], model: DocumentModel) -> str:
    """Render one paragraph, preferring run markup then in-session revision diffs."""
    rev_html = _render_pending_revision_diff(para, model)
    if rev_html is not None:
        return rev_html
    return _render_runs(para, intervals)


def _render_pending_revision_diff(para: Paragraph, model: DocumentModel) -> str | None:
    """Show in-session tracked edits (RevisionStore) as ins/del markup.

    ``edit_paragraph`` records pending insertions/deletions in the store while
    rewriting runs to the result text, so run markup alone cannot show them.
    Diff the earliest pending deletion baseline against current ``plain_text``.
    """
    pending = [
        r for r in model.revisions.get_revisions_in_paragraph(para.para_id) if r.is_pending
    ]
    if not pending:
        return None
    deletions = [r for r in pending if r.revision_type == RevisionType.DELETION]
    if not deletions:
        return None
    original = min(deletions, key=lambda r: (r.timestamp or datetime.min, r.start_offset)).text
    revised = para.plain_text
    if original == revised:
        return None
    return _diff_to_track_html(compute_diff(original, revised))


def _diff_to_track_html(result) -> str:
    """Word-style track-change classes for a computed diff."""
    parts: list[str] = []
    for op in result.operations:
        text = html.escape(op.text, quote=False).replace("\n", "<br>")
        if op.op == DiffOperation.EQUAL:
            parts.append(text)
        elif op.op == DiffOperation.DELETE:
            parts.append(f'<del class="diff-delete">{text}</del>')
        elif op.op == DiffOperation.INSERT:
            parts.append(f'<ins class="diff-insert">{text}</ins>')
    return "".join(parts)


def _render_table(table: Table, intervals: dict[str, list[Interval]], model: DocumentModel) -> list[Block]:
    blocks: list[Block] = []
    for row in table.rows:
        cells: list[dict] = []
        cell_html: list[str] = []
        texts: list[str] = []
        row_ids: list[str] = []
        for cell in row:  # each cell is a Paragraph
            cell_intervals = intervals.get(cell.para_id, [])
            html = _render_paragraph_html(cell, cell_intervals, model)
            cells.append({"para_id": cell.para_id, "html": html})
            cell_html.append(f'<span class="ws-cell">{html}</span>')
            texts.append(cell.plain_text)
            row_ids.extend(_unique_ids(cell_intervals))
        blocks.append(
            Block(
                kind="table_row",
                para_id=row[0].para_id if row else "",
                html="".join(cell_html),
                text=" | ".join(texts),
                style=None,
                comment_ids=_dedupe(row_ids),
                cells=cells,
            )
        )
    return blocks


def _render_runs(para: Paragraph, intervals: list[Interval]) -> str:
    """Render a paragraph's runs to inline HTML (track changes + comment spans).

    Walks runs in order, tracking the character offset in raw-text space (which
    matches comment anchor offsets). Deleted runs are struck through and do not
    advance the offset (they are not part of raw text). Live runs are split at
    comment boundaries that fall inside them.
    """
    parts: list[str] = []
    offset = 0
    for run in para.runs:
        if run.is_deleted():
            parts.append(f'<del class="diff-delete">{_format_run(run, run.text)}</del>')
            continue
        parts.append(_render_live_run(run, offset, offset + len(run.text), intervals))
        offset += len(run.text)

    html = "".join(parts)
    # Convert any field-code placeholders ([CITATION_x]) to their display text.
    if para.field_codes:
        html = para.get_display_text(html)
    return html


def _render_live_run(run: Run, start: int, end: int, intervals: list[Interval]) -> str:
    """Render one non-deleted run, segmenting at comment boundaries within it."""
    cuts = {start, end}
    for s, e, _cid in intervals:
        if start < s < end:
            cuts.add(s)
        if start < e < end:
            cuts.add(e)
    points = sorted(cuts)

    out: list[str] = []
    for a, b in zip(points, points[1:]):
        seg_text = run.text[a - start:b - start]
        if not seg_text:
            continue
        ids = _dedupe([cid for s, e, cid in intervals if s <= a and b <= e])
        frag = _format_run(run, seg_text)
        if run.is_inserted():
            frag = f'<ins class="diff-insert">{frag}</ins>'
        if ids:
            frag = (
                f'<span class="ws-comment-ref" data-comment-ids="{" ".join(ids)}">'
                f"{frag}</span>"
            )
        out.append(frag)
    return "".join(out)


def _format_run(run: Run, text: str) -> str:
    """Escape + apply run formatting; render embedded newlines as ``<br>``."""
    segments = text.split("\n")
    html = "<br>".join(run.formatting.to_html(seg) for seg in segments)
    return html


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _unique_ids(intervals: list[Interval]) -> list[str]:
    return _dedupe([cid for _s, _e, cid in intervals])


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
