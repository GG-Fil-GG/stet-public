"""
Tests for edit operations in the Document Model.

Phase 4 of DOM Migration: Edit Operations.
"""

import pytest
from pathlib import Path
from datetime import datetime

from src.document_model import (
    DocumentModel,
    DocumentBody,
    Paragraph,
    Run,
    RunFormatting,
    CommentStore,
    Comment,
    CommentAnchor,
    CommentThread,
    RevisionStore,
    PlainTextView,
    PlainTextViewBuilder,
    parse_docx,
)
from src.document_model.edits import DocumentEdit, EditType
from src.document_model.paragraph import RevisionType
from tests.test_support import SYNTHETIC_TEST_DATA_DIR


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def simple_paragraph():
    """Create a simple paragraph with text."""
    return Paragraph(
        para_id="PARA0001",
        text_id="TEXT0001",
        runs=[Run(text="Hello world, this is a test paragraph.")],
        index=0
    )


@pytest.fixture
def paragraph_with_runs():
    """Create a paragraph with multiple runs."""
    return Paragraph(
        para_id="PARA0002",
        text_id="TEXT0002",
        runs=[
            Run(text="Bold text", formatting=RunFormatting(bold=True), start_offset=0),
            Run(text=" and ", formatting=RunFormatting(), start_offset=9),
            Run(text="italic text", formatting=RunFormatting(italic=True), start_offset=14),
        ],
        index=0
    )


@pytest.fixture
def model_with_comment():
    """Create a model with a paragraph and a comment anchored to it."""
    model = DocumentModel()
    
    # Add paragraph with text
    para = Paragraph(
        para_id="PARA0001",
        text_id="TEXT0001",
        runs=[Run(text="The quick brown fox jumps over the lazy dog.")],
        index=0
    )
    model.body.add_element(para)
    
    # Add comment anchored to "quick brown fox" (positions 4-19)
    comment = Comment(
        comment_id="0",
        para_id="COMMENT_PARA_0",
        author="Test Author",
        author_initials="TA",
        text="This is a comment about the fox",
        anchor=CommentAnchor(
            comment_id="0",
            para_id="PARA0001",
            start_offset=4,    # Start of "quick"
            end_offset=19     # End of "fox"
        )
    )
    model.comments.comments["0"] = comment
    model.comments._by_para_id["COMMENT_PARA_0"] = comment
    model.comments.threads["0"] = CommentThread(thread_id="0", root=comment)
    
    return model


@pytest.fixture
def model_with_multiple_paragraphs():
    """Create a model with multiple paragraphs."""
    model = DocumentModel()
    
    for i in range(5):
        para = Paragraph(
            para_id=f"PARA{i:04X}",
            text_id=f"TEXT{i:04X}",
            runs=[Run(text=f"This is paragraph {i}. It has some text content.")],
            index=i
        )
        model.body.add_element(para)
    
    return model


# =============================================================================
# Test DocumentEdit Creation
# =============================================================================

class TestDocumentEditCreation:
    """Tests for DocumentEdit factory methods."""
    
    def test_create_insert_edit(self):
        """Test creating an insert edit."""
        edit = DocumentEdit.insert(
            para_id="PARA0001",
            position=10,
            text="inserted ",
            author="Test"
        )
        
        assert edit.edit_type == EditType.INSERT
        assert edit.para_id == "PARA0001"
        assert edit.start_offset == 10
        assert edit.end_offset == 10  # Insert has same start/end
        assert edit.text == "inserted "
        assert edit.is_insert
        assert not edit.is_delete
    
    def test_create_delete_edit(self):
        """Test creating a delete edit."""
        edit = DocumentEdit.delete(
            para_id="PARA0001",
            start=10,
            end=20,
            author="Test"
        )
        
        assert edit.edit_type == EditType.DELETE
        assert edit.start_offset == 10
        assert edit.end_offset == 20
        assert edit.deletion_length == 10
        assert edit.is_delete
    
    def test_create_replace_edit(self):
        """Test creating a replace edit."""
        edit = DocumentEdit.replace(
            para_id="PARA0001",
            start=10,
            end=15,
            new_text="replacement",
            author="Test"
        )
        
        assert edit.edit_type == EditType.REPLACE
        assert edit.deletion_length == 5
        assert edit.insertion_length == 11
        assert edit.net_length_change == 6  # 11 - 5
        assert edit.is_replace
    
    def test_net_length_change(self):
        """Test net_length_change calculation."""
        # Insert adds text
        insert = DocumentEdit.insert("PARA", 0, "hello", "Test")
        assert insert.net_length_change == 5
        
        # Delete removes text
        delete = DocumentEdit.delete("PARA", 0, 10, "Test")
        assert delete.net_length_change == -10
        
        # Replace: 5 chars removed, 8 added
        replace = DocumentEdit.replace("PARA", 0, 5, "12345678", "Test")
        assert replace.net_length_change == 3
    
    def test_edit_validation(self):
        """Test edit validation."""
        # Valid edit
        edit = DocumentEdit.insert("PARA", 0, "text", "Test")
        assert edit.validate() is True
        
        # Invalid: no para_id
        with pytest.raises(ValueError, match="para_id is required"):
            DocumentEdit.insert("", 0, "text", "Test").validate()
        
        # Invalid: negative offset
        with pytest.raises(ValueError, match="start_offset cannot be negative"):
            DocumentEdit(
                edit_type=EditType.INSERT,
                para_id="PARA",
                start_offset=-1,
                text="text"
            ).validate()
        
        # Invalid: insert without text
        with pytest.raises(ValueError, match="INSERT edit requires text"):
            DocumentEdit.insert("PARA", 0, "", "Test").validate()


