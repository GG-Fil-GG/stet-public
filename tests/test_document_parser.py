"""
Unit tests for the Document Parser.

Tests parsing of DOCX files into DocumentModel.
"""

import pytest
from pathlib import Path

from src.document_model import (
    DocumentParser,
    parse_docx,
    DocumentModel,
)
from tests.test_support import SYNTHETIC_TEST_DATA_DIR


# Path to test data


class TestDocumentParser:
    """Tests for DocumentParser class."""
    
    def test_parser_initialization(self):
        """Parser initializes with valid path."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        if test_file.exists():
            parser = DocumentParser(test_file)
            assert parser.docx_path == test_file
    
    def test_parser_file_not_found(self):
        """Parser raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            DocumentParser("/nonexistent/file.docx")
    
    def test_parse_returns_document_model(self):
        """parse() returns a DocumentModel instance."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        assert isinstance(model, DocumentModel)
        assert model.source_path == test_file
    
    def test_parse_extracts_paragraphs(self):
        """Parser extracts paragraphs from document."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        assert model.paragraph_count > 0
    
    def test_parse_extracts_comments(self):
        """Parser extracts comments from document."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        assert model.comment_count > 0
    
    def test_comments_have_text(self):
        """Parsed comments have text content."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        
        for comment in model.comments.comments.values():
            assert comment.text, f"Comment {comment.comment_id} has no text"
    
    def test_comments_have_author(self):
        """Parsed comments have author information."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        
        for comment in model.comments.comments.values():
            assert comment.author, f"Comment {comment.comment_id} has no author"
    
    def test_root_comments_have_anchors(self):
        """Root comments have anchor positions."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        
        for thread in model.comments.threads.values():
            assert thread.root.anchor is not None, \
                f"Thread {thread.thread_id} root has no anchor"
            assert thread.root.anchor.para_id, \
                f"Thread {thread.thread_id} anchor has no para_id"
    
    def test_reply_threading(self):
        """Parser correctly identifies reply threading."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "reply_test.docx"
        
        model = parse_docx(test_file)
        
        # Find threads with replies
        threads_with_replies = [
            t for t in model.comments.threads.values() 
            if t.reply_count > 0
        ]
        
        assert len(threads_with_replies) > 0, "Expected at least one thread with replies"
        
        for thread in threads_with_replies:
            # All replies should have a parent_para_id
            for reply in thread.replies:
                assert reply.parent_para_id is not None, \
                    f"Reply {reply.comment_id} has no parent_para_id"


class TestParserEdgeCases:
    """Tests for edge cases in document parsing."""
    
    def test_document_with_track_changes(self):
        """Parser handles documents with track changes."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test_tc_in_range.docx"
        
        model = parse_docx(test_file)
        assert model.paragraph_count > 0
        assert model.comment_count > 0

    def test_deleted_run_text_captured_from_deltext(self):
        """`<w:del><w:delText>` is captured as a deleted run (not dropped).

        Regression for the M6a viewer: deletions were invisible because the
        parser only read `<w:t>`, so deleted runs (text in `<w:delText>`) parsed
        empty and were discarded.
        """
        from lxml import etree
        from src.document_model import DocumentParser, DocumentModel

        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
        para_xml = (
            f'<w:p xmlns:w="{W}" xmlns:w14="{W14}" '
            f'w14:paraId="00000001" w14:textId="00000001">'
            '<w:r><w:t xml:space="preserve">Keep </w:t></w:r>'
            '<w:del w:id="1" w:author="Stet"><w:r><w:delText>gone</w:delText></w:r></w:del>'
            '<w:r><w:t xml:space="preserve"> end</w:t></w:r>'
            '</w:p>'
        )
        parser = DocumentParser(SYNTHETIC_TEST_DATA_DIR / "test.docx")
        para = parser._parse_paragraph(etree.fromstring(para_xml), DocumentModel())

        deleted = [r for r in para.runs if r.is_deleted()]
        assert len(deleted) == 1
        assert deleted[0].text == "gone"
        # plain_text excludes deleted text → offsets/anchors are unaffected.
        assert para.plain_text == "Keep  end"
        # The deletion is preserved (visible to the renderer via full_text/runs).
        assert "gone" in para.full_text
    
    def test_document_without_comments(self):
        """Parser handles documents without comments."""
        # Create a model and check it doesn't error
        # Even if no specific test file, the parser should handle missing comments.xml
        test_file = SYNTHETIC_TEST_DATA_DIR / "dummy.docx"
        
        model = parse_docx(test_file)
        assert model is not None
    
    def test_paragraph_para_ids_valid(self):
        """All paragraphs have valid para_ids."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        
        for para in model.body.iter_paragraphs():
            # para_id should be non-empty
            assert para.para_id, f"Paragraph {para.index} has empty para_id"


class TestAllTestDataFiles:
    """Run basic parsing test on all test data files."""
    
    @pytest.mark.parametrize("docx_file", list(SYNTHETIC_TEST_DATA_DIR.glob("*.docx")) if SYNTHETIC_TEST_DATA_DIR.exists() else [])
    def test_parse_file(self, docx_file):
        """Parse each test data file without errors."""
        model = parse_docx(docx_file)
        assert model is not None
        assert model.paragraph_count >= 0
