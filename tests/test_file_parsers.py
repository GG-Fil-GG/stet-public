"""Unit tests for src/file_parsers/*."""

from pathlib import Path

import pytest

from src.file_parsers import (
    DocxParser,
    PDFParser,
    PptxParser,
    RtfParser,
    SpreadsheetParser,
)
from tests.test_support import (
    DUMMY_DOCX,
    SAMPLE_PPTX,
    SAMPLE_RTF,
    SAMPLE_XLSX,
    SYNTHETIC_TEST_DATA_DIR,
    require_synthetic_file,
)


SAMPLE_PDF = SYNTHETIC_TEST_DATA_DIR / "attachments" / "sample.pdf"


class TestSpreadsheetParser:
    def test_parse_xlsx(self):
        path = require_synthetic_file(SAMPLE_XLSX)
        result = SpreadsheetParser().parse(str(path))

        assert result.error is None
        assert result.file_type == "xlsx"
        assert result.sheet_count >= 1
        markdown = result.to_markdown()
        assert "Spreadsheet:" in markdown
        assert result.get_token_estimate() > 0

    def test_get_sheet_info(self):
        path = require_synthetic_file(SAMPLE_XLSX)
        info = SpreadsheetParser().get_sheet_info(str(path))
        assert info["file_type"] == "xlsx"
        assert info["sheet_count"] >= 1
        assert len(info["sheet_names"]) >= 1

    def test_unsupported_extension_returns_error(self, temp_dir):
        bad_file = temp_dir / "data.txt"
        bad_file.write_text("not a spreadsheet")
        result = SpreadsheetParser().parse(str(bad_file))
        assert result.error is not None
        assert result.sheets == []


class TestPDFParser:
    def test_parse_sample_pdf(self):
        path = require_synthetic_file(SAMPLE_PDF)
        result = PDFParser().parse(str(path), max_pages=2)

        assert result.error is None
        assert result.total_pages >= 1
        assert result.pages_extracted >= 1
        markdown = result.to_markdown()
        assert "PDF:" in markdown

    def test_get_page_count(self):
        path = require_synthetic_file(SAMPLE_PDF)
        count = PDFParser().get_page_count(str(path))
        assert count >= 1

    def test_parse_pages_string(self):
        parser = PDFParser()
        assert parser.parse_pages_string("1-3", total_pages=10) == [1, 2, 3]
        assert parser.parse_pages_string("1, 5, 10", total_pages=10) == [1, 5, 10]
        assert parser.parse_pages_string("15-20", total_pages=10) == [10]


class TestDocxParser:
    def test_parse_dummy_docx(self):
        path = require_synthetic_file(DUMMY_DOCX)
        result = DocxParser().parse(str(path))

        assert result.error is None
        assert result.section_count >= 1
        assert result.paragraph_count >= 1
        markdown = result.to_markdown()
        assert "Document:" in markdown
        assert result.get_token_estimate() > 0

    def test_get_document_info(self):
        path = require_synthetic_file(DUMMY_DOCX)
        info = DocxParser().get_document_info(str(path))
        assert info["has_error"] is False
        assert info["paragraph_count"] >= 1

    def test_invalid_file_returns_error(self, temp_dir):
        bad_file = temp_dir / "bad.docx"
        bad_file.write_text("not a zip")
        result = DocxParser().parse(str(bad_file))
        assert result.error is not None
        assert result.sections == []


class TestRtfParser:
    def test_parse_sample_rtf(self):
        path = require_synthetic_file(SAMPLE_RTF)
        result = RtfParser().parse(str(path))

        assert result.error is None
        assert "Stetomab" in result.text
        assert "intention-to-treat" in result.text
        markdown = result.to_markdown()
        assert "=== RTF:" in markdown
        assert result.get_token_estimate() > 0

    def test_unicode_rtf_decodes(self, temp_dir):
        # \u escapes are how RTF stores non-ASCII; striprtf should resolve them.
        rtf = r"{\rtf1\ansi\ansicpg932 \u26085?\u26412? text\par}"
        path = temp_dir / "jp.rtf"
        path.write_text(rtf, encoding="utf-8")
        result = RtfParser().parse(str(path))
        assert result.error is None
        assert "text" in result.text

    def test_truncation_marker(self, temp_dir):
        from src.file_parsers.rtf_parser import MAX_CHARS

        big_body = "word " * (MAX_CHARS // 2)
        path = temp_dir / "big.rtf"
        path.write_text(r"{\rtf1\ansi " + big_body + r"\par}", encoding="utf-8")
        result = RtfParser().parse(str(path))
        assert result.error is None
        assert result.text.endswith("[... truncated]")

    def test_missing_file_sets_error(self, temp_dir):
        result = RtfParser().parse(str(temp_dir / "ghost.rtf"))
        assert result.error is not None
        assert result.text == ""


class TestPptxParser:
    def test_parse_sample_pptx(self):
        path = require_synthetic_file(SAMPLE_PPTX)
        result = PptxParser().parse(str(path))

        assert result.error is None
        assert result.slide_count == 2
        assert result.total_slides == 2
        assert result.slides[0].title
        # Title is not duplicated into the body text.
        assert result.slides[0].title not in result.slides[0].body_text
        # Speaker notes captured on slide 2.
        assert "statistical appendix" in result.slides[1].notes
        markdown = result.to_markdown()
        assert "=== PPTX:" in markdown
        assert result.get_token_estimate() > 0

    def test_slide_cap_truncates(self):
        path = require_synthetic_file(SAMPLE_PPTX)
        result = PptxParser().parse(str(path), max_slides=1)
        assert result.slide_count == 1
        assert result.total_slides == 2
        assert "truncated, showing first 1 of 2 slides" in result.to_markdown()

    def test_invalid_pptx_sets_error(self, temp_dir):
        bad_file = temp_dir / "bad.pptx"
        bad_file.write_text("not a zip")
        result = PptxParser().parse(str(bad_file))
        assert result.error is not None
        assert result.slides == []
