"""
Tests for Phase 4: Plain Text → DOM Conversion with Structural Support.

Tests the unified plain text conversion functions:
- compute_structural_edits()
- apply_revision_from_plain_text()

Coverage:
- Same paragraph count with content changes
- Paragraph splitting (one → many)
- Paragraph merging (many → one)
- Mixed structural changes
- Empty paragraph handling
"""

import pytest
from typing import List, Dict, Optional

from src.document_model import DocumentModel
from src.document_model.model import DocumentBody
from src.document_model.paragraph import Paragraph, Run
from src.document_model.edits import DocumentEdit, EditType
from src.document_model.utils import generate_valid_para_id, generate_hex_id
from src.document_model.plain_text import (
    compute_structural_edits,
    apply_revision_from_plain_text,
    _align_paragraphs,
    _compute_within_paragraph_edits,
)


# =============================================================================
# Test Fixtures
# =============================================================================

def create_test_paragraph(text: str, para_id: str = None, index: int = 0) -> Paragraph:
    """Helper to create a test paragraph with given text."""
    if para_id is None:
        para_id = generate_valid_para_id(set())
    text_id = generate_hex_id(set())
    
    run = Run(text=text)
    return Paragraph(
        para_id=para_id,
        text_id=text_id,
        runs=[run],
        index=index
    )


def create_test_model_with_paragraphs(texts: List[str]) -> DocumentModel:
    """Create a test model with paragraphs containing the given texts."""
    model = DocumentModel()
    
    existing_ids = set()
    for i, text in enumerate(texts):
        para_id = generate_valid_para_id(existing_ids)
        existing_ids.add(para_id)
        
        para = create_test_paragraph(text, para_id=para_id, index=i)
        model.body.elements.append(para)
        model.body._para_id_index[para_id] = para
    
    return model


# =============================================================================
# Tests for compute_structural_edits()
# =============================================================================

