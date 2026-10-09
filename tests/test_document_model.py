"""
Unit tests for the Document Model (Phase 1).

Tests the core data structures without parsing/serialization.
"""

import pytest
from datetime import datetime

from src.document_model import (
    # Core model
    DocumentModel,
    DocumentBody,
    Table,
    
    # Paragraph
    Paragraph,
    Run,
    RunFormatting,
    
    # Comments
    Comment,
    CommentStore,
    CommentThread,
    CommentAnchor,
    CommentParagraph,
    
    # Revisions
    Revision,
    RevisionStore,
    RevisionType,
    
    # Edits
    DocumentEdit,
    EditType,
    
    # Utilities
    generate_valid_para_id,
    generate_hex_id,
    generate_comment_id,
    is_valid_para_id,
    is_valid_hex_id,
)


class TestIDGenerators:
    """Tests for ID generation utilities."""
    
    def test_generate_valid_para_id_first_char_constraint(self):
        """ParaId first character must be 0-7."""
        existing = set()
        for _ in range(100):
            para_id = generate_valid_para_id(existing)
            assert para_id[0] in '01234567', f"Invalid first char: {para_id[0]}"
            assert len(para_id) == 8
            existing.add(para_id)
    
    def test_generate_valid_para_id_uniqueness(self):
        """Generated paraIds must be unique."""
        existing = set()
        for _ in range(50):
            para_id = generate_valid_para_id(existing)
            assert para_id not in existing
            existing.add(para_id)
    
    def test_generate_valid_para_id_avoids_existing(self):
        """Generator respects existing IDs."""
        existing = {"00000001", "00000002", "00000003"}
        para_id = generate_valid_para_id(existing)
        assert para_id not in existing
    
    def test_generate_hex_id_no_constraint(self):
        """Hex IDs can use full 0-F range."""
        existing = set()
        first_chars_seen = set()
        for _ in range(100):
            hex_id = generate_hex_id(existing)
            first_chars_seen.add(hex_id[0])
            assert len(hex_id) == 8
            existing.add(hex_id)
        # Should eventually see characters > 7 (statistically likely in 100 tries)
        # Note: This could theoretically fail but is extremely unlikely
        assert len(first_chars_seen) > 4, "Expected more variety in first chars"
    
    def test_generate_comment_id_format(self):
        """Comment IDs are integers as strings."""
        existing = set()
        for _ in range(20):
            comment_id = generate_comment_id(existing)
            assert comment_id.isdigit()
            int_id = int(comment_id)
            assert 100 <= int_id <= 9999
            existing.add(int_id)
    
    def test_is_valid_para_id(self):
        """Validate paraId checker."""
        assert is_valid_para_id("01234567")  # Valid
        assert is_valid_para_id("7FFFFFFF")  # Valid (max)
        assert not is_valid_para_id("80000000")  # Invalid (starts with 8)
        assert not is_valid_para_id("ABCDEF12")  # Invalid (starts with A)
        assert not is_valid_para_id("1234567")  # Invalid (too short)
        assert not is_valid_para_id("123456789")  # Invalid (too long)
        assert not is_valid_para_id("")  # Invalid (empty)
        assert not is_valid_para_id("GHIJKLMN")  # Invalid (not hex)
    
    def test_is_valid_hex_id(self):
        """Validate hex ID checker."""
        assert is_valid_hex_id("ABCDEF12")  # Valid
        assert is_valid_hex_id("00000000")  # Valid
        assert is_valid_hex_id("FFFFFFFF")  # Valid
        assert not is_valid_hex_id("abcdef12")  # Invalid (lowercase)
        assert not is_valid_hex_id("1234567")  # Invalid (too short)
        assert not is_valid_hex_id("")  # Invalid (empty)