# =============================================================================
# Test Paragraph Text Operations
# =============================================================================

class TestParagraphTextOperations:
    """Tests for paragraph text insertion and deletion."""
    
    def test_insert_at_beginning(self, simple_paragraph):
        """Test inserting text at the beginning."""
        simple_paragraph.insert_text(0, "START ")
        assert simple_paragraph.plain_text.startswith("START Hello")
    
    def test_insert_in_middle(self, simple_paragraph):
        """Test inserting text in the middle."""
        simple_paragraph.insert_text(6, "beautiful ")
        assert "beautiful world" in simple_paragraph.plain_text
    
    def test_insert_at_end(self, simple_paragraph):
        """Test inserting text at the end."""
        simple_paragraph.insert_text(len(simple_paragraph.plain_text), " END")
        assert simple_paragraph.plain_text.endswith(" END")
    
    def test_delete_from_beginning(self, simple_paragraph):
        """Test deleting text from the beginning."""
        deleted = simple_paragraph.delete_text(0, 6)
        assert deleted == "Hello "
        assert simple_paragraph.plain_text.startswith("world")
    
    def test_delete_from_middle(self, simple_paragraph):
        """Test deleting text from the middle."""
        original = simple_paragraph.plain_text
        deleted = simple_paragraph.delete_text(5, 11)
        assert deleted == " world"
        assert " world" not in simple_paragraph.plain_text
    
    def test_delete_from_end(self, simple_paragraph):
        """Test deleting text from the end."""
        original = simple_paragraph.plain_text
        deleted = simple_paragraph.delete_text(len(original) - 10, len(original))
        assert deleted == "paragraph."
        assert not simple_paragraph.plain_text.endswith("paragraph.")
    
    def test_insert_splits_run(self, paragraph_with_runs):
        """Test that inserting in middle of run splits it."""
        # Insert in middle of "Bold text"
        paragraph_with_runs.insert_text(4, "INSERTED ", RunFormatting())
        assert "BoldINSERTED  text" in paragraph_with_runs.plain_text
    
    def test_delete_across_runs(self, paragraph_with_runs):
        """Test deleting across run boundaries."""
        # Delete "text and it" which spans runs
        deleted = paragraph_with_runs.delete_text(5, 16)
        assert "and " in deleted


# =============================================================================
# Test Apply Edit to Model
# =============================================================================

class TestApplyEditToModel:
    """Tests for applying edits to DocumentModel."""
    
    def test_apply_insert_edit(self, model_with_comment):
        """Test applying an insert edit."""
        original_text = model_with_comment.get_paragraph("PARA0001").plain_text
        
        edit = DocumentEdit.insert(
            para_id="PARA0001",
            position=0,
            text="START ",
            author="Test",
            track_change=True
        )
        
        success = model_with_comment.apply_edit(edit)
        
        assert success
        para = model_with_comment.get_paragraph("PARA0001")
        assert para.plain_text.startswith("START The")
        assert model_with_comment.is_dirty
    
    def test_apply_delete_edit(self, model_with_comment):
        """Test applying a delete edit."""
        edit = DocumentEdit.delete(
            para_id="PARA0001",
            start=0,
            end=4,  # Delete "The "
            author="Test",
            track_change=True
        )
        
        success = model_with_comment.apply_edit(edit)
        
        assert success
        para = model_with_comment.get_paragraph("PARA0001")
        assert para.plain_text.startswith("quick")
    
    def test_apply_replace_edit(self, model_with_comment):
        """Test applying a replace edit."""
        edit = DocumentEdit.replace(
            para_id="PARA0001",
            start=4,
            end=9,  # Replace "quick"
            new_text="slow",
            author="Test",
            track_change=True
        )
        
        success = model_with_comment.apply_edit(edit)
        
        assert success
        para = model_with_comment.get_paragraph("PARA0001")
        assert "slow brown fox" in para.plain_text
    
    def test_revision_created_on_insert(self, model_with_comment):
        """Test that insert creates a revision when track_change=True."""
        edit = DocumentEdit.insert(
            para_id="PARA0001",
            position=0,
            text="START ",
            author="TestAuthor",
            track_change=True
        )
        
        model_with_comment.apply_edit(edit)
        
        assert len(model_with_comment.revisions.revisions) == 1
        rev = list(model_with_comment.revisions.revisions.values())[0]
        assert rev.revision_type == RevisionType.INSERTION
        assert rev.text == "START "
        assert rev.author == "TestAuthor"
    
    def test_no_revision_when_track_change_false(self, model_with_comment):
        """Test that no revision is created when track_change=False."""
        edit = DocumentEdit.insert(
            para_id="PARA0001",
            position=0,
            text="START ",
            author="Test",
            track_change=False
        )
        
        model_with_comment.apply_edit(edit)
        
        assert len(model_with_comment.revisions.revisions) == 0