class TestComputeStructuralEdits:
    """Tests for the compute_structural_edits function."""
    
    def test_same_count_no_changes(self):
        """Same paragraph count with identical content produces no edits."""
        original = ["Hello world", "Second paragraph"]
        revised = ["Hello world", "Second paragraph"]
        para_ids = ["PARA0001", "PARA0002"]
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        assert len(edits) == 0
    
    def test_same_count_content_changed(self):
        """Same paragraph count with content changes produces REPLACE edits."""
        original = ["Hello world", "Second paragraph"]
        revised = ["Hello universe", "Second paragraph"]
        para_ids = ["PARA0001", "PARA0002"]
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        # Should have one REPLACE edit for the first paragraph
        assert len(edits) == 1
        assert edits[0].para_id == "PARA0001"
        assert edits[0].edit_type == EditType.REPLACE
        assert edits[0].text == "Hello universe"
    
    def test_same_count_both_changed(self):
        """Same paragraph count with both paragraphs changed."""
        original = ["Hello world", "Second paragraph"]
        revised = ["Hello universe", "Third paragraph"]
        para_ids = ["PARA0001", "PARA0002"]
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        # Should have two REPLACE edits, one for each paragraph
        assert len(edits) == 2
        
        para_ids_in_edits = {edit.para_id for edit in edits}
        assert "PARA0001" in para_ids_in_edits
        assert "PARA0002" in para_ids_in_edits
        
        for edit in edits:
            assert edit.edit_type == EditType.REPLACE
    
    def test_split_one_to_two(self):
        """One paragraph split into two produces structural edits."""
        original = ["Hello world. This is a long paragraph."]
        revised = ["Hello world.", "This is a long paragraph."]
        para_ids = ["PARA0001"]
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        # Should have at least one INSERT_PARAGRAPH edit
        insert_para_edits = [e for e in edits if e.edit_type == EditType.INSERT_PARAGRAPH]
        assert len(insert_para_edits) >= 1
        
        # The new paragraph should have content
        for edit in insert_para_edits:
            assert edit.text is not None
            assert len(edit.text) > 0
    
    def test_merge_two_to_one(self):
        """Two paragraphs merged into one produces structural edits."""
        original = ["Hello world.", "This continues."]
        revised = ["Hello world. This continues."]
        para_ids = ["PARA0001", "PARA0002"]
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        # Should have at least one DELETE_PARAGRAPH edit
        delete_para_edits = [e for e in edits if e.edit_type == EditType.DELETE_PARAGRAPH]
        assert len(delete_para_edits) >= 1
    
    def test_insert_new_paragraph(self):
        """Adding a new paragraph in the middle."""
        original = ["First paragraph", "Third paragraph"]
        revised = ["First paragraph", "New middle paragraph", "Third paragraph"]
        para_ids = ["PARA0001", "PARA0002"]
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        # Should have an INSERT_PARAGRAPH edit
        insert_edits = [e for e in edits if e.edit_type == EditType.INSERT_PARAGRAPH]
        assert len(insert_edits) >= 1
        
        # The inserted paragraph should have the new content
        new_contents = [e.text for e in insert_edits]
        assert any("New middle" in text or "middle" in text for text in new_contents if text)
    
    def test_delete_middle_paragraph(self):
        """Deleting a paragraph from the middle."""
        original = ["First paragraph", "Middle to delete", "Third paragraph"]
        revised = ["First paragraph", "Third paragraph"]
        para_ids = ["PARA0001", "PARA0002", "PARA0003"]
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        # Should have a DELETE_PARAGRAPH edit
        delete_edits = [e for e in edits if e.edit_type == EditType.DELETE_PARAGRAPH]
        assert len(delete_edits) >= 1
    
    def test_empty_original(self):
        """Empty original list produces no edits."""
        original = []
        revised = ["New paragraph"]
        para_ids = []
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        # Can't do anything without original paragraphs
        assert len(edits) == 0
    
    def test_empty_revised(self):
        """Empty revised list deletes all paragraphs."""
        original = ["First", "Second"]
        revised = []
        para_ids = ["PARA0001", "PARA0002"]
        
        edits = compute_structural_edits(original, revised, para_ids)
        
        # Should delete all paragraphs
        delete_edits = [e for e in edits if e.edit_type == EditType.DELETE_PARAGRAPH]
        assert len(delete_edits) == 2
    
    def test_thread_id_propagated(self):
        """Thread ID is propagated to all edits."""
        original = ["Hello world"]
        revised = ["Hello universe"]
        para_ids = ["PARA0001"]
        
        edits = compute_structural_edits(
            original, revised, para_ids,
            thread_id="THREAD123"
        )
        
        assert len(edits) > 0
        for edit in edits:
            assert edit.thread_id == "THREAD123"


# =============================================================================
# Tests for _align_paragraphs()
# =============================================================================

class TestAlignParagraphs:
    """Tests for the paragraph alignment algorithm."""
    
    def test_identical_alignment(self):
        """Identical paragraphs align as matches."""
        original = ["First", "Second", "Third"]
        revised = ["First", "Second", "Third"]
        
        alignment = _align_paragraphs(original, revised)
        
        # All should be matches
        match_ops = [a for a in alignment if a['type'] == 'match']
        assert len(match_ops) == 3
    
    def test_content_change_still_matches(self):
        """Similar content aligns as matches despite changes."""
        original = ["Hello world from Earth"]
        revised = ["Hello world from Mars"]
        
        alignment = _align_paragraphs(original, revised)
        
        # Should still match (similar enough)
        match_ops = [a for a in alignment if a['type'] == 'match']
        assert len(match_ops) == 1
    
    def test_complete_replacement_detected(self):
        """Completely different content may not match."""
        original = ["AAAA AAAA AAAA"]
        revised = ["ZZZZ ZZZZ ZZZZ"]
        
        alignment = _align_paragraphs(original, revised)
        
        # Could be match, delete+insert, or other depending on similarity threshold
        assert len(alignment) > 0
    
    def test_insertion_detected(self):
        """New paragraph insertion is detected."""
        original = ["First", "Third"]
        revised = ["First", "Second", "Third"]
        
        alignment = _align_paragraphs(original, revised)
        
        # Should have an insert operation
        insert_ops = [a for a in alignment if a['type'] == 'insert']
        assert len(insert_ops) >= 1
    
    def test_deletion_detected(self):
        """Paragraph deletion is detected."""
        original = ["First", "Second", "Third"]
        revised = ["First", "Third"]
        
        alignment = _align_paragraphs(original, revised)
        
        # Should have a delete operation
        delete_ops = [a for a in alignment if a['type'] == 'delete']
        assert len(delete_ops) >= 1


