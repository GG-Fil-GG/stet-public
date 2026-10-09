"""
Tests for Phase 3: Paragraph Structural Changes

Tests cover:
- DocumentBody manipulation methods (insert_element_at, remove_element, get_element_index)
- New EditTypes (INSERT_PARAGRAPH, DELETE_PARAGRAPH)
- Paragraph splitting and merging
- Anchor migration during structural changes
"""

import pytest
from src.document_model import (
    DocumentModel,
    DocumentBody,
    Paragraph,
    Run,
    DocumentEdit,
    EditType,
    Comment,
    CommentAnchor,
    generate_valid_para_id,
    is_valid_para_id,
)


# =============================================================================
# HELPERS
# =============================================================================

def create_test_model_with_paragraphs(texts: list[str]) -> DocumentModel:
    """Create a model with paragraphs containing the given texts."""
    model = DocumentModel()
    for i, text in enumerate(texts):
        para_id = f"PARA{i:04d}"
        text_id = f"TEXT{i:04d}"
        para = Paragraph(
            para_id=para_id,
            text_id=text_id,
            runs=[Run(text=text)] if text else [],
            index=i
        )
        model.body.add_element(para)
    return model


def add_comment_with_anchor(
    model: DocumentModel,
    comment_id: str,
    para_id: str,
    start_offset: int,
    end_offset: int,
    end_para_id: str = None,
) -> Comment:
    """Add a comment with an anchor to the model."""
    anchor = CommentAnchor(
        comment_id=comment_id,
        para_id=para_id,
        start_offset=start_offset,
        end_offset=end_offset,
        end_para_id=end_para_id,
    )
    comment = Comment(
        comment_id=comment_id,
        para_id=para_id,  # Comment also requires para_id for internal tracking
        text="Test comment",
        author="Test",
        anchor=anchor,
    )
    model.comments.comments[comment_id] = comment
    return comment


# =============================================================================
# DOCUMENT BODY MANIPULATION TESTS
# =============================================================================

class TestDocumentBodyInsertElementAt:
    """Tests for DocumentBody.insert_element_at()"""
    
    def test_insert_at_beginning(self):
        """Insert element at index 0."""
        model = create_test_model_with_paragraphs(["First", "Second"])

        new_para = Paragraph(para_id="NEW00001", text_id="TEXTNEW1", runs=[Run(text="New")])
        model.body.insert_element_at(0, new_para)

        # Check order
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 3
        assert paragraphs[0].plain_text == "New"
        assert paragraphs[1].plain_text == "First"
        assert paragraphs[2].plain_text == "Second"
        
        # Check indices are updated
        assert paragraphs[0].index == 0
        assert paragraphs[1].index == 1
        assert paragraphs[2].index == 2
    
    def test_insert_in_middle(self):
        """Insert element in the middle."""
        model = create_test_model_with_paragraphs(["First", "Second", "Third"])

        new_para = Paragraph(para_id="NEW00001", text_id="TEXTNEW1", runs=[Run(text="Middle")])
        model.body.insert_element_at(1, new_para)
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 4
        assert paragraphs[0].plain_text == "First"
        assert paragraphs[1].plain_text == "Middle"
        assert paragraphs[2].plain_text == "Second"
        assert paragraphs[3].plain_text == "Third"
    
    def test_insert_at_end(self):
        """Insert element at the end."""
        model = create_test_model_with_paragraphs(["First", "Second"])

        new_para = Paragraph(para_id="NEW00001", text_id="TEXTNEW1", runs=[Run(text="Last")])
        model.body.insert_element_at(2, new_para)
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 3
        assert paragraphs[2].plain_text == "Last"
    
    def test_insert_updates_para_id_index(self):
        """Inserted element is findable by para_id."""
        model = create_test_model_with_paragraphs(["First"])

        new_para = Paragraph(para_id="NEW00001", text_id="TEXTNEW1", runs=[Run(text="New")])
        model.body.insert_element_at(0, new_para)

        found = model.body.get_element_by_para_id("NEW00001")
        assert found is not None
        assert found.plain_text == "New"


class TestDocumentBodyRemoveElement:
    """Tests for DocumentBody.remove_element()"""
    
    def test_remove_paragraph(self):
        """Remove a paragraph by para_id."""
        model = create_test_model_with_paragraphs(["First", "Second", "Third"])
        
        removed = model.body.remove_element("PARA0001")  # "Second"
        
        assert removed is not None
        assert removed.plain_text == "Second"
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 2
        assert paragraphs[0].plain_text == "First"
        assert paragraphs[1].plain_text == "Third"
    
    def test_remove_updates_indices(self):
        """Removing element updates subsequent indices."""
        model = create_test_model_with_paragraphs(["First", "Second", "Third"])
        
        model.body.remove_element("PARA0000")  # Remove first
        
        paragraphs = list(model.body.iter_paragraphs())
        assert paragraphs[0].index == 0
        assert paragraphs[1].index == 1
    
    def test_remove_updates_para_id_index(self):
        """Removed element is no longer findable by para_id."""
        model = create_test_model_with_paragraphs(["First", "Second"])
        
        model.body.remove_element("PARA0000")
        
        found = model.body.get_element_by_para_id("PARA0000")
        assert found is None
    
    def test_remove_nonexistent_returns_none(self):
        """Removing nonexistent element returns None."""
        model = create_test_model_with_paragraphs(["First"])
        
        removed = model.body.remove_element("NONEXISTENT")
        assert removed is None