# =============================================================================
# Test Anchor Adjustment
# =============================================================================

class TestAnchorAdjustment:
    """Tests for automatic anchor adjustment after edits."""
    
    def test_insert_before_anchor_shifts_anchor(self, model_with_comment):
        """Test that inserting before anchor shifts it."""
        # Comment anchor is at 4-19 ("quick brown fox")
        original_start = model_with_comment.comments.comments["0"].anchor.start_offset
        original_end = model_with_comment.comments.comments["0"].anchor.end_offset
        
        # Insert at position 0 (before anchor)
        edit = DocumentEdit.insert(
            para_id="PARA0001",
            position=0,
            text="START ",  # 6 chars
            author="Test",
            track_change=False
        )
        
        model_with_comment.apply_edit(edit)
        
        # Anchor should shift by 6
        anchor = model_with_comment.comments.comments["0"].anchor
        assert anchor.start_offset == original_start + 6
        assert anchor.end_offset == original_end + 6
    
    def test_insert_after_anchor_no_shift(self, model_with_comment):
        """Test that inserting after anchor doesn't shift it."""
        # Comment anchor is at 4-19 ("quick brown fox")
        original_start = model_with_comment.comments.comments["0"].anchor.start_offset
        original_end = model_with_comment.comments.comments["0"].anchor.end_offset
        
        # Insert at position 30 (after anchor)
        edit = DocumentEdit.insert(
            para_id="PARA0001",
            position=30,
            text=" INSERTED",
            author="Test",
            track_change=False
        )
        
        model_with_comment.apply_edit(edit)
        
        # Anchor should not shift
        anchor = model_with_comment.comments.comments["0"].anchor
        assert anchor.start_offset == original_start
        assert anchor.end_offset == original_end
    
    def test_delete_before_anchor_shifts_anchor(self, model_with_comment):
        """Test that deleting before anchor shifts it."""
        # Comment anchor is at 4-19 ("quick brown fox")
        original_start = model_with_comment.comments.comments["0"].anchor.start_offset
        original_end = model_with_comment.comments.comments["0"].anchor.end_offset
        
        # Delete "The " (0-4) which is before anchor
        edit = DocumentEdit.delete(
            para_id="PARA0001",
            start=0,
            end=4,
            author="Test",
            track_change=False
        )
        
        model_with_comment.apply_edit(edit)
        
        # Anchor should shift by -4
        anchor = model_with_comment.comments.comments["0"].anchor
        assert anchor.start_offset == original_start - 4
        assert anchor.end_offset == original_end - 4


# =============================================================================
# Test PlainTextView.compute_edits()
# =============================================================================

