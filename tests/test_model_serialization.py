"""
Tests for DocumentModel serialization (to_dict / from_dict).

These tests ensure the model can be serialized to JSON and restored correctly,
which is essential for session persistence in Phase 6.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.document_model import (
    DocumentModel,
    parse_docx,
    Paragraph,
    Run,
    Comment,
    CommentAnchor,
    CommentThread,
    CommentStore,
    Revision,
    RevisionStore,
)
from src.document_model.paragraph import RunFormatting, ParagraphProperties, RevisionType
from src.document_model.model import Table, DocumentBody, DocumentProperties, StyleStore
from tests.test_support import SYNTHETIC_TEST_DATA_DIR

class TestRunFormattingSerialization:
    """Tests for RunFormatting serialization."""
    
    def test_empty_formatting(self):
        """Test serializing default/empty formatting."""
        fmt = RunFormatting()
        d = fmt.to_dict()
        restored = RunFormatting.from_dict(d)
        
        assert restored.bold == fmt.bold
        assert restored.italic == fmt.italic
        assert restored.is_empty() == fmt.is_empty()
    
    def test_full_formatting(self):
        """Test serializing formatting with all properties set."""
        fmt = RunFormatting(
            bold=True,
            italic=True,
            underline=True,
            strike=True,
            superscript=True,
            font_name="Arial",
            font_size=12.5,
            color="FF0000",
            highlight="yellow",
        )
        d = fmt.to_dict()
        restored = RunFormatting.from_dict(d)
        
        assert restored.bold is True
        assert restored.italic is True
        assert restored.underline is True
        assert restored.strike is True
        assert restored.superscript is True
        assert restored.font_name == "Arial"
        assert restored.font_size == 12.5
        assert restored.color == "FF0000"
        assert restored.highlight == "yellow"


class TestRunSerialization:
    """Tests for Run serialization."""
    
    def test_simple_run(self):
        """Test serializing a simple run."""
        run = Run(
            text="Hello world",
            start_offset=0,
            end_offset=11,
        )
        d = run.to_dict()
        restored = Run.from_dict(d)
        
        assert restored.text == "Hello world"
        assert restored.start_offset == 0
        assert restored.end_offset == 11
    
    def test_run_with_revision(self):
        """Test serializing run with revision type."""
        run = Run(
            text="inserted",
            revision_type=RevisionType.INSERTION,
            revision_id="1",
        )
        d = run.to_dict()
        restored = Run.from_dict(d)
        
        assert restored.revision_type == RevisionType.INSERTION
        assert restored.revision_id == "1"


class TestParagraphSerialization:
    """Tests for Paragraph serialization."""
    
    def test_simple_paragraph(self):
        """Test serializing a simple paragraph."""
        para = Paragraph(
            para_id="12345678",
            text_id="ABCDEF12",
            runs=[Run(text="Test text")],
            index=0,
        )
        d = para.to_dict()
        restored = Paragraph.from_dict(d)
        
        assert restored.para_id == "12345678"
        assert restored.text_id == "ABCDEF12"
        assert len(restored.runs) == 1
        assert restored.runs[0].text == "Test text"
    
    def test_paragraph_with_multiple_runs(self):
        """Test paragraph with multiple runs."""
        para = Paragraph(
            para_id="12345678",
            text_id="ABCDEF12",
            runs=[
                Run(text="Normal "),
                Run(text="bold", formatting=RunFormatting(bold=True)),
                Run(text=" text"),
            ],
        )
        d = para.to_dict()
        restored = Paragraph.from_dict(d)
        
        assert len(restored.runs) == 3
        assert restored.runs[1].formatting.bold is True


class TestCommentSerialization:
    """Tests for Comment serialization."""
    
    def test_root_comment(self):
        """Test serializing a root comment."""
        comment = Comment(
            comment_id="1",
            para_id="12345678",
            text="Test comment",
            author="Test Author",
            author_initials="TA",
            date=datetime(2025, 2, 5, 10, 30, 0, tzinfo=timezone.utc),
            is_resolved=False,
        )
        d = comment.to_dict()
        restored = Comment.from_dict(d)
        
        assert restored.comment_id == "1"
        assert restored.text == "Test comment"
        assert restored.author == "Test Author"
        assert restored.is_root
    
    def test_reply_comment(self):
        """Test serializing a reply comment."""
        comment = Comment(
            comment_id="2",
            para_id="23456789",
            text="Reply text",
            author="Replier",
            parent_para_id="12345678",
        )
        d = comment.to_dict()
        restored = Comment.from_dict(d)
        
        assert restored.is_reply
        assert restored.parent_para_id == "12345678"
    
    def test_comment_with_anchor(self):
        """Test serializing comment with anchor."""
        anchor = CommentAnchor(
            comment_id="1",
            para_id="12345678",
            start_offset=5,
            end_offset=10,
        )
        comment = Comment(
            comment_id="1",
            para_id="12345678",
            text="Comment on text",
            anchor=anchor,
        )
        d = comment.to_dict()
        restored = Comment.from_dict(d)
        
        assert restored.anchor is not None
        assert restored.anchor.start_offset == 5
        assert restored.anchor.end_offset == 10


class TestCommentStoreSerialization:
    """Tests for CommentStore serialization."""
    
    def test_empty_store(self):
        """Test serializing empty store."""
        store = CommentStore()
        d = store.to_dict()
        restored = CommentStore.from_dict(d)
        
        assert restored.comment_count == 0
        assert restored.thread_count == 0
    
    def test_store_with_thread(self):
        """Test serializing store with a thread."""
        store = CommentStore()
        root = Comment(
            comment_id="1",
            para_id="12345678",
            text="Root comment",
            author="Author",
        )
        store.add_comment(root)
        
        d = store.to_dict()
        restored = CommentStore.from_dict(d)
        
        assert restored.comment_count == 1
        assert restored.thread_count == 1
        assert restored.get_comment("1") is not None

    def test_round_trip_root_identity(self):
        """After round-trip, thread.root must be the same object as store.comments[id]."""
        store = CommentStore()
        store.add_comment(Comment(
            comment_id="1", para_id="12345678",
            text="Root", author="A",
            anchor=CommentAnchor(comment_id="1", para_id="AABBCCDD",
                                 start_offset=0, end_offset=5),
        ))

        restored = CommentStore.from_dict(store.to_dict())

        assert restored.comments["1"] is restored.threads["1"].root

    def test_round_trip_reply_identity(self):
        """After round-trip, thread replies must be the same objects as store.comments."""
        store = CommentStore()
        store.add_comment(Comment(
            comment_id="1", para_id="12345678",
            text="Root", author="A",
        ))
        store.add_comment(Comment(
            comment_id="2", para_id="23456789",
            text="Reply", author="B",
            parent_para_id="12345678",
        ))

        restored = CommentStore.from_dict(store.to_dict())

        assert restored.comments["2"] is restored.threads["1"].replies[0]

    def test_round_trip_mutation_propagates(self):
        """Mutating a comment via store.comments must be visible via thread.root."""
        store = CommentStore()
        store.add_comment(Comment(
            comment_id="1", para_id="12345678",
            text="Root", author="A",
        ))

        restored = CommentStore.from_dict(store.to_dict())
        restored.comments["1"].is_resolved = True

        assert restored.threads["1"].root.is_resolved is True
        assert restored.threads["1"].is_resolved is True

    def test_round_trip_preserves_reply_order(self):
        """Replies must stay in their original order after round-trip."""
        store = CommentStore()
        store.add_comment(Comment(
            comment_id="1", para_id="12345678",
            text="Root", author="A",
        ))
        store.add_comment(Comment(
            comment_id="2", para_id="23456789",
            text="First reply", author="B",
            parent_para_id="12345678",
            date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ))
        store.add_comment(Comment(
            comment_id="3", para_id="34567890",
            text="Second reply", author="C",
            parent_para_id="12345678",
            date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        ))

        restored = CommentStore.from_dict(store.to_dict())

        assert len(restored.threads["1"].replies) == 2
        assert restored.threads["1"].replies[0].comment_id == "2"
        assert restored.threads["1"].replies[1].comment_id == "3"


class TestRevisionSerialization:
    """Tests for Revision serialization."""
    
    def test_insertion_revision(self):
        """Test serializing insertion revision."""
        rev = Revision(
            revision_id="1",
            revision_type=RevisionType.INSERTION,
            para_id="12345678",
            start_offset=5,
            end_offset=15,
            text="new text",
            author="Editor",
            timestamp=datetime(2025, 2, 5, 10, 30, 0, tzinfo=timezone.utc),
        )
        d = rev.to_dict()
        restored = Revision.from_dict(d)
        
        assert restored.revision_type == RevisionType.INSERTION
        assert restored.text == "new text"
        assert restored.author == "Editor"
    
    def test_deletion_revision(self):
        """Test serializing deletion revision."""
        rev = Revision(
            revision_id="2",
            revision_type=RevisionType.DELETION,
            para_id="12345678",
            start_offset=0,
            end_offset=5,
            text="old",
        )
        d = rev.to_dict()
        restored = Revision.from_dict(d)
        
        assert restored.revision_type == RevisionType.DELETION


class TestRevisionStoreSerialization:
    """Tests for RevisionStore serialization."""
    
    def test_empty_store(self):
        """Test serializing empty revision store."""
        store = RevisionStore()
        d = store.to_dict()
        restored = RevisionStore.from_dict(d)
        
        assert restored.revision_count == 0
    
    def test_store_with_revisions(self):
        """Test serializing store with revisions."""
        store = RevisionStore()
        store.add_insertion("12345678", 0, "new text", "Author")
        store.add_deletion("12345678", 10, 15, "old", "Author")
        
        d = store.to_dict()
        restored = RevisionStore.from_dict(d)
        
        assert restored.revision_count == 2


class TestDocumentBodySerialization:
    """Tests for DocumentBody serialization."""
    
    def test_empty_body(self):
        """Test serializing empty body."""
        body = DocumentBody()
        d = body.to_dict()
        restored = DocumentBody.from_dict(d)
        
        assert restored.paragraph_count == 0
    
    def test_body_with_paragraphs(self):
        """Test serializing body with paragraphs."""
        body = DocumentBody()
        body.add_element(Paragraph(para_id="11111111", text_id="AAAAAAAA", runs=[Run(text="Para 1")]))
        body.add_element(Paragraph(para_id="22222222", text_id="BBBBBBBB", runs=[Run(text="Para 2")]))
        
        d = body.to_dict()
        restored = DocumentBody.from_dict(d)
        
        assert restored.paragraph_count == 2
        assert restored.get_element_by_para_id("11111111") is not None


class TestDocumentModelSerialization:
    """Tests for DocumentModel serialization."""
    
    def test_empty_model(self):
        """Test serializing empty model."""
        model = DocumentModel()
        d = model.to_dict()
        restored = DocumentModel.from_dict(d)
        
        assert restored.paragraph_count == 0
        assert restored.comment_count == 0
    
    def test_model_with_content(self):
        """Test serializing model with content."""
        model = DocumentModel(source_path=Path("/test/path.docx"))
        model.body.add_element(Paragraph(
            para_id="12345678",
            text_id="ABCDEF12",
            runs=[Run(text="Test paragraph")]
        ))
        
        d = model.to_dict()
        restored = DocumentModel.from_dict(d)
        
        assert restored.paragraph_count == 1
        assert str(restored.source_path) == "/test/path.docx"
    
    def test_json_serializable(self):
        """Test that to_dict output is JSON serializable."""
        model = DocumentModel()
        model.body.add_element(Paragraph(
            para_id="12345678",
            text_id="ABCDEF12",
            runs=[Run(text="Test")]
        ))
        
        d = model.to_dict()
        json_str = json.dumps(d)
        
        assert json_str is not None
        assert len(json_str) > 0


class TestRealDocumentSerialization:
    """Tests with real document files."""
    
    @pytest.fixture
    def test_docx_path(self):
        """Get path to test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return path
    
    def test_round_trip_preservation(self, test_docx_path):
        """Test that round-trip preserves all data."""
        original = parse_docx(test_docx_path)
        
        d = original.to_dict()
        restored = DocumentModel.from_dict(d)
        
        assert restored.paragraph_count == original.paragraph_count
        assert restored.comment_count == original.comment_count
        assert restored.thread_count == original.thread_count
    
    def test_json_round_trip(self, test_docx_path):
        """Test full JSON round-trip (serialize to JSON string and back)."""
        original = parse_docx(test_docx_path)
        
        json_str = json.dumps(original.to_dict())
        restored = DocumentModel.from_dict(json.loads(json_str))
        
        assert restored.paragraph_count == original.paragraph_count
        assert restored.comment_count == original.comment_count
    
    def test_paragraph_text_preserved(self, test_docx_path):
        """Test that paragraph text is preserved."""
        original = parse_docx(test_docx_path)
        
        d = original.to_dict()
        restored = DocumentModel.from_dict(d)
        
        # Compare first few paragraphs
        orig_paras = list(original.body.iter_paragraphs())[:5]
        rest_paras = list(restored.body.iter_paragraphs())[:5]
        
        for orig, rest in zip(orig_paras, rest_paras):
            assert orig.plain_text == rest.plain_text
            assert orig.para_id == rest.para_id
    
    def test_comments_preserved(self, test_docx_path):
        """Test that comments are preserved."""
        original = parse_docx(test_docx_path)
        
        if original.comment_count == 0:
            pytest.skip("No comments in test document")
        
        d = original.to_dict()
        restored = DocumentModel.from_dict(d)
        
        # Compare threads
        for thread_id in original.comments.threads:
            orig_thread = original.comments.get_thread(thread_id)
            rest_thread = restored.comments.get_thread(thread_id)
            
            assert rest_thread is not None
            assert rest_thread.root.text == orig_thread.root.text
            assert rest_thread.root.author == orig_thread.root.author
            assert len(rest_thread.replies) == len(orig_thread.replies)


class TestMultipleDocuments:
    """Tests with multiple document files."""
    
    @pytest.mark.parametrize("filename", [
        "test.docx",
        "dummy.docx",
        "reply_test.docx",
    ])
    def test_various_documents(self, filename):
        """Test serialization with various documents."""
        path = SYNTHETIC_TEST_DATA_DIR / filename
        
        original = parse_docx(path)
        d = original.to_dict()
        restored = DocumentModel.from_dict(d)
        
        assert restored.paragraph_count == original.paragraph_count
        assert restored.comment_count == original.comment_count