# =============================================================================
# Tests for apply_revision_from_plain_text()
# =============================================================================

class TestApplyRevisionFromPlainText:
    """Tests for the unified entry point function."""
    
    def test_single_paragraph_no_change(self):
        """Single paragraph with no change produces no edits."""
        model = create_test_model_with_paragraphs(["Hello world"])
        para_id = model.body.elements[0].para_id
        
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[para_id],
            revised_text="Hello world"
        )
        
        assert len(edits) == 0
        assert model.get_paragraph(para_id).plain_text == "Hello world"
    
    def test_single_paragraph_content_change(self):
        """Single paragraph content change is applied."""
        model = create_test_model_with_paragraphs(["Hello world"])
        para_id = model.body.elements[0].para_id
        
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[para_id],
            revised_text="Hello universe"
        )
        
        assert len(edits) > 0
        assert model.get_paragraph(para_id).plain_text == "Hello universe"
    
    def test_multi_paragraph_same_count(self):
        """Multiple paragraphs with same count and changes."""
        model = create_test_model_with_paragraphs(["First para", "Second para"])
        para_ids = [e.para_id for e in model.body.elements]
        
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=para_ids,
            revised_text="Modified first\n\nModified second"
        )
        
        assert len(edits) > 0
        assert model.get_paragraph(para_ids[0]).plain_text == "Modified first"
        assert model.get_paragraph(para_ids[1]).plain_text == "Modified second"
    
    def test_split_paragraph(self):
        """Single paragraph split into two."""
        model = create_test_model_with_paragraphs(["Hello world. More text here."])
        para_id = model.body.elements[0].para_id
        
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[para_id],
            revised_text="Hello world.\n\nMore text here."
        )
        
        # Should have applied edits including an INSERT_PARAGRAPH
        insert_edits = [e for e in edits if e.edit_type == EditType.INSERT_PARAGRAPH]
        assert len(insert_edits) >= 1
        
        # Model should now have 2 paragraphs
        assert len(model.body.elements) == 2
    
    def test_merge_paragraphs(self):
        """Two paragraphs merged into one."""
        model = create_test_model_with_paragraphs(["First part.", "Second part."])
        para_ids = [e.para_id for e in model.body.elements]
        
        original_count = len(model.body.elements)
        
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=para_ids,
            revised_text="First part. Second part."  # Single paragraph
        )
        
        # Should have DELETE_PARAGRAPH edit
        delete_edits = [e for e in edits if e.edit_type == EditType.DELETE_PARAGRAPH]
        assert len(delete_edits) >= 1
        
        # Model should have fewer paragraphs
        assert len(model.body.elements) < original_count
    
    def test_thread_id_in_applied_edits(self):
        """Thread ID is set in applied edits."""
        model = create_test_model_with_paragraphs(["Hello world"])
        para_id = model.body.elements[0].para_id
        
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[para_id],
            revised_text="Hello universe",
            thread_id="TEST_THREAD"
        )
        
        assert len(edits) > 0
        for edit in edits:
            assert edit.thread_id == "TEST_THREAD"
    
    def test_empty_para_ids_returns_empty(self):
        """Empty para_ids list returns empty edits."""
        model = create_test_model_with_paragraphs(["Hello"])
        
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[],
            revised_text="Something"
        )
        
        assert len(edits) == 0
    
    def test_whitespace_handling(self):
        """Extra whitespace in revised text is handled correctly."""
        model = create_test_model_with_paragraphs(["Hello"])
        para_id = model.body.elements[0].para_id
        
        # Revised text with extra whitespace
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[para_id],
            revised_text="  Hello modified  "
        )
        
        # Should handle the whitespace
        assert len(edits) > 0


