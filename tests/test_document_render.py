"""Unit tests for the workspace document renderer (Stage 1, Milestone 6a).

Pure Python: builds ``DocumentModel`` fixtures directly and asserts on the
``render_document`` output (block separation, inline track changes, comment
boundary segmentation incl. overlap + cross-paragraph, tables, escaping).
"""

from src.document_model.model import DocumentModel, Table
from src.document_model.paragraph import Paragraph, Run, RevisionType
from src.document_model.comments import Comment, CommentAnchor
from src.workspace.render import render_document


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #

def _para(para_id, *runs, style=None):
    return Paragraph(para_id=para_id, text_id=f"t{para_id}", runs=list(runs), style_id=style)


def _run(text, *, inserted=False, deleted=False, **fmt):
    rev = None
    if inserted:
        rev = RevisionType.INSERTION
    elif deleted:
        rev = RevisionType.DELETION
    from src.document_model.paragraph import RunFormatting

    return Run(text=text, formatting=RunFormatting(**fmt), revision_type=rev)


def _model(*paragraphs):
    model = DocumentModel()
    for p in paragraphs:
        model.body.add_element(p)
    return model


def _add_comment(model, comment_id, para_id, start, end, *, end_para_id=None, resolved=False):
    anchor = CommentAnchor(
        comment_id=comment_id,
        para_id=para_id,
        start_offset=start,
        end_offset=end,
        end_para_id=end_para_id,
    )
    comment = Comment(
        comment_id=comment_id,
        para_id=f"c{comment_id}",
        text=f"comment {comment_id}",
        author="Reviewer",
        is_resolved=resolved,
        anchor=anchor,
    )
    model.comments.add_comment(comment)
    return comment


# --------------------------------------------------------------------------- #
# Block structure
# --------------------------------------------------------------------------- #

class TestBlockStructure:
    def test_each_paragraph_is_its_own_block(self):
        model = _model(_para("p1", _run("First.")), _para("p2", _run("Second.")))
        blocks = render_document(model)
        assert [b.kind for b in blocks] == ["paragraph", "paragraph"]
        assert blocks[0].para_id == "p1" and "First." in blocks[0].html
        assert blocks[1].para_id == "p2" and "Second." in blocks[1].html

    def test_empty_paragraph_still_emits_a_block(self):
        model = _model(_para("p1", _run("Text.")), _para("p2"), _para("p3", _run("More.")))
        blocks = render_document(model)
        assert len(blocks) == 3
        assert blocks[1].para_id == "p2"
        assert blocks[1].html == ""  # empty, JS/CSS preserves the blank line

    def test_style_and_text_carried(self):
        model = _model(_para("p1", _run("Heading"), style="Heading1"))
        block = render_document(model)[0]
        assert block.style == "Heading1"
        assert block.text == "Heading"

    def test_to_dict_shape(self):
        model = _model(_para("p1", _run("x")))
        d = render_document(model)[0].to_dict()
        assert {"kind", "para_id", "html", "text", "style", "comment_ids"} <= set(d.keys())
        assert "cells" not in d  # only table rows carry cells

    def test_html_is_escaped(self):
        model = _model(_para("p1", _run("a <b> & c")))
        html = render_document(model)[0].html
        assert "&lt;b&gt;" in html and "&amp;" in html
        assert "<b>" not in html


# --------------------------------------------------------------------------- #
# Track changes
# --------------------------------------------------------------------------- #

class TestTrackChanges:
    def test_inserted_run_highlighted(self):
        model = _model(_para("p1", _run("keep "), _run("added", inserted=True)))
        html = render_document(model)[0].html
        assert '<ins class="diff-insert">added</ins>' in html

    def test_deleted_run_struck_not_dropped(self):
        model = _model(_para("p1", _run("keep "), _run("gone", deleted=True)))
        html = render_document(model)[0].html
        assert '<del class="diff-delete">gone</del>' in html  # present, not dropped

    def test_soft_break_newline_renders_as_br(self):
        model = _model(_para("p1", _run("line1\nline2")))
        html = render_document(model)[0].html
        assert "line1<br>line2" in html


