"""Unit tests for the agent tool layer (Stage 1, Milestone 1).

Pure-Python: no LLM, no browser. Uses committed synthetic fixtures.
"""

import shutil

import pytest

from src.document_model import parse_docx
from src.agent import ToolError, TOOLS, get_tool, list_tools
from src.agent import tools
from tests.test_support import (
    TEST_DOCX,
    SAMPLE_XLSX,
    SAMPLE_RTF,
    SAMPLE_PPTX,
    SAMPLE_TXT,
    SYNTHETIC_TEST_DATA_DIR,
)

SAMPLE_PDF = SYNTHETIC_TEST_DATA_DIR / "attachments" / "sample.pdf"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _model():
    return parse_docx(TEST_DOCX)


def _first_nonempty_para_id(model) -> str:
    for para in model.body.iter_paragraphs():
        if para.plain_text.strip():
            return para.para_id
    raise AssertionError("No non-empty paragraph in fixture")


def _first_thread_id(model) -> str:
    return next(iter(model.comments.threads.keys()))


# --------------------------------------------------------------------------- #
# list_workspace_files
# --------------------------------------------------------------------------- #

class TestListWorkspaceFiles:
    def test_lists_files_and_excludes_stet(self, temp_dir):
        shutil.copyfile(TEST_DOCX, temp_dir / "manuscript.docx")
        shutil.copyfile(SAMPLE_PDF, temp_dir / "ref.pdf")
        stet = temp_dir / ".stet"
        stet.mkdir()
        (stet / "config.json").write_text("{}", encoding="utf-8")

        result = tools.list_workspace_files(temp_dir)

        names = {f["name"] for f in result["files"]}
        assert "manuscript.docx" in names
        assert "ref.pdf" in names
        assert result["count"] == 2
        assert all(".stet" not in f["path"] for f in result["files"])

    def test_paths_are_workspace_relative(self, temp_dir):
        sub = temp_dir / "references"
        sub.mkdir()
        shutil.copyfile(SAMPLE_PDF, sub / "guide.pdf")
        result = tools.list_workspace_files(temp_dir)
        paths = {f["path"] for f in result["files"]}
        assert "references/guide.pdf" in paths

    def test_missing_root_raises(self, temp_dir):
        with pytest.raises(ToolError) as exc:
            tools.list_workspace_files(temp_dir / "nope")
        assert exc.value.code == "not_found"


# --------------------------------------------------------------------------- #
# read_document
# --------------------------------------------------------------------------- #

class TestReadDocument:
    def test_summary_matches_parse(self):
        model = _model()
        result = tools.read_document(TEST_DOCX)
        assert result["paragraph_count"] == model.paragraph_count
        assert result["comment_count"] == model.comment_count
        assert result["thread_count"] == model.thread_count
        assert result["path"] == str(TEST_DOCX)

    def test_missing_file_raises(self, temp_dir):
        with pytest.raises(ToolError) as exc:
            tools.read_document(temp_dir / "missing.docx")
        assert exc.value.code == "not_found"


# --------------------------------------------------------------------------- #
# list_comments
# --------------------------------------------------------------------------- #

class TestListComments:
    def test_all_returns_threads(self):
        model = _model()
        result = tools.list_comments(model, comment_filter="all")
        assert result["count"] == model.thread_count
        assert result["count"] > 0
        first = result["threads"][0]
        assert {"thread_id", "root_comment_id", "status", "comments"} <= first.keys()

    def test_open_is_subset_of_all(self):
        model = _model()
        all_count = tools.list_comments(model, comment_filter="all")["count"]
        open_count = tools.list_comments(model, comment_filter="open")["count"]
        resolved_count = tools.list_comments(model, comment_filter="resolved")["count"]
        assert open_count + resolved_count == all_count

    def test_invalid_filter_raises(self):
        with pytest.raises(ToolError) as exc:
            tools.list_comments(_model(), comment_filter="bogus")
        assert exc.value.code == "invalid_argument"