class TestDocumentBodyGetElementIndex:
    """Tests for DocumentBody.get_element_index()"""
    
    def test_get_index_of_paragraph(self):
        """Get index of existing paragraph."""
        model = create_test_model_with_paragraphs(["First", "Second", "Third"])
        
        assert model.body.get_element_index("PARA0000") == 0
        assert model.body.get_element_index("PARA0001") == 1
        assert model.body.get_element_index("PARA0002") == 2
    
    def test_get_index_nonexistent_returns_minus_one(self):
        """Nonexistent paragraph returns -1."""
        model = create_test_model_with_paragraphs(["First"])
        
        assert model.body.get_element_index("NONEXISTENT") == -1


# =============================================================================
# EDIT TYPE TESTS
# =============================================================================

class TestInsertParagraphEdit:
    """Tests for INSERT_PARAGRAPH edit type."""
    
    def test_insert_paragraph_edit_creation(self):
        """Create an INSERT_PARAGRAPH edit."""
        edit = DocumentEdit.insert_paragraph(
            text="New paragraph text",
            after_para_id="PARA0000",
            author="Test"
        )
        
        assert edit.edit_type == EditType.INSERT_PARAGRAPH
        assert edit.text == "New paragraph text"
        assert edit.after_para_id == "PARA0000"
        assert edit.author == "Test"
    
    def test_insert_paragraph_at_beginning(self):
        """Insert paragraph at document beginning (after_para_id=None)."""
        edit = DocumentEdit.insert_paragraph(
            text="First paragraph",
            after_para_id=None,
        )
        
        assert edit.after_para_id is None
    
    def test_insert_paragraph_applies_to_model(self):
        """INSERT_PARAGRAPH edit is applied correctly."""
        model = create_test_model_with_paragraphs(["First", "Second"])
        
        edit = DocumentEdit.insert_paragraph(
            text="Middle",
            after_para_id="PARA0000",  # After "First"
            track_change=False
        )
        
        result = model.apply_edit(edit)
        assert result is True
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 3
        assert paragraphs[0].plain_text == "First"
        assert paragraphs[1].plain_text == "Middle"
        assert paragraphs[2].plain_text == "Second"
    
    def test_insert_paragraph_generates_valid_para_id(self):
        """New paragraph gets a valid para_id."""
        model = create_test_model_with_paragraphs(["First"])
        
        edit = DocumentEdit.insert_paragraph(
            text="New",
            after_para_id="PARA0000",
            track_change=False
        )
        
        model.apply_edit(edit)
        
        paragraphs = list(model.body.iter_paragraphs())
        new_para = paragraphs[1]
        
        assert is_valid_para_id(new_para.para_id)


class TestDeleteParagraphEdit:
    """Tests for DELETE_PARAGRAPH edit type."""
    
    def test_delete_paragraph_edit_creation(self):
        """Create a DELETE_PARAGRAPH edit."""
        edit = DocumentEdit.delete_paragraph(
            para_id="PARA0001",
            author="Test"
        )
        
        assert edit.edit_type == EditType.DELETE_PARAGRAPH
        assert edit.para_id == "PARA0001"
        assert edit.author == "Test"
    
    def test_delete_paragraph_applies_to_model(self):
        """DELETE_PARAGRAPH edit is applied correctly."""
        model = create_test_model_with_paragraphs(["First", "Second", "Third"])
        
        edit = DocumentEdit.delete_paragraph(
            para_id="PARA0001",  # "Second"
            track_change=False
        )
        
        result = model.apply_edit(edit)
        assert result is True
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 2
        assert paragraphs[0].plain_text == "First"
        assert paragraphs[1].plain_text == "Third"
    
    def test_delete_nonexistent_returns_false(self):
        """Deleting nonexistent paragraph returns False."""
        model = create_test_model_with_paragraphs(["First"])
        
        edit = DocumentEdit.delete_paragraph(para_id="NONEXISTENT")
        
        result = model.apply_edit(edit)
        assert result is False


# =============================================================================
# PARAGRAPH SPLIT TESTS
# =============================================================================