class TestRunFormatting:
    """Tests for RunFormatting dataclass."""
    
    def test_default_formatting_is_empty(self):
        """Default formatting should be empty (no styling)."""
        fmt = RunFormatting()
        assert fmt.is_empty()
    
    def test_formatting_equality(self):
        """Formatting objects with same properties are equal."""
        fmt1 = RunFormatting(bold=True, italic=True)
        fmt2 = RunFormatting(bold=True, italic=True)
        assert fmt1 == fmt2
    
    def test_formatting_copy(self):
        """Copy creates independent object."""
        fmt1 = RunFormatting(bold=True, font_size=12.0)
        fmt2 = fmt1.copy()
        fmt2.bold = False
        assert fmt1.bold is True
        assert fmt2.bold is False


class TestRun:
    """Tests for Run dataclass."""
    
    def test_run_creation(self):
        """Basic run creation."""
        run = Run(text="Hello", start_offset=0)
        assert run.text == "Hello"
        assert run.length == 5
        assert run.end_offset == 5
    
    def test_run_revision_flags(self):
        """Run revision type flags."""
        normal_run = Run(text="normal")
        assert not normal_run.is_deleted()
        assert not normal_run.is_inserted()
        
        deleted_run = Run(text="deleted", revision_type=RevisionType.DELETION)
        assert deleted_run.is_deleted()
        
        inserted_run = Run(text="inserted", revision_type=RevisionType.INSERTION)
        assert inserted_run.is_inserted()


class TestParagraph:
    """Tests for Paragraph dataclass."""
    
    def test_paragraph_creation(self):
        """Basic paragraph creation."""
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[Run(text="Hello world")]
        )
        assert para.plain_text == "Hello world"
        assert para.char_count == 11
    
    def test_paragraph_excludes_deleted_text(self):
        """plain_text excludes deleted runs."""
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[
                Run(text="Keep this"),
                Run(text=" delete this", revision_type=RevisionType.DELETION),
                Run(text=" and this")
            ]
        )
        assert para.plain_text == "Keep this and this"
        assert para.full_text == "Keep this delete this and this"
    
    def test_get_run_at_offset(self):
        """Find run containing character offset."""
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[
                Run(text="Hello ", start_offset=0),
                Run(text="world", start_offset=6)
            ]
        )
        
        run, offset = para.get_run_at_offset(0)
        assert run.text == "Hello "
        assert offset == 0
        
        run, offset = para.get_run_at_offset(7)
        assert run.text == "world"
        assert offset == 1
    
    def test_insert_text_at_end(self):
        """Insert text at the end of paragraph."""
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[Run(text="Hello")]
        )
        para.insert_text(5, " world")
        assert para.plain_text == "Hello world"
    
    def test_insert_text_in_middle(self):
        """Insert text in the middle of a run."""
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[Run(text="Helloworld")]
        )
        para.insert_text(5, " ")
        assert para.plain_text == "Hello world"
    
    def test_delete_text(self):
        """Delete text from paragraph."""
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[Run(text="Hello world")]
        )
        deleted = para.delete_text(5, 11)
        assert deleted == " world"
        assert para.plain_text == "Hello"


class TestCommentAnchor:
    """Tests for CommentAnchor dataclass."""
    
    def test_anchor_creation(self):
        """Basic anchor creation."""
        anchor = CommentAnchor(
            comment_id="1",
            para_id="01234567",
            start_offset=0,
            end_offset=10
        )
        assert not anchor.is_collapsed
        assert not anchor.spans_paragraphs
    
    def test_collapsed_anchor(self):
        """Zero-width anchor detection."""
        anchor = CommentAnchor(
            comment_id="1",
            para_id="01234567",
            start_offset=5,
            end_offset=5
        )
        assert anchor.is_collapsed
    
    def test_anchor_shift(self):
        """Anchor position adjustment after edit."""
        anchor = CommentAnchor(
            comment_id="1",
            para_id="01234567",
            start_offset=10,
            end_offset=20
        )
        
        # Insert 5 chars before anchor
        anchor.shift(5, 5)
        assert anchor.start_offset == 15
        assert anchor.end_offset == 25
        
        # Delete 3 chars after anchor (no effect)
        anchor.shift(-3, 30)
        assert anchor.start_offset == 15
        assert anchor.end_offset == 25
    
    def test_anchor_contains_offset(self):
        """Check if offset is within anchor range."""
        anchor = CommentAnchor(
            comment_id="1",
            para_id="01234567",
            start_offset=10,
            end_offset=20
        )
        assert anchor.contains_offset(10)
        assert anchor.contains_offset(15)
        assert not anchor.contains_offset(20)  # End is exclusive
        assert not anchor.contains_offset(5)


