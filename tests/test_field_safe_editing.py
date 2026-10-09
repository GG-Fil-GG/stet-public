"""M9e: field-safe editing, dash repair, and comment-reply behaviour.

Covers the M9d re-pilot findings:
- #1 editing a citation-bearing paragraph must never produce an unopenable
  document (serialize-time balance safety net), while allowing citation removal;
- #2 en dashes dropped from numeric ranges are restored (bounded to digit–digit);
- #3 edit_paragraph carries an optional comment-thread linkage.

Uses ``citation_field.docx`` — a synthetic fixture with EndNote-style fields
(fldChar/instrText/fldData) plus an en-dash year range — added in M9e because
earlier fixtures had no field codes and so never exercised this path.
"""

import zipfile
from xml.etree import ElementTree as ET

import pytest

from src.document_model import parse_docx
from src.document_model.serializer import DocumentSerializer
from src.document_model.serializer_field_codes import _fragment_runs_balanced
from src.agent import ToolError, get_tool
from src.agent import tools
from tests.test_support import CITATION_FIELD_DOCX, DUMMY_DOCX, require_synthetic_file

SINGLE_FIELD_PARA = "1A2B3C40"   # "...clear benefit [CITATION_1] in this setting."
MULTI_FIELD_PARA = "1A2B3C41"    # 3 citations + "2013–2019" range


def _fixture():
    return parse_docx(require_synthetic_file(CITATION_FIELD_DOCX))


def _export_document_xml(model, tmp_path) -> str:
    out = tmp_path / "out.docx"
    tools.export_document(
        model, "out.docx", workspace_root=tmp_path,
        include_track_changes=True, overwrite=True,
    )
    return zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")


def _assert_valid_ooxml(document_xml: str):
    # Raises ET.ParseError if the document is structurally invalid (Word refuses
    # exactly these — the M9d re-pilot's "won't open" failure).
    ET.fromstring(document_xml)


# --------------------------------------------------------------------------- #
# The fixture itself
# --------------------------------------------------------------------------- #

class TestCitationFixture:
    def test_fields_parsed_as_placeholders(self):
        model = _fixture()
        assert list(model.get_paragraph(SINGLE_FIELD_PARA).field_codes) == ["[CITATION_1]"]
        multi = model.get_paragraph(MULTI_FIELD_PARA)
        assert list(multi.field_codes) == ["[CITATION_2]", "[CITATION_3]", "[CITATION_4]"]
        assert "[CITATION_2]" in multi.plain_text
        assert "2013\u20132019" in multi.plain_text

    def test_plain_roundtrip_is_valid_and_preserves_fields(self, tmp_path):
        model = _fixture()
        xml = _export_document_xml(model, tmp_path)
        _assert_valid_ooxml(xml)
        # 4 fields x 3 fldChar (begin/separate/end)
        assert xml.count("<w:fldChar") == 12


# --------------------------------------------------------------------------- #
# #1 Field-safe editing
# --------------------------------------------------------------------------- #

class TestFieldSafeEditing:
    def test_keep_all_citations_is_valid_and_live(self, tmp_path):
        model = _fixture()
        tools.edit_paragraph(
            model, MULTI_FIELD_PARA,
            "Earlier work showed efficacy [CITATION_2]. Later analyses [CITATION_3] "
            "and pooled meta-analyses [CITATION_4] confirmed it across 2013\u20132019 cohorts.",
        )
        xml = _export_document_xml(model, tmp_path)
        _assert_valid_ooxml(xml)
        assert xml.count("<w:fldChar") == 12  # all 4 fields still live

    def test_dropping_a_citation_is_allowed_and_valid(self, tmp_path):
        model = _fixture()
        result = tools.edit_paragraph(
            model, MULTI_FIELD_PARA,
            "Earlier work showed efficacy [CITATION_2] and meta-analyses [CITATION_4] "
            "confirmed it across 2013\u20132019 cohorts.",
        )
        assert result["removed_citations"] == ["[CITATION_3]"]
        xml = _export_document_xml(model, tmp_path)
        _assert_valid_ooxml(xml)              # removal must not corrupt the file
        assert xml.count("<w:fldChar") == 9   # [CITATION_3] gone, others live

    def test_dropping_all_citations_is_valid(self, tmp_path):
        model = _fixture()
        result = tools.edit_paragraph(
            model, MULTI_FIELD_PARA, "We revised the paragraph and removed the citations.",
        )
        assert set(result["removed_citations"]) == {"[CITATION_2]", "[CITATION_3]", "[CITATION_4]"}
        xml = _export_document_xml(model, tmp_path)
        _assert_valid_ooxml(xml)

    def test_removed_citations_absent_when_all_kept(self):
        model = _fixture()
        result = tools.edit_paragraph(
            model, SINGLE_FIELD_PARA, "An earlier randomized trial clearly showed benefit [CITATION_1] here.",
        )
        assert "removed_citations" not in result


