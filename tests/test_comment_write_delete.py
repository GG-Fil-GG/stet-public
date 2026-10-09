"""Add/remove anchored comments and serializer round-trip (Stage 1, Milestone 2).

Pure-Python: parses the committed synthetic fixture, mutates the model through
the public `DocumentModel` API, exports via the serializer, and reparses to
prove the anchors/comments survive (or are removed) correctly.

Fixture facts (test_data/synthetic/test.docx):
- 4685B513  "Methods: ..."     — clean paragraph, no existing comment.
- 47BAD27B  "Discussion: ..."  — contains a field code / citation (the
  known-risk case); already carries thread "5" at [12, 245).
- thread "3" — a root thread anchored in 0ACFE22E.
"""

import zipfile

import pytest

from src.document_model import parse_docx
from src.agent import tools
from src.agent import ToolError
from tests.test_support import TEST_DOCX

CLEAN_PARA = "4685B513"
FIELD_CODE_PARA = "47BAD27B"


def _model():
    return parse_docx(TEST_DOCX)


def _export_reparse(model, temp_dir):
    out = temp_dir / "roundtrip.docx"
    tools.export_document(model, out, workspace_root=temp_dir)
    return parse_docx(out), out


def _reparsed_segment(reparsed, comment_id):
    """Return the highlighted text for a comment's anchor after reparse."""
    for thread in reparsed.comments.threads.values():
        if thread.root.comment_id == comment_id:
            anchor = thread.root.anchor
            assert anchor is not None, "Reparsed root comment lost its anchor"
            para = reparsed.get_paragraph(anchor.para_id)
            return para.raw_text[anchor.start_offset:anchor.end_offset]
    return None


# --------------------------------------------------------------------------- #
# add_comment — precise-range proof
# --------------------------------------------------------------------------- #

class TestAddCommentPreciseRange:
    def test_clean_range_roundtrips_exactly(self, temp_dir):
        model = _model()
        raw = model.get_paragraph(CLEAN_PARA).raw_text
        start, end = 9, 40
        intended = raw[start:end]
        result = tools.add_comment(model, CLEAN_PARA, start, end, "Note on methods.")

        reparsed, _ = _export_reparse(model, temp_dir)
        assert result["comment_id"] in reparsed.comments.comments
        assert _reparsed_segment(reparsed, result["comment_id"]) == intended

    def test_range_at_paragraph_start(self, temp_dir):
        model = _model()
        raw = model.get_paragraph(CLEAN_PARA).raw_text
        intended = raw[0:7]
        result = tools.add_comment(model, CLEAN_PARA, 0, 7, "Heading note.")

        reparsed, _ = _export_reparse(model, temp_dir)
        assert _reparsed_segment(reparsed, result["comment_id"]) == intended

    def test_whole_paragraph_range(self, temp_dir):
        model = _model()
        raw = model.get_paragraph(CLEAN_PARA).raw_text
        result = tools.add_comment(model, CLEAN_PARA, 0, len(raw), "Whole paragraph.")

        reparsed, _ = _export_reparse(model, temp_dir)
        assert _reparsed_segment(reparsed, result["comment_id"]) == raw

    def test_mid_run_range_splits_correctly(self, temp_dir):
        # Start and end both fall inside text (forces run splitting on both ends).
        model = _model()
        raw = model.get_paragraph(CLEAN_PARA).raw_text
        start, end = 14, len(raw) - 10
        intended = raw[start:end]
        result = tools.add_comment(model, CLEAN_PARA, start, end, "Mid-run span.")

        reparsed, _ = _export_reparse(model, temp_dir)
        assert _reparsed_segment(reparsed, result["comment_id"]) == intended


class TestAddCommentFieldCodeParagraph:
    """The known-risk case: anchoring inside a paragraph with a field code."""

    def test_field_code_prefix_range(self, temp_dir):
        model = _model()
        raw = model.get_paragraph(FIELD_CODE_PARA).raw_text
        intended = raw[0:10]
        result = tools.add_comment(model, FIELD_CODE_PARA, 0, 10, "Discussion note.")

        reparsed, _ = _export_reparse(model, temp_dir)
        assert _reparsed_segment(reparsed, result["comment_id"]) == intended

    def test_field_code_spanning_range(self, temp_dir):
        # Span across the body that includes the citation marker.
        model = _model()
        raw = model.get_paragraph(FIELD_CODE_PARA).raw_text
        start, end = 12, 245
        intended = raw[start:end]
        result = tools.add_comment(model, FIELD_CODE_PARA, start, end, "Citation span.")

        reparsed, _ = _export_reparse(model, temp_dir)
        assert _reparsed_segment(reparsed, result["comment_id"]) == intended


# --------------------------------------------------------------------------- #
# remove_comment
# --------------------------------------------------------------------------- #

class TestRemoveComment:
    def test_remove_root_strips_thread_and_anchors(self, temp_dir):
        model = _model()
        thread_id = "3"
        assert thread_id in model.comments.threads
        before = model.comment_count

        tools.remove_comment(model, thread_id)
        assert thread_id not in model.comments.threads
        assert model.comment_count == before - 1

        reparsed, out = _export_reparse(model, temp_dir)
        assert thread_id not in reparsed.comments.threads
        assert thread_id not in reparsed.comments.comments

        with zipfile.ZipFile(out) as zf:
            doc = zf.read("word/document.xml").decode("utf-8")
            comments = zf.read("word/comments.xml").decode("utf-8")
        assert f'w:commentRangeStart w:id="{thread_id}"' not in doc
        assert f'w:commentRangeEnd w:id="{thread_id}"' not in doc
        assert f'w:comment w:id="{thread_id}"' not in comments

    def test_remove_reply_keeps_thread(self):
        model = _model()
        thread_id = next(iter(model.comments.threads))
        root_id = model.comments.threads[thread_id].root.comment_id
        reply = model.add_reply(parent_comment_id=root_id, text="temp reply", author="Stet")
        assert model.get_thread(thread_id).reply_count == 1

        removed = model.remove_comment(reply.comment_id)
        assert removed is True
        assert model.get_thread(thread_id).reply_count == 0
        assert thread_id in model.comments.threads

    def test_remove_unknown_returns_false(self):
        model = _model()
        assert model.remove_comment("no_such_comment") is False

    def test_remove_comment_tool_unknown_raises(self):
        with pytest.raises(ToolError) as exc:
            tools.remove_comment(_model(), "no_such_comment")
        assert exc.value.code == "not_found"


# --------------------------------------------------------------------------- #
# add_comment validation
# --------------------------------------------------------------------------- #

class TestAddCommentValidation:
    def test_invalid_range_raises(self):
        model = _model()
        with pytest.raises(ValueError):
            model.add_comment(CLEAN_PARA, 5, 2, text="bad", author="Stet")

    def test_unknown_paragraph_raises(self):
        model = _model()
        with pytest.raises(ValueError):
            model.add_comment("DEADBEEF", 0, 1, text="x", author="Stet")

    def test_out_of_bounds_raises(self):
        model = _model()
        raw_len = len(model.get_paragraph(CLEAN_PARA).raw_text)
        with pytest.raises(ValueError):
            model.add_comment(CLEAN_PARA, 0, raw_len + 5, text="x", author="Stet")