class TestSplitParagraph:
    """Tests for DocumentModel.split_paragraph()"""
    
    def test_split_creates_two_paragraphs(self):
        """Splitting creates two paragraphs with correct text."""
        model = create_test_model_with_paragraphs(["Hello World"])
        
        new_para_id = model.split_paragraph("PARA0000", 5, track_change=False)
        
        assert new_para_id is not None
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 2
        assert paragraphs[0].plain_text == "Hello"
        assert paragraphs[1].plain_text == " World"
    
    def test_split_new_paragraph_has_valid_id(self):
        """New paragraph from split has valid para_id."""
        model = create_test_model_with_paragraphs(["Hello World"])
        
        new_para_id = model.split_paragraph("PARA0000", 5, track_change=False)
        
        assert is_valid_para_id(new_para_id)
    
    def test_split_at_invalid_position_returns_none(self):
        """Splitting at position 0 or end returns None."""
        model = create_test_model_with_paragraphs(["Hello"])
        
        # At beginning
        result = model.split_paragraph("PARA0000", 0, track_change=False)
        assert result is None
        
        # At end
        result = model.split_paragraph("PARA0000", 5, track_change=False)
        assert result is None
        
        # Beyond end
        result = model.split_paragraph("PARA0000", 10, track_change=False)
        assert result is None
    
    def test_split_anchor_before_split_stays(self):
        """Anchor entirely before split point stays in original paragraph."""
        model = create_test_model_with_paragraphs(["Hello World"])
        add_comment_with_anchor(model, "C1", "PARA0000", 0, 5)  # "Hello"
        
        model.split_paragraph("PARA0000", 6, track_change=False)  # Split after "Hello "
        
        comment = model.comments.comments["C1"]
        assert comment.anchor.para_id == "PARA0000"
        assert comment.anchor.start_offset == 0
        assert comment.anchor.end_offset == 5
    
    def test_split_anchor_after_split_migrates(self):
        """Anchor entirely after split point migrates to new paragraph."""
        model = create_test_model_with_paragraphs(["Hello World"])
        add_comment_with_anchor(model, "C1", "PARA0000", 6, 11)  # "World"
        
        new_para_id = model.split_paragraph("PARA0000", 6, track_change=False)
        
        comment = model.comments.comments["C1"]
        assert comment.anchor.para_id == new_para_id
        assert comment.anchor.start_offset == 0  # 6 - 6 = 0
        assert comment.anchor.end_offset == 5    # 11 - 6 = 5
    
    def test_split_anchor_spanning_becomes_multi_paragraph(self):
        """Anchor spanning split point becomes multi-paragraph anchor."""
        model = create_test_model_with_paragraphs(["Hello World"])
        add_comment_with_anchor(model, "C1", "PARA0000", 3, 8)  # "lo Wo"
        
        new_para_id = model.split_paragraph("PARA0000", 6, track_change=False)
        
        comment = model.comments.comments["C1"]
        assert comment.anchor.para_id == "PARA0000"
        assert comment.anchor.start_offset == 3
        assert comment.anchor.end_para_id == new_para_id
        assert comment.anchor.end_offset == 2  # 8 - 6 = 2


# =============================================================================
# PARAGRAPH MERGE TESTS
# =============================================================================

class TestMergeParagraphs:
    """Tests for DocumentModel.merge_paragraphs()"""
    
    def test_merge_combines_text(self):
        """Merging combines text from both paragraphs."""
        model = create_test_model_with_paragraphs(["Hello", " World"])
        
        result = model.merge_paragraphs("PARA0000", "PARA0001", track_change=False)
        
        assert result is True
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 1
        assert paragraphs[0].plain_text == "Hello World"
    
    def test_merge_non_adjacent_returns_false(self):
        """Merging non-adjacent paragraphs returns False."""
        model = create_test_model_with_paragraphs(["First", "Middle", "Last"])
        
        result = model.merge_paragraphs("PARA0000", "PARA0002", track_change=False)
        
        assert result is False
    
    def test_merge_anchor_on_second_migrates(self):
        """Anchor on second paragraph migrates to first with offset adjustment."""
        model = create_test_model_with_paragraphs(["Hello", " World"])
        add_comment_with_anchor(model, "C1", "PARA0001", 1, 6)  # "World" in second para
        
        model.merge_paragraphs("PARA0000", "PARA0001", track_change=False)
        
        comment = model.comments.comments["C1"]
        assert comment.anchor.para_id == "PARA0000"
        assert comment.anchor.start_offset == 6   # 1 + 5 (len of "Hello")
        assert comment.anchor.end_offset == 11    # 6 + 5
    
    def test_merge_multi_para_anchor_collapses(self):
        """Multi-paragraph anchor spanning merged paragraphs collapses to single."""
        model = create_test_model_with_paragraphs(["Hello", " World"])
        add_comment_with_anchor(model, "C1", "PARA0000", 3, 3, end_para_id="PARA0001")
        model.comments.comments["C1"].anchor.end_offset = 3  # "lo" in first, " Wo" in second
        
        model.merge_paragraphs("PARA0000", "PARA0001", track_change=False)
        
        comment = model.comments.comments["C1"]
        assert comment.anchor.para_id == "PARA0000"
        assert comment.anchor.end_para_id is None  # Collapsed to single
        assert comment.anchor.start_offset == 3
        assert comment.anchor.end_offset == 8  # 3 + 5 (len of "Hello")