class TestComment:
    """Tests for Comment dataclass."""
    
    def test_comment_creation(self):
        """Basic comment creation."""
        comment = Comment(
            comment_id="1",
            para_id="01234567",
            text="This is a comment",
            author="Test Author"
        )
        assert comment.is_root
        assert not comment.is_reply
    
    def test_reply_comment(self):
        """Reply comment detection."""
        reply = Comment(
            comment_id="2",
            para_id="12345678",
            text="This is a reply",
            author="Test Author",
            parent_para_id="01234567"
        )
        assert not reply.is_root
        assert reply.is_reply


class TestCommentStore:
    """Tests for CommentStore."""
    
    def test_add_root_comment(self):
        """Adding a root comment creates a thread."""
        store = CommentStore()
        comment = Comment(
            comment_id="1",
            para_id="01234567",
            text="Root comment",
            author="Author"
        )
        store.add_comment(comment)
        
        assert store.comment_count == 1
        assert store.thread_count == 1
        assert store.get_thread("1") is not None
    
    def test_add_reply_to_comment(self):
        """Adding a reply using add_reply method."""
        store = CommentStore()
        
        # Add root comment
        root = Comment(
            comment_id="1",
            para_id="01234567",
            text="Root comment",
            author="Author",
            anchor=CommentAnchor(comment_id="1", para_id="PARA0001", start_offset=0, end_offset=10)
        )
        store.add_comment(root)
        
        # Add reply
        reply = store.add_reply(
            parent_comment_id="1",
            text="Reply text",
            author="Replier",
            timestamp=datetime.now()
        )
        
        assert reply is not None
        assert reply.is_reply
        assert reply.parent_para_id == root.para_id
        
        thread = store.get_thread("1")
        assert thread.reply_count == 1
        assert thread.all_comments == [root, reply]
    
    def test_get_thread_for_comment(self):
        """Find thread containing a comment."""
        store = CommentStore()
        
        root = Comment(comment_id="1", para_id="01234567", text="Root", author="A")
        store.add_comment(root)
        
        thread = store.get_thread_for_comment("1")
        assert thread is not None
        assert thread.root == root
    
    def test_resolve_thread(self):
        """Resolving and unresolving threads."""
        store = CommentStore()
        root = Comment(comment_id="1", para_id="01234567", text="Root", author="A")
        store.add_comment(root)
        
        assert not store.get_thread("1").is_resolved
        
        store.resolve_thread("1")
        assert store.get_thread("1").is_resolved
        
        store.unresolve_thread("1")
        assert not store.get_thread("1").is_resolved