# =============================================================================
# Tests for within-paragraph edits
# =============================================================================

class TestWithinParagraphEdits:
    """Tests for the _compute_within_paragraph_edits helper."""
    
    def test_no_change(self):
        """Identical text produces no edits."""
        edits = _compute_within_paragraph_edits(
            "PARA001", "Hello world", "Hello world", "Stet", True, None
        )
        
        assert len(edits) == 0
    
    def test_simple_replacement(self):
        """Simple word replacement produces a single REPLACE edit."""
        edits = _compute_within_paragraph_edits(
            "PARA001", "Hello world", "Hello universe", "Stet", True, None
        )
        
        # Should produce a single REPLACE edit
        assert len(edits) == 1
        assert edits[0].edit_type == EditType.REPLACE
        assert edits[0].text == "Hello universe"
    
    def test_insertion_only(self):
        """Adding text produces a REPLACE edit."""
        edits = _compute_within_paragraph_edits(
            "PARA001", "Hello", "Hello world", "Stet", True, None
        )
        
        assert len(edits) == 1
        assert edits[0].edit_type == EditType.REPLACE
        assert edits[0].text == "Hello world"
    
    def test_deletion_only(self):
        """Removing text produces a REPLACE edit."""
        edits = _compute_within_paragraph_edits(
            "PARA001", "Hello world", "Hello", "Stet", True, None
        )
        
        assert len(edits) == 1
        assert edits[0].edit_type == EditType.REPLACE
        assert edits[0].text == "Hello"


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for the complete conversion flow."""
    
    def test_accept_equivalent_single_paragraph(self):
        """Unified entry point produces same result as manual REPLACE."""
        # Create two identical models
        model1 = create_test_model_with_paragraphs(["Original text here"])
        model2 = create_test_model_with_paragraphs(["Original text here"])
        
        para_id1 = model1.body.elements[0].para_id
        # Make para_id2 same as para_id1 for comparison
        model2.body.elements[0].para_id = para_id1
        model2.body._para_id_index = {para_id1: model2.body.elements[0]}
        
        revised = "Modified text here"
        
        # Apply via unified entry point
        apply_revision_from_plain_text(
            model=model1,
            para_ids=[para_id1],
            revised_text=revised
        )
        
        # Apply via manual REPLACE edit
        original_text = model2.get_paragraph(para_id1).plain_text
        edit = DocumentEdit(
            edit_type=EditType.REPLACE,
            para_id=para_id1,
            start_offset=0,
            end_offset=len(original_text),
            text=revised,
            author="Stet",
            track_change=True
        )
        model2.apply_edit(edit)
        
        # Both should have same result
        assert model1.get_paragraph(para_id1).plain_text == model2.get_paragraph(para_id1).plain_text
    
    def test_roundtrip_split_merge(self):
        """Split then merge returns to original state (approximately)."""
        original_text = "Hello world. This is more text."
        model = create_test_model_with_paragraphs([original_text])
        para_ids = [e.para_id for e in model.body.elements]
        
        # Split
        apply_revision_from_plain_text(
            model=model,
            para_ids=para_ids,
            revised_text="Hello world.\n\nThis is more text."
        )
        
        assert len(model.body.elements) == 2
        
        # Get new para_ids after split
        new_para_ids = [e.para_id for e in model.body.elements]
        
        # Merge back
        apply_revision_from_plain_text(
            model=model,
            para_ids=new_para_ids,
            revised_text="Hello world. This is more text."
        )
        
        # Should be back to single paragraph
        assert len(model.body.elements) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
