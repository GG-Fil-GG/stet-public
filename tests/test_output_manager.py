"""Unit tests for src/output_manager.py."""

import json
from pathlib import Path

from src.output_manager import (
    get_extractor_paths,
    get_llm_thread_path,
    get_output_dir,
    list_document_outputs,
    sanitize_filename,
    save_extractor_output,
    save_llm_suggestion,
)


class TestSanitizeFilename:
    def test_strips_date_prefix_and_draft_suffix(self):
        name = "251208_Example Study PMS Final analysis_4th draft.docx"
        slug = sanitize_filename(name)
        assert slug == "example_study_pms_final_analysis_4th"

    def test_truncates_long_names_at_word_boundary(self):
        long_name = "very_long_document_name_with_many_words_in_it.docx"
        slug = sanitize_filename(long_name, max_length=20)
        assert len(slug) <= 20
        assert "_" in slug


class TestOutputPaths:
    def test_get_output_dir_creates_structure(self, temp_dir):
        docx = temp_dir / "sample_test.docx"
        docx.write_bytes(b"fake")

        output_dir = get_output_dir(str(docx), base_output_dir=str(temp_dir / "output"))
        assert output_dir.exists()
        assert (output_dir / "llm").exists()

    def test_extractor_and_llm_paths(self, temp_dir):
        docx = temp_dir / "sample_test.docx"
        docx.write_bytes(b"fake")
        base = str(temp_dir / "output")

        extractor_paths = get_extractor_paths(str(docx), base_output_dir=base)
        assert extractor_paths["json"].name == "comments.json"
        assert extractor_paths["txt"].name == "comments.txt"

        thread_path = get_llm_thread_path(str(docx), "117", base_output_dir=base)
        assert thread_path.name == "thread_117.json"


class TestSaveOutputs:
    def test_save_extractor_output(self, temp_dir):
        docx = temp_dir / "sample_test.docx"
        docx.write_bytes(b"fake")
        base = str(temp_dir / "output")

        paths = save_extractor_output(
            str(docx),
            threads_json='{"threads": []}',
            threads_txt="No threads",
            base_output_dir=base,
        )

        assert json.loads(Path(paths["json"]).read_text(encoding="utf-8")) == {"threads": []}
        assert Path(paths["txt"]).read_text(encoding="utf-8") == "No threads"

    def test_save_llm_suggestion(self, temp_dir):
        docx = temp_dir / "sample_test.docx"
        docx.write_bytes(b"fake")
        base = str(temp_dir / "output")

        suggestion = {"revised_text": "Updated", "response": "Thanks"}
        path = save_llm_suggestion(str(docx), "42", suggestion, base_output_dir=base)

        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        assert saved == suggestion


class TestListDocumentOutputs:
    def test_lists_saved_outputs(self, temp_dir):
        docx = temp_dir / "sample_test.docx"
        docx.write_bytes(b"fake")
        base = str(temp_dir / "output")

        save_extractor_output(str(docx), "{}", "txt", base_output_dir=base)
        save_llm_suggestion(str(docx), "1", {"a": 1}, base_output_dir=base)

        results = list_document_outputs(base_output_dir=base)
        assert len(results) == 1
        entry = results[0]
        assert entry["has_comments_json"] is True
        assert entry["has_comments_txt"] is True
        assert entry["llm_thread_count"] == 1

    def test_empty_base_returns_empty_list(self, temp_dir):
        assert list_document_outputs(base_output_dir=str(temp_dir / "missing")) == []