class TestRevisionStore:
    """Tests for RevisionStore."""
    
    def test_add_insertion(self):
        """Adding an insertion revision."""
        store = RevisionStore()
        rev = store.add_insertion(
            para_id="01234567",
            position=10,
            text="inserted text",
            author="Author"
        )
        
        assert rev.revision_type == RevisionType.INSERTION
        assert rev.text == "inserted text"
        assert store.revision_count == 1
    
    def test_add_deletion(self):
        """Adding a deletion revision."""
        store = RevisionStore()
        rev = store.add_deletion(
            para_id="01234567",
            start=10,
            end=20,
            original_text="deleted text",
            author="Author"
        )
        
        assert rev.revision_type == RevisionType.DELETION
        assert rev.text == "deleted text"
    
    def test_accept_reject_revision(self):
        """Accepting and rejecting revisions."""
        store = RevisionStore()
        rev = store.add_insertion(
            para_id="01234567",
            position=10,
            text="test",
            author="Author"
        )
        
        assert rev.is_pending
        
        store.accept_revision(rev.revision_id)
        assert rev.is_accepted
        assert not rev.is_pending
        
        # Reject overrides accept
        store.reject_revision(rev.revision_id)
        assert rev.is_rejected
        assert not rev.is_accepted


class TestDocumentEdit:
    """Tests for DocumentEdit."""
    
    def test_create_insert_edit(self):
        """Create an insertion edit."""
        edit = DocumentEdit.insert(
            para_id="01234567",
            position=10,
            text="new text"
        )
        
        assert edit.is_insert
        assert edit.insertion_length == 8
        assert edit.deletion_length == 0
        assert edit.net_length_change == 8
    
    def test_create_delete_edit(self):
        """Create a deletion edit."""
        edit = DocumentEdit.delete(
            para_id="01234567",
            start=10,
            end=20
        )
        
        assert edit.is_delete
        assert edit.deletion_length == 10
        assert edit.net_length_change == -10
    
    def test_create_replace_edit(self):
        """Create a replacement edit."""
        edit = DocumentEdit.replace(
            para_id="01234567",
            start=10,
            end=20,
            new_text="new"
        )
        
        assert edit.is_replace
        assert edit.deletion_length == 10
        assert edit.insertion_length == 3
        assert edit.net_length_change == -7
    
    def test_edit_validation(self):
        """Edit validation catches errors."""
        with pytest.raises(ValueError):
            edit = DocumentEdit(
                edit_type=EditType.INSERT,
                para_id="",  # Invalid: empty para_id
                start_offset=0,
                text="test"
            )
            edit.validate()
        
        with pytest.raises(ValueError):
            edit = DocumentEdit(
                edit_type=EditType.DELETE,
                para_id="01234567",
                start_offset=10,
                end_offset=10  # Invalid: zero-length delete
            )
            edit.validate()