# --------------------------------------------------------------------------- #
# #1 Layer B: serialize-time balance safety net (direct unit tests)
# --------------------------------------------------------------------------- #

class TestBalanceSafetyNet:
    def test_fragment_balance_checker(self):
        assert _fragment_runs_balanced("<w:r><w:t>ok</w:t></w:r>")
        assert _fragment_runs_balanced('<w:r><w:fldChar w:fldCharType="begin"/></w:r>')
        assert not _fragment_runs_balanced("<w:r><w:t>x</w:t></w:r></w:r>")
        assert not _fragment_runs_balanced("<w:ins><w:r><w:t>x</w:t></w:r>")

    def test_balanced_field_restores_live(self):
        s = DocumentSerializer()
        content = '<w:r><w:t xml:space="preserve">See [CITATION_9] here.</w:t></w:r>'
        field_xml = (
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> ADDIN EN.CITE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>[9]</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        )
        out = s._restore_field_codes(content, {"[CITATION_9]": field_xml})
        assert _fragment_runs_balanced(out)
        assert "<w:fldChar" in out            # restored as a live field
        assert "[CITATION_9]" not in out

    def test_unbalancing_field_degrades_to_static_text(self):
        """A field whose restoration would unbalance the paragraph is degraded to
        its citation display text — never emitted as broken runs."""
        s = DocumentSerializer()
        content = '<w:r><w:t xml:space="preserve">See [CITATION_9] here.</w:t></w:r>'
        # Deliberately unbalanced field XML (extra </w:r>): restoring it verbatim
        # would corrupt the paragraph.
        bad_field = (
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>[9]</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:r>'
        )
        out = s._restore_field_codes(content, {"[CITATION_9]": bad_field})
        assert _fragment_runs_balanced(out)   # invariant: always balanced
        assert "[9]" in out                    # citation kept as static text
        assert "[CITATION_9]" not in out
        assert "<w:fldChar" not in out         # the broken field was dropped


# --------------------------------------------------------------------------- #
# #2 Dash numeric-range repair
# --------------------------------------------------------------------------- #

class TestNumericRangeDashRepair:
    @pytest.mark.parametrize("bad", ["2013 2019", "2013-2019", "2013 - 2019", "2013\u20112019"])
    def test_range_variants_restored(self, bad):
        model = _fixture()
        result = tools.edit_paragraph(
            model, MULTI_FIELD_PARA,
            f"Trials [CITATION_2], analyses [CITATION_3] and meta-analyses [CITATION_4] "
            f"agreed across {bad} cohorts.",
        )
        assert result["restored_ranges"] == ["2013\u20132019"]
        assert "2013\u20132019" in model.get_paragraph(MULTI_FIELD_PARA).plain_text

    def test_prose_not_touched_without_original_range(self):
        out, restored = tools._restore_numeric_range_dashes("no ranges here", "the 30 90 day window")
        assert out == "the 30 90 day window"
        assert restored == []

    def test_only_original_ranges_restored(self):
        out, restored = tools._restore_numeric_range_dashes("the 30\u201390 day window", "the 30 90 day window")
        assert out == "the 30\u201390 day window"
        assert restored == ["30\u201390"]

    def test_correct_dash_left_alone(self):
        out, restored = tools._restore_numeric_range_dashes("2013\u20132019", "kept 2013\u20132019 intact")
        assert out == "kept 2013\u20132019 intact"
        assert restored == []


# --------------------------------------------------------------------------- #
# #3 Comment-reply linkage
# --------------------------------------------------------------------------- #

class TestCommentLinkage:
    def test_schema_advertises_addresses_thread_id(self):
        schema = get_tool("edit_paragraph").json_schema()
        assert "addresses_thread_id" in schema["properties"]

    def test_valid_thread_is_echoed(self):
        model = parse_docx(require_synthetic_file(DUMMY_DOCX))
        thread_id = next(iter(model.comments.threads))
        para_id = next(p.para_id for p in model.body.iter_paragraphs() if p.plain_text.strip())
        result = tools.edit_paragraph(
            model, para_id, "Revised to address the reviewer.", addresses_thread_id=thread_id,
        )
        assert result["addresses_thread_id"] == thread_id

    def test_unknown_thread_raises(self):
        model = _fixture()
        with pytest.raises(ToolError) as exc:
            tools.edit_paragraph(
                model, SINGLE_FIELD_PARA, "Benefit shown [CITATION_1].",
                addresses_thread_id="NO_SUCH_THREAD",
            )
        assert exc.value.code == "not_found"

    def test_instruction_edit_has_no_linkage(self):
        model = _fixture()
        result = tools.edit_paragraph(model, SINGLE_FIELD_PARA, "Benefit shown [CITATION_1] plainly.")
        assert "addresses_thread_id" not in result