# --------------------------------------------------------------------------- #
# Comments (boundary segmentation)
# --------------------------------------------------------------------------- #

class TestComments:
    def test_single_comment_span(self):
        model = _model(_para("p1", _run("Hello world")))
        _add_comment(model, "1", "p1", 0, 5)  # "Hello"
        block = render_document(model)[0]
        assert block.comment_ids == ["1"]
        assert '<span class="ws-comment-ref" data-comment-ids="1">Hello</span>' in block.html
        assert "world" in block.html  # uncovered tail rendered plainly

    def test_overlapping_comments_share_segment(self):
        model = _model(_para("p1", _run("0123456789")))
        _add_comment(model, "1", "p1", 0, 6)
        _add_comment(model, "2", "p1", 4, 10)
        block = render_document(model)[0]
        assert set(block.comment_ids) == {"1", "2"}
        # The overlap region [4,6) carries both ids.
        assert 'data-comment-ids="1 2"' in block.html

    def test_cross_paragraph_anchor_covers_both_ends_and_middle(self):
        model = _model(_para("p1", _run("AAAA")), _para("p2", _run("MMMM")), _para("p3", _run("ZZZZ")))
        _add_comment(model, "5", "p1", 1, 3, end_para_id="p3")
        blocks = {b.para_id: b for b in render_document(model)}
        assert "5" in blocks["p1"].comment_ids  # head
        assert "5" in blocks["p2"].comment_ids  # middle paragraph fully covered
        assert "5" in blocks["p3"].comment_ids  # tail
        assert "ws-comment-ref" in blocks["p2"].html
        assert '<span class="ws-comment-ref" data-comment-ids="5">MMMM</span>' in blocks["p2"].html

    def test_resolved_status_does_not_block_rendering(self):
        model = _model(_para("p1", _run("Hello world")))
        _add_comment(model, "1", "p1", 0, 5, resolved=True)
        block = render_document(model)[0]
        assert block.comment_ids == ["1"]  # still anchored/highlighted; JS styles resolved


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #

class TestTables:
    def test_table_renders_one_block_per_row_with_cells(self):
        row1 = [_para("r1c1", _run("Name")), _para("r1c2", _run("Value"))]
        row2 = [_para("r2c1", _run("Age")), _para("r2c2", _run("42"))]
        table = Table(rows=[row1, row2])
        model = DocumentModel()
        model.body.add_element(table)
        blocks = render_document(model)
        assert [b.kind for b in blocks] == ["table_row", "table_row"]
        assert blocks[0].para_id == "r1c1"
        assert len(blocks[0].cells) == 2
        assert "ws-cell" in blocks[0].html
        assert "Name" in blocks[0].html and "Value" in blocks[0].html
        assert blocks[1].text == "Age | 42"

    def test_paragraphs_and_tables_keep_document_order(self):
        para_a = _para("p1", _run("Intro"))
        table = Table(rows=[[_para("r1c1", _run("cell"))]])
        para_b = _para("p2", _run("Outro"))
        model = DocumentModel()
        for el in (para_a, table, para_b):
            model.body.add_element(el)
        kinds = [b.kind for b in render_document(model)]
        assert kinds == ["paragraph", "table_row", "paragraph"]


class TestPendingRevisionDiff:
    def test_in_session_edit_renders_ins_del_from_revision_store(self):
        from src.agent.tools import edit_paragraph

        model = _model(_para("p1", _run("Hello world")))
        edit_paragraph(model, "p1", "Hello there", track_changes=True)
        html = render_document(model)[0].html
        assert 'class="diff-delete"' in html
        assert 'class="diff-insert"' in html
        assert "Hello" in html