# =============================================================================
# ANCHOR MIGRATION FOR DELETE TESTS
# =============================================================================

class TestAnchorMigrationForDelete:
    """Tests for anchor migration when paragraphs are deleted."""
    
    def test_delete_migrates_anchor_to_next(self):
        """Anchor on deleted paragraph migrates to next paragraph."""
        model = create_test_model_with_paragraphs(["First", "Second", "Third"])
        add_comment_with_anchor(model, "C1", "PARA0001", 0, 6)  # On "Second"
        
        edit = DocumentEdit.delete_paragraph(para_id="PARA0001", track_change=False)
        model.apply_edit(edit)
        
        comment = model.comments.comments["C1"]
        assert comment.anchor.para_id == "PARA0002"  # Migrated to "Third"
        assert comment.anchor.start_offset == 0
        assert comment.anchor.end_offset == 0
    
    def test_delete_last_migrates_anchor_to_previous(self):
        """Anchor on last deleted paragraph migrates to previous."""
        model = create_test_model_with_paragraphs(["First", "Second"])
        add_comment_with_anchor(model, "C1", "PARA0001", 0, 6)  # On "Second"
        
        edit = DocumentEdit.delete_paragraph(para_id="PARA0001", track_change=False)
        model.apply_edit(edit)
        
        comment = model.comments.comments["C1"]
        assert comment.anchor.para_id == "PARA0000"  # Migrated to "First"
        # Offset should be at end of "First" paragraph
        assert comment.anchor.start_offset == 5
        assert comment.anchor.end_offset == 5


# =============================================================================
# PARA ID GENERATION TESTS
# =============================================================================

class TestParaIdGeneration:
    """Tests for para_id generation."""
    
    def test_generated_id_is_valid(self):
        """Generated para_id passes validation."""
        for _ in range(100):
            para_id = generate_valid_para_id(set())
            assert is_valid_para_id(para_id), f"Invalid para_id: {para_id}"
    
    def test_generated_id_first_char_is_0_to_7(self):
        """Generated para_id has first character 0-7."""
        for _ in range(100):
            para_id = generate_valid_para_id(set())
            assert para_id[0] in "01234567", f"Invalid first char: {para_id[0]}"
    
    def test_generated_id_is_unique(self):
        """Generated para_id avoids existing IDs."""
        existing = {"00000000", "00000001", "00000002"}
        
        for _ in range(100):
            para_id = generate_valid_para_id(existing)
            assert para_id not in existing
    
    def test_generated_id_is_8_chars_uppercase_hex(self):
        """Generated para_id is 8 uppercase hex characters."""
        for _ in range(100):
            para_id = generate_valid_para_id(set())
            assert len(para_id) == 8
            assert para_id == para_id.upper()
            int(para_id, 16)  # Should not raise


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestStructuralChangesIntegration:
    """Integration tests for structural changes."""
    
    def test_split_then_merge_roundtrip(self):
        """Split then merge returns to original state."""
        model = create_test_model_with_paragraphs(["Hello World"])
        
        # Split
        new_para_id = model.split_paragraph("PARA0000", 5, track_change=False)
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 2
        
        # Merge back
        model.merge_paragraphs("PARA0000", new_para_id, track_change=False)
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 1
        assert paragraphs[0].plain_text == "Hello World"
    
    def test_multiple_inserts_preserve_order(self):
        """Multiple paragraph inserts maintain correct order."""
        model = create_test_model_with_paragraphs(["First"])
        
        # Insert after first
        edit1 = DocumentEdit.insert_paragraph(text="Second", after_para_id="PARA0000", track_change=False)
        model.apply_edit(edit1)
        
        # Get the new paragraph's ID
        paras = list(model.body.iter_paragraphs())
        second_id = paras[1].para_id
        
        # Insert after second
        edit2 = DocumentEdit.insert_paragraph(text="Third", after_para_id=second_id, track_change=False)
        model.apply_edit(edit2)
        
        paragraphs = list(model.body.iter_paragraphs())
        assert len(paragraphs) == 3
        assert paragraphs[0].plain_text == "First"
        assert paragraphs[1].plain_text == "Second"
        assert paragraphs[2].plain_text == "Third"