class TestDocumentModel:
    """Tests for DocumentModel."""
    
    def test_create_empty_model(self):
        """Create an empty document model."""
        model = DocumentModel()
        assert model.paragraph_count == 0
        assert model.comment_count == 0
        assert not model.is_dirty
    
    def test_add_paragraph(self):
        """Add paragraphs to model."""
        model = DocumentModel()
        
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[Run(text="Hello world")]
        )
        model.body.add_element(para)
        
        assert model.paragraph_count == 1
        assert model.get_paragraph("01234567") == para
    
    def test_apply_insert_edit(self):
        """Apply an insertion edit."""
        model = DocumentModel()
        
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[Run(text="Hello world")]
        )
        model.body.add_element(para)
        
        edit = DocumentEdit.insert(
            para_id="01234567",
            position=5,
            text=" beautiful"
        )
        
        result = model.apply_edit(edit)
        assert result is True
        assert para.plain_text == "Hello beautiful world"
        assert model.is_dirty
        assert model.revision_count == 1
    
    def test_apply_delete_edit(self):
        """Apply a deletion edit."""
        model = DocumentModel()
        
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[Run(text="Hello beautiful world")]
        )
        model.body.add_element(para)
        
        edit = DocumentEdit.delete(
            para_id="01234567",
            start=5,
            end=15
        )
        
        result = model.apply_edit(edit)
        assert result is True
        assert para.plain_text == "Hello world"
    
    def test_edit_adjusts_anchors(self):
        """Edits adjust comment anchor positions."""
        model = DocumentModel()
        
        para = Paragraph(
            para_id="01234567",
            text_id="ABCDEF12",
            runs=[Run(text="Hello world")]
        )
        model.body.add_element(para)
        
        # Add comment anchored at "world" (position 6-11)
        comment = Comment(
            comment_id="1",
            para_id="COMMENT1",
            text="Comment on world",
            author="Author",
            anchor=CommentAnchor(
                comment_id="1",
                para_id="01234567",
                start_offset=6,
                end_offset=11
            )
        )
        model.comments.add_comment(comment)
        
        # Insert " beautiful" at position 5
        edit = DocumentEdit.insert(
            para_id="01234567",
            position=5,
            text=" beautiful"
        )
        model.apply_edit(edit)
        
        # Anchor should shift
        assert comment.anchor.start_offset == 16  # 6 + 10
        assert comment.anchor.end_offset == 21    # 11 + 10
    
    def test_get_context_paragraphs(self):
        """Get paragraphs around a target for context."""
        model = DocumentModel()
        
        for i in range(5):
            para = Paragraph(
                para_id=f"0{i}234567",
                text_id=f"ABCDEF{i}2",
                runs=[Run(text=f"Paragraph {i}")]
            )
            model.body.add_element(para)
        
        # Get context around paragraph 2 (middle)
        context = model.get_context_paragraphs("02234567", before=1, after=1)
        assert len(context) == 3
        assert context[0].para_id == "01234567"
        assert context[1].para_id == "02234567"
        assert context[2].para_id == "03234567"
    
    def test_add_reply_via_model(self):
        """Add reply through DocumentModel convenience method."""
        model = DocumentModel()
        
        para = Paragraph(
            para_id="PARA0001",
            text_id="ABCDEF12",
            runs=[Run(text="Hello world")]
        )
        model.body.add_element(para)
        
        # Add root comment
        comment = Comment(
            comment_id="1",
            para_id="01234567",
            text="Please fix this",
            author="Reviewer",
            anchor=CommentAnchor(
                comment_id="1",
                para_id="PARA0001",
                start_offset=0,
                end_offset=5
            )
        )
        model.comments.add_comment(comment)
        
        # Add reply via model
        reply = model.add_reply(
            parent_comment_id="1",
            text="Fixed!",
            author="Stet"
        )
        
        assert reply is not None
        assert model.comment_count == 2
        assert model.thread_count == 1
        assert model.is_dirty


class TestDocumentBody:
    """Tests for DocumentBody."""
    
    def test_iter_paragraphs_includes_tables(self):
        """iter_paragraphs yields paragraphs from tables."""
        body = DocumentBody()
        
        # Add regular paragraph
        para1 = Paragraph(para_id="01234567", text_id="A1234567", runs=[Run(text="Para 1")])
        body.add_element(para1)
        
        # Add table with paragraphs
        table = Table(rows=[
            [Paragraph(para_id="11234567", text_id="B1234567", runs=[Run(text="Cell 1")])],
            [Paragraph(para_id="21234567", text_id="C1234567", runs=[Run(text="Cell 2")])]
        ])
        body.add_element(table)
        
        # Add another paragraph
        para2 = Paragraph(para_id="31234567", text_id="D1234567", runs=[Run(text="Para 2")])
        body.add_element(para2)
        
        all_paras = list(body.iter_paragraphs())
        assert len(all_paras) == 4
        assert all_paras[0].para_id == "01234567"
        assert all_paras[1].para_id == "11234567"
        assert all_paras[2].para_id == "21234567"
        assert all_paras[3].para_id == "31234567"
    
    def test_get_element_by_para_id_finds_table_cells(self):
        """Can find paragraphs inside tables by para_id."""
        body = DocumentBody()
        
        table = Table(rows=[
            [Paragraph(para_id="11234567", text_id="B1234567", runs=[Run(text="Cell 1")])]
        ])
        body.add_element(table)
        
        para = body.get_element_by_para_id("11234567")
        assert para is not None
        assert para.plain_text == "Cell 1"