class TestComputeEdits:
    """Tests for computing edits from text diffs."""
    
    def test_compute_simple_insert(self, model_with_multiple_paragraphs):
        """Test computing edits for a simple insertion."""
        builder = PlainTextViewBuilder(model_with_multiple_paragraphs)
        view = builder.build_for_paragraphs(["PARA0000"])
        
        original = view.text
        revised = original.replace("paragraph 0", "paragraph ZERO")
        
        edits = view.compute_edits(revised, author="Test", track_changes=True)
        
        assert len(edits) >= 1
        # Should have delete "0" and insert "ZERO" (or combined)
    
    def test_compute_simple_delete(self, model_with_multiple_paragraphs):
        """Test computing edits for a simple deletion."""
        builder = PlainTextViewBuilder(model_with_multiple_paragraphs)
        view = builder.build_for_paragraphs(["PARA0000"])
        
        original = view.text
        revised = original.replace(". It has", ". Has")  # Delete " It"
        
        edits = view.compute_edits(revised, author="Test", track_changes=True)
        
        assert len(edits) >= 1
    
    def test_compute_no_changes(self, model_with_multiple_paragraphs):
        """Test computing edits when there are no changes."""
        builder = PlainTextViewBuilder(model_with_multiple_paragraphs)
        view = builder.build_for_paragraphs(["PARA0000"])
        
        edits = view.compute_edits(view.text, author="Test")
        
        assert len(edits) == 0
    
    def test_compute_edits_for_paragraph(self, model_with_multiple_paragraphs):
        """Test computing edits for a single paragraph."""
        builder = PlainTextViewBuilder(model_with_multiple_paragraphs)
        view = builder.build_for_paragraphs(["PARA0001"])
        
        original = "This is paragraph 1. It has some text content."
        revised = "This is modified paragraph 1. It has different text content."
        
        edits = view.compute_edits_for_paragraph(
            "PARA0001", original, revised, author="Test"
        )
        
        assert len(edits) > 0


# =============================================================================
# Test Full Edit Workflow
# =============================================================================

class TestFullEditWorkflow:
    """Tests for the complete edit workflow."""
    
    def test_compute_and_apply_edits(self, model_with_multiple_paragraphs):
        """Test computing edits and applying them to the model."""
        para_id = "PARA0000"
        original_para = model_with_multiple_paragraphs.get_paragraph(para_id)
        original_text = original_para.plain_text
        
        # Create revised text - use a simpler edit (single word at end)
        revised_text = original_text.replace("content.", "stuff.")
        
        # Compute edits
        builder = PlainTextViewBuilder(model_with_multiple_paragraphs)
        view = builder.build_for_paragraphs([para_id])
        
        edits = view.compute_edits_for_paragraph(
            para_id, original_text, revised_text, author="Test", track_changes=True
        )
        
        # Apply edits in reverse order (from end to beginning) to avoid position shifts
        edits_sorted = sorted(edits, key=lambda e: e.start_offset, reverse=True)
        for edit in edits_sorted:
            model_with_multiple_paragraphs.apply_edit(edit)
        
        # Verify result
        modified_para = model_with_multiple_paragraphs.get_paragraph(para_id)
        assert "stuff." in modified_para.plain_text
        assert "content." not in modified_para.plain_text
    
    def test_multiple_edits_preserve_anchor(self, model_with_comment):
        """Test that multiple edits correctly preserve anchor positions."""
        para_id = "PARA0001"
        original_para = model_with_comment.get_paragraph(para_id)
        
        # Original: "The quick brown fox jumps over the lazy dog."
        # Anchor is on "quick brown fox" (4-19)
        
        # Replace "quick" with "slow" (makes text shorter by 1)
        edit1 = DocumentEdit.replace(
            para_id=para_id,
            start=4,
            end=9,
            new_text="slow",
            author="Test",
            track_change=False
        )
        model_with_comment.apply_edit(edit1)
        
        # Check anchor adjusted
        anchor = model_with_comment.comments.comments["0"].anchor
        # Anchor end should shift by -1
        assert anchor.start_offset == 4
        assert anchor.end_offset == 18  # Was 19, now 18


# =============================================================================
# Integration Tests with Real Documents
# =============================================================================

class TestIntegrationWithRealDocuments:
    """Integration tests using synthetic DOCX files."""

    def test_compute_and_apply_edits_real_doc(self):
        """Test edit workflow with a real document."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        
        if model.thread_count == 0:
            pytest.skip("Document has no comment threads")
        
        # Get a thread and its target paragraph
        thread_id = list(model.comments.threads.keys())[0]
        thread = model.comments.threads[thread_id]
        
        if not thread.root.anchor:
            pytest.skip("Thread has no anchor")
        
        para_id = thread.root.anchor.para_id
        para = model.get_paragraph(para_id)
        
        if not para:
            pytest.skip("Paragraph not found")
        
        original_text = para.plain_text
        original_length = len(original_text)
        
        # Make a simple edit
        revised_text = original_text.replace("the", "THE")
        
        if revised_text == original_text:
            pytest.skip("No 'the' in paragraph to replace")
        
        # Compute and apply edits
        builder = PlainTextViewBuilder(model)
        view = builder.build_for_paragraphs([para_id])
        
        edits = view.compute_edits_for_paragraph(
            para_id, original_text, revised_text, author="Test", track_changes=True
        )
        
        for edit in edits:
            model.apply_edit(edit)
        
        # Verify changes
        modified_para = model.get_paragraph(para_id)
        assert "THE" in modified_para.plain_text
        
        # Verify revisions were recorded
        assert len(model.revisions.revisions) > 0


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