# --------------------------------------------------------------------------- #
# find_in_document
# --------------------------------------------------------------------------- #

class TestFindInDocument:
    def test_finds_paragraph_by_text(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        target = model.get_paragraph(para_id).plain_text
        # Search for a verbatim slice of the paragraph.
        snippet = target[: min(len(target), 40)]
        result = tools.find_in_document(model, snippet)
        assert result["count"] >= 1
        assert any(m["para_id"] == para_id for m in result["matches"])
        first = result["matches"][0]
        assert {"para_id", "text", "style"} <= first.keys()

    def test_match_is_case_and_whitespace_insensitive(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        target = model.get_paragraph(para_id).plain_text.strip()
        words = target.split()
        if len(words) < 3:
            pytest.skip("Fixture paragraph too short for whitespace test")
        # Re-spaced + upper-cased version of the first few words.
        query = "   ".join(words[:3]).upper()
        result = tools.find_in_document(model, query)
        assert any(m["para_id"] == para_id for m in result["matches"])

    def test_no_match_returns_empty(self):
        result = tools.find_in_document(_model(), "zzz_no_such_text_zzz_qwerty")
        assert result["count"] == 0
        assert result["matches"] == []
        assert result["truncated"] is False

    def test_max_results_truncates(self):
        model = _model()
        # "e" matches essentially every prose paragraph in the fixture.
        result = tools.find_in_document(model, "e", max_results=1)
        assert len(result["matches"]) <= 1
        if result["count"] > 1:
            assert result["truncated"] is True

    def test_empty_query_raises(self):
        with pytest.raises(ToolError) as exc:
            tools.find_in_document(_model(), "   ")
        assert exc.value.code == "invalid_argument"


# --------------------------------------------------------------------------- #
# read_paragraph
# --------------------------------------------------------------------------- #

class TestReadParagraph:
    def test_reads_text_and_fields(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        result = tools.read_paragraph(model, para_id)
        assert result["para_id"] == para_id
        assert result["text"]
        assert set(result["formatting_summary"]) == {
            "bold", "italic", "underline", "superscript", "subscript"
        }
        assert isinstance(result["comment_ids"], list)

    def test_anchored_paragraph_reports_comment(self):
        model = _model()
        thread = next(iter(model.comments.threads.values()))
        anchor = thread.root.anchor
        if anchor is None:
            pytest.skip("Fixture thread has no anchor")
        result = tools.read_paragraph(model, anchor.para_id)
        assert thread.root.comment_id in result["comment_ids"]

    def test_unknown_para_raises(self):
        with pytest.raises(ToolError) as exc:
            tools.read_paragraph(_model(), "DEADBEEF")
        assert exc.value.code == "not_found"


# --------------------------------------------------------------------------- #
# edit_paragraph
# --------------------------------------------------------------------------- #

class TestEditParagraph:
    def test_plain_edit_changes_text(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        result = tools.edit_paragraph(
            model, para_id, "Completely rewritten paragraph text.", track_changes=False
        )
        assert result["applied"] is True
        assert result["edit_count"] > 0
        assert "rewritten" in model.get_paragraph(para_id).plain_text

    def test_tracked_edit_records_revision(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        before = model.revision_count
        tools.edit_paragraph(
            model, para_id, "Tracked revision of the paragraph.", track_changes=True
        )
        assert model.revision_count > before

    def test_unknown_para_raises(self):
        with pytest.raises(ToolError) as exc:
            tools.edit_paragraph(_model(), "DEADBEEF", "x", track_changes=False)
        assert exc.value.code == "not_found"


# --------------------------------------------------------------------------- #
# add_comment_reply
# --------------------------------------------------------------------------- #

class TestAddCommentReply:
    def test_reply_added_to_thread(self):
        model = _model()
        thread_id = _first_thread_id(model)
        before = model.get_thread(thread_id).reply_count
        result = tools.add_comment_reply(model, thread_id, "Addressed, thank you.")
        assert result["thread_id"] == thread_id
        assert result["author"] == "Stet"
        assert model.get_thread(thread_id).reply_count == before + 1

    def test_unknown_thread_raises(self):
        with pytest.raises(ToolError) as exc:
            tools.add_comment_reply(_model(), "no_such_thread", "hi")
        assert exc.value.code == "not_found"


# --------------------------------------------------------------------------- #
# read_file
# --------------------------------------------------------------------------- #

class TestReadFile:
    def test_reads_xlsx(self):
        result = tools.read_file(SAMPLE_XLSX)
        assert result["file_type"] == "xlsx"
        assert result["content"]
        assert "sheet_count" in result["meta"]

    def test_reads_pdf(self):
        result = tools.read_file(SAMPLE_PDF)
        assert result["file_type"] == "pdf"
        assert "page_count" in result["meta"]

    def test_reads_docx_reference(self):
        result = tools.read_file(TEST_DOCX)
        assert result["file_type"] == "docx"
        assert result["content"]

    def test_reads_rtf(self):
        result = tools.read_file(SAMPLE_RTF)
        assert result["file_type"] == "rtf"
        assert "Stetomab" in result["content"]
        assert "char_count" in result["meta"]

    def test_reads_pptx(self):
        result = tools.read_file(SAMPLE_PPTX)
        assert result["file_type"] == "pptx"
        assert result["content"]
        assert result["meta"]["slide_count"] == 2
        assert result["meta"]["total_slides"] == 2

    def test_reads_txt(self):
        result = tools.read_file(SAMPLE_TXT)
        assert result["file_type"] == "txt"
        assert "Stetomab" in result["content"]
        assert result["meta"]["line_count"] >= 1

    def test_reads_md(self, temp_dir):
        md = temp_dir / "notes.md"
        md.write_text("# Heading\n\nSome **markdown** body.", encoding="utf-8")
        result = tools.read_file(md)
        assert result["file_type"] == "md"
        assert "markdown" in result["content"]

    def test_unsupported_format_raises(self, temp_dir):
        odd = temp_dir / "note.xyz"
        odd.write_text("hi", encoding="utf-8")
        with pytest.raises(ToolError) as exc:
            tools.read_file(odd)
        assert exc.value.code == "unsupported_format"

    def test_missing_file_raises(self, temp_dir):
        with pytest.raises(ToolError) as exc:
            tools.read_file(temp_dir / "ghost.pdf")
        assert exc.value.code == "not_found"


# --------------------------------------------------------------------------- #
# export_document
# --------------------------------------------------------------------------- #

class TestExportDocument:
    def test_export_roundtrip_reflects_edit(self, temp_dir):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        tools.edit_paragraph(model, para_id, "Exported revision text here.", track_changes=False)

        out = temp_dir / "exported.docx"
        result = tools.export_document(
            model, out, workspace_root=temp_dir, include_track_changes=False
        )
        assert result["path"] == str(out.resolve())
        assert out.is_file()

        reparsed = parse_docx(out)
        assert "Exported revision text here." in reparsed.get_paragraph(para_id).plain_text

    def test_export_creates_parent_dirs(self, temp_dir):
        model = _model()
        out = temp_dir / "nested" / "deep" / "out.docx"
        tools.export_document(model, out, workspace_root=temp_dir)
        assert out.is_file()

    def test_export_outside_workspace_raises(self, temp_dir):
        model = _model()
        workspace = temp_dir / "ws"
        workspace.mkdir()
        out = temp_dir / "escape.docx"  # sibling of workspace, not inside
        with pytest.raises(ToolError) as exc:
            tools.export_document(model, out, workspace_root=workspace)
        assert exc.value.code == "outside_workspace"

    def test_export_overwrite_requires_confirmation(self, temp_dir):
        model = _model()
        out = temp_dir / "exists.docx"
        tools.export_document(model, out, workspace_root=temp_dir)  # new path OK
        with pytest.raises(ToolError) as exc:
            tools.export_document(model, out, workspace_root=temp_dir)
        assert exc.value.code == "overwrite_requires_confirmation"
        # Confirming succeeds.
        tools.export_document(model, out, workspace_root=temp_dir, overwrite=True)


# --------------------------------------------------------------------------- #
# create_document
# --------------------------------------------------------------------------- #

class TestCreateDocument:
    def test_creates_blank_docx(self, temp_dir):
        out = temp_dir / "new.docx"
        result = tools.create_document(out, workspace_root=temp_dir)
        assert result["created"] is True
        assert out.is_file()
        model = parse_docx(out)
        assert model.comment_count == 0

    def test_creates_parent_dirs(self, temp_dir):
        out = temp_dir / "a" / "b" / "fresh.docx"
        tools.create_document(out, workspace_root=temp_dir)
        assert out.is_file()

    def test_outside_workspace_raises(self, temp_dir):
        workspace = temp_dir / "ws"
        workspace.mkdir()
        out = temp_dir / "outside.docx"
        with pytest.raises(ToolError) as exc:
            tools.create_document(out, workspace_root=workspace)
        assert exc.value.code == "outside_workspace"

    def test_overwrite_requires_confirmation(self, temp_dir):
        out = temp_dir / "dup.docx"
        tools.create_document(out, workspace_root=temp_dir)
        with pytest.raises(ToolError) as exc:
            tools.create_document(out, workspace_root=temp_dir)
        assert exc.value.code == "overwrite_requires_confirmation"
        tools.create_document(out, workspace_root=temp_dir, overwrite=True)


# --------------------------------------------------------------------------- #
# add_comment / remove_comment (tool layer)
# --------------------------------------------------------------------------- #

class TestAddRemoveCommentTools:
    def test_add_comment_happy_path(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        before = model.comment_count
        result = tools.add_comment(model, para_id, 0, 4, "New note.")
        assert result["para_id"] == para_id
        assert result["thread_id"] == result["comment_id"]
        assert model.comment_count == before + 1

    def test_add_comment_invalid_range_raises(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        with pytest.raises(ToolError) as exc:
            tools.add_comment(model, para_id, 5, 2, "bad")
        assert exc.value.code == "invalid_argument"

    def test_add_comment_unknown_para_raises(self):
        with pytest.raises(ToolError) as exc:
            tools.add_comment(_model(), "DEADBEEF", 0, 1, "x")
        assert exc.value.code == "invalid_argument"

    def test_remove_comment_happy_path(self):
        model = _model()
        thread_id = _first_thread_id(model)
        result = tools.remove_comment(model, thread_id)
        assert result["removed"] is True
        assert model.get_thread(thread_id) is None

    def test_remove_comment_unknown_raises(self):
        with pytest.raises(ToolError) as exc:
            tools.remove_comment(_model(), "no_such_comment")
        assert exc.value.code == "not_found"


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

class TestRegistry:
    EXPECTED = {
        "list_workspace_files", "read_document", "read_file", "create_document",
        "list_comments", "find_in_document", "read_paragraph", "edit_paragraph",
        "add_comment_reply", "add_comment", "remove_comment", "export_document",
    }

    def test_all_tools_registered(self):
        assert set(TOOLS.keys()) == self.EXPECTED
        assert len(list_tools()) == len(self.EXPECTED)

    def test_get_tool_returns_spec(self):
        spec = get_tool("edit_paragraph")
        assert spec.handler is tools.edit_paragraph
        assert spec.requires_model is True

    def test_workspace_tool_flagged(self):
        assert get_tool("list_workspace_files").requires_workspace_root is True
        # M2: the guarded writers now also require the workspace root.
        assert get_tool("export_document").requires_workspace_root is True
        assert get_tool("create_document").requires_workspace_root is True

    def test_every_schema_is_valid_json_schema(self):
        for spec in list_tools():
            schema = spec.json_schema()
            assert isinstance(schema, dict)
            assert schema.get("type") == "object"
