"""
Tests for PlainTextView and related classes.

Phase 3 of DOM Migration: Plain text view for LLM integration.
"""

import pytest
from pathlib import Path

from src.document_model import (
    DocumentModel,
    DocumentBody,
    Paragraph,
    Run,
    CommentStore,
    Comment,
    CommentAnchor,
    CommentThread,
    PlainTextView,
    PlainTextViewBuilder,
    TextScope,
    DOMPosition,
    PreservedRegion,
    CommentRange,
    get_context_for_thread,
    parse_docx,
)
from tests.test_support import SYNTHETIC_TEST_DATA_DIR


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def simple_model():
    """Create a simple document model with 5 paragraphs."""
    model = DocumentModel()
    
    # Add 5 paragraphs
    for i in range(5):
        para = Paragraph(
            para_id=f"PARA{i:04X}",
            text_id=f"TEXT{i:04X}",
            runs=[Run(text=f"This is paragraph {i}.")],
            index=i
        )
        model.body.add_element(para)
    
    return model


@pytest.fixture
def model_with_comment():
    """Create a document model with a comment anchored to paragraph 2."""
    model = DocumentModel()
    
    # Add 5 paragraphs
    for i in range(5):
        para = Paragraph(
            para_id=f"PARA{i:04X}",
            text_id=f"TEXT{i:04X}",
            runs=[Run(text=f"Paragraph {i} with some text content.")],
            index=i
        )
        model.body.add_element(para)
    
    # Add a comment anchored to paragraph 2 (PARA0002)
    comment = Comment(
        comment_id="0",
        para_id="COMMENT_PARA_0",
        author="Test Author",
        author_initials="TA",
        text="This is a test comment",
        anchor=CommentAnchor(
            comment_id="0",
            para_id="PARA0002",
            start_offset=11,  # Start of "with"
            end_offset=27    # End of "text content"
        )
    )
    model.comments.comments["0"] = comment
    model.comments._by_para_id["COMMENT_PARA_0"] = comment
    model.comments.threads["0"] = CommentThread(thread_id="0", root=comment)
    
    return model


@pytest.fixture
def model_with_thread():
    """Create a document model with a threaded comment (root + reply)."""
    model = DocumentModel()
    
    # Add 5 paragraphs
    for i in range(5):
        para = Paragraph(
            para_id=f"PARA{i:04X}",
            text_id=f"TEXT{i:04X}",
            runs=[Run(text=f"Paragraph {i} with some text content.")],
            index=i
        )
        model.body.add_element(para)
    
    # Root comment
    root_comment = Comment(
        comment_id="0",
        para_id="COMMENT_PARA_0",
        author="Test Author",
        author_initials="TA",
        text="Root comment",
        anchor=CommentAnchor(
            comment_id="0",
            para_id="PARA0002",
            start_offset=0,
            end_offset=11  # "Paragraph 2"
        )
    )
    
    # Reply
    reply_comment = Comment(
        comment_id="1",
        para_id="COMMENT_PARA_1",
        author="Replier",
        author_initials="R",
        text="Reply to root",
        parent_para_id="COMMENT_PARA_0",
        anchor=CommentAnchor(
            comment_id="1",
            para_id="PARA0002",
            start_offset=0,
            end_offset=11
        )
    )
    
    model.comments.comments["0"] = root_comment
    model.comments.comments["1"] = reply_comment
    model.comments._by_para_id["COMMENT_PARA_0"] = root_comment
    model.comments._by_para_id["COMMENT_PARA_1"] = reply_comment
    
    thread = CommentThread(thread_id="0", root=root_comment)
    thread.replies.append(reply_comment)
    model.comments.threads["0"] = thread
    
    return model


# =============================================================================
# Test TextScope
# =============================================================================

class TestTextScope:
    """Tests for TextScope dataclass."""
    
    def test_from_para_ids(self):
        """Test creating scope from paragraph IDs."""
        scope = TextScope.from_para_ids(["PARA1", "PARA2", "PARA3"])
        assert scope.para_ids == ["PARA1", "PARA2", "PARA3"]
        assert scope.start_index is None
        assert scope.thread_id is None
    
    def test_from_range(self):
        """Test creating scope from index range."""
        scope = TextScope.from_range(5, 10)
        assert scope.start_index == 5
        assert scope.end_index == 10
        assert scope.para_ids is None
    
    def test_from_thread(self):
        """Test creating scope from thread ID."""
        scope = TextScope.from_thread("thread_123", before=3, after=4)
        assert scope.thread_id == "thread_123"
        assert scope.context_before == 3
        assert scope.context_after == 4
    
    def test_scope_with_options(self):
        """Test scope with additional options."""
        scope = TextScope.from_para_ids(
            ["PARA1"],
            include_deleted_text=True,
            skip_ghost_paragraphs=False
        )
        assert scope.include_deleted_text is True
        assert scope.skip_ghost_paragraphs is False


# =============================================================================
# Test DOMPosition
# =============================================================================

class TestDOMPosition:
    """Tests for DOMPosition dataclass."""
    
    def test_equality(self):
        """Test DOMPosition equality."""
        pos1 = DOMPosition(para_id="PARA1", para_index=0, char_offset=5)
        pos2 = DOMPosition(para_id="PARA1", para_index=0, char_offset=5)
        pos3 = DOMPosition(para_id="PARA1", para_index=0, char_offset=10)
        
        assert pos1 == pos2
        assert pos1 != pos3
    
    def test_hashable(self):
        """Test that DOMPosition is hashable."""
        pos1 = DOMPosition(para_id="PARA1", para_index=0, char_offset=5)
        pos2 = DOMPosition(para_id="PARA1", para_index=0, char_offset=5)
        
        # Should be usable in sets/dicts
        positions = {pos1, pos2}
        assert len(positions) == 1


# =============================================================================
# Test PlainTextView Construction
# =============================================================================

class TestPlainTextViewConstruction:
    """Tests for building PlainTextView."""
    
    def test_build_from_simple_model(self, simple_model):
        """Test building view from a simple model."""
        builder = PlainTextViewBuilder(simple_model)
        scope = TextScope.from_range(0, 4)
        view = builder.build(scope)
        
        assert view.paragraph_count == 5
        assert "paragraph 0" in view.text
        assert "paragraph 4" in view.text
    
    def test_build_for_paragraphs(self, simple_model):
        """Test building view for specific paragraphs."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0001", "PARA0003"])
        
        assert view.paragraph_count == 2
        assert "paragraph 1" in view.text
        assert "paragraph 3" in view.text
        assert "paragraph 0" not in view.text
    
    def test_paragraph_boundaries(self, simple_model):
        """Test that paragraph boundaries are tracked correctly."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000", "PARA0001"])
        
        assert len(view.paragraph_boundaries) == 2
        
        # First paragraph
        start1, end1, pid1 = view.paragraph_boundaries[0]
        assert pid1 == "PARA0000"
        assert start1 == 0
        
        # Second paragraph should start after first + separator
        start2, end2, pid2 = view.paragraph_boundaries[1]
        assert pid2 == "PARA0001"
        assert start2 > end1


# =============================================================================
# Test Position Mapping
# =============================================================================

class TestPositionMapping:
    """Tests for bidirectional position mapping."""
    
    def test_dom_to_plain_first_paragraph(self, simple_model):
        """Test converting DOM position to plain text for first paragraph."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000", "PARA0001"])
        
        # Position in first paragraph
        plain_pos = view.dom_to_plain("PARA0000", 5)
        assert plain_pos == 5
    
    def test_dom_to_plain_second_paragraph(self, simple_model):
        """Test converting DOM position to plain text for second paragraph."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000", "PARA0001"])
        
        # Get first paragraph end
        _, end1, _ = view.paragraph_boundaries[0]
        start2, _, _ = view.paragraph_boundaries[1]
        
        # Position 5 in second paragraph
        plain_pos = view.dom_to_plain("PARA0001", 5)
        assert plain_pos == start2 + 5
    
    def test_dom_to_plain_not_found(self, simple_model):
        """Test dom_to_plain for non-existent paragraph."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000"])
        
        plain_pos = view.dom_to_plain("NONEXISTENT", 5)
        assert plain_pos == -1
    
    def test_plain_to_dom_first_paragraph(self, simple_model):
        """Test converting plain text position to DOM for first paragraph."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000", "PARA0001"])
        
        dom_pos = view.plain_to_dom(5)
        assert dom_pos is not None
        assert dom_pos.para_id == "PARA0000"
        assert dom_pos.char_offset == 5
        assert dom_pos.para_index == 0
    
    def test_plain_to_dom_second_paragraph(self, simple_model):
        """Test converting plain text position to DOM for second paragraph."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000", "PARA0001"])
        
        start2, _, _ = view.paragraph_boundaries[1]
        
        dom_pos = view.plain_to_dom(start2 + 5)
        assert dom_pos is not None
        assert dom_pos.para_id == "PARA0001"
        assert dom_pos.char_offset == 5
        assert dom_pos.para_index == 1
    
    def test_plain_to_dom_invalid(self, simple_model):
        """Test plain_to_dom for invalid positions."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000"])
        
        # Negative position
        assert view.plain_to_dom(-1) is None
    
    def test_round_trip_mapping(self, simple_model):
        """Test that mapping is reversible."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000", "PARA0001"])
        
        # Start with DOM position
        original_para = "PARA0000"
        original_offset = 7
        
        # Convert to plain, then back to DOM
        plain_pos = view.dom_to_plain(original_para, original_offset)
        dom_pos = view.plain_to_dom(plain_pos)
        
        assert dom_pos is not None
        assert dom_pos.para_id == original_para
        assert dom_pos.char_offset == original_offset


# =============================================================================
# Test Comment Range Tracking
# =============================================================================

class TestCommentRangeTracking:
    """Tests for tracking comment ranges in plain text."""
    
    def test_comment_range_single_paragraph(self, model_with_comment):
        """Test comment range in a single paragraph."""
        builder = PlainTextViewBuilder(model_with_comment)
        view = builder.build_for_paragraphs(["PARA0002"])
        
        assert "0" in view.comment_ranges
        comment_range = view.comment_ranges["0"]
        
        assert comment_range.comment_id == "0"
        assert comment_range.start_offset == 11  # Same as anchor
        assert comment_range.end_offset == 27
    
    def test_get_comment_range_text(self, model_with_comment):
        """Test getting the text that a comment references."""
        builder = PlainTextViewBuilder(model_with_comment)
        view = builder.build_for_paragraphs(["PARA0002"])
        
        text = view.get_comment_range_text("0")
        assert text is not None
        assert "with" in text or "text" in text  # Part of "with some text content"
    
    def test_comment_range_not_in_scope(self, model_with_comment):
        """Test that comments not in scope are not included."""
        builder = PlainTextViewBuilder(model_with_comment)
        # Build view for paragraph 0, but comment is on paragraph 2
        view = builder.build_for_paragraphs(["PARA0000"])
        
        assert "0" not in view.comment_ranges


# =============================================================================
# Test Thread-Based Context
# =============================================================================

class TestThreadBasedContext:
    """Tests for building views around comment threads."""
    
    def test_build_for_thread(self, model_with_thread):
        """Test building view for a thread."""
        builder = PlainTextViewBuilder(model_with_thread)
        view = builder.build_for_thread(
            thread_id="0",
            context_before=1,
            context_after=1
        )
        
        # Should include paragraphs 1, 2, 3 (target is 2)
        assert view.paragraph_count == 3
        assert "Paragraph 1" in view.text
        assert "Paragraph 2" in view.text
        assert "Paragraph 3" in view.text
    
    def test_build_for_thread_expanded_target(self, model_with_thread):
        """Test building view with expanded target range."""
        builder = PlainTextViewBuilder(model_with_thread)
        view = builder.build_for_thread(
            thread_id="0",
            context_before=1,
            context_after=1,
            ref_start_offset=-1,  # Include paragraph 1 in target
            ref_end_offset=1      # Include paragraph 3 in target
        )
        
        target_ids = getattr(view, '_target_para_ids', [])
        assert len(target_ids) == 3  # Paragraphs 1, 2, 3
    
    def test_build_for_nonexistent_thread(self, simple_model):
        """Test building view for non-existent thread."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_thread(thread_id="nonexistent")
        
        assert view.text == ""
        assert view.paragraph_count == 0
    
    def test_get_context_for_thread_function(self, model_with_thread):
        """Test the get_context_for_thread helper function."""
        before, target, after, target_id, all_ids = get_context_for_thread(
            model_with_thread,
            thread_id="0",
            context_before=1,
            context_after=1
        )
        
        assert target_id == "PARA0002"
        assert all_ids == ["PARA0002"]
        assert "Paragraph 2" in target


# =============================================================================
# Test Accepted Revisions
# =============================================================================

class TestAcceptedRevisions:
    """Tests for applying accepted revisions to views."""
    
    def test_apply_revision_to_view(self, simple_model):
        """Test that accepted revisions are applied."""
        builder = PlainTextViewBuilder(simple_model)
        
        # Build view with a revision
        revisions = {"PARA0001": "This is the REVISED text."}
        view = builder.build_for_paragraphs(
            ["PARA0000", "PARA0001"],
            accepted_revisions=revisions
        )
        
        assert "REVISED" in view.text
        assert "paragraph 1" not in view.text
    
    def test_revision_in_thread_context(self, model_with_thread):
        """Test revisions are applied in thread context."""
        before, target, after, _, _ = get_context_for_thread(
            model_with_thread,
            thread_id="0",
            context_before=1,
            context_after=1,
            accepted_revisions={"PARA0002": "REVISED TARGET TEXT"}
        )
        
        assert "REVISED TARGET TEXT" in target


# =============================================================================
# Test Helper Methods
# =============================================================================

class TestHelperMethods:
    """Tests for helper methods on PlainTextView."""
    
    def test_get_paragraph_text(self, simple_model):
        """Test getting text for a specific paragraph."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000", "PARA0001"])
        
        text = view.get_paragraph_text("PARA0000")
        assert text == "This is paragraph 0."
    
    def test_get_paragraph_text_not_found(self, simple_model):
        """Test getting text for paragraph not in view."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000"])
        
        text = view.get_paragraph_text("PARA0003")
        assert text is None
    
    def test_char_count(self, simple_model):
        """Test character count property."""
        builder = PlainTextViewBuilder(simple_model)
        view = builder.build_for_paragraphs(["PARA0000"])
        
        assert view.char_count == len(view.text)


# =============================================================================
# Test PreservedRegion
# =============================================================================

class TestPreservedRegion:
    """Tests for PreservedRegion dataclass."""
    
    def test_preserved_region_creation(self):
        """Test creating a preserved region."""
        region = PreservedRegion(
            start_offset=10,
            end_offset=25,
            placeholder="[CITATION]",
            original_content="Smith et al., 2020",
            region_type="citation"
        )
        
        assert region.start_offset == 10
        assert region.end_offset == 25
        assert region.placeholder == "[CITATION]"
        assert region.original_content == "Smith et al., 2020"
        assert region.region_type == "citation"


# =============================================================================
# Test CommentRange
# =============================================================================

class TestCommentRange:
    """Tests for CommentRange dataclass."""
    
    def test_comment_range_length(self):
        """Test CommentRange length property."""
        range_obj = CommentRange(
            comment_id="0",
            start_offset=10,
            end_offset=25,
            text="some text here"
        )
        
        assert range_obj.length == 15


# =============================================================================
# Integration Tests with Real Documents
# =============================================================================

class TestIntegrationWithRealDocuments:
    """Integration tests using synthetic DOCX files."""

    def test_build_view_from_parsed_document(self):
        """Test building view from a parsed document."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        
        if model.paragraph_count == 0:
            pytest.skip("Document has no paragraphs")
        
        builder = PlainTextViewBuilder(model)
        scope = TextScope.from_range(0, min(5, model.paragraph_count - 1))
        view = builder.build(scope)
        
        assert view.paragraph_count > 0
        assert len(view.text) > 0
    
    def test_thread_context_from_parsed_document(self):
        """Test thread context from a parsed document."""
        test_file = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(test_file)
        
        if model.thread_count == 0:
            pytest.skip("Document has no comment threads")
        
        thread_id = list(model.comments.threads.keys())[0]
        
        before, target, after, target_id, all_ids = get_context_for_thread(
            model,
            thread_id=thread_id,
            context_before=2,
            context_after=2
        )
        
        # Should have gotten some text
        assert len(target) > 0 or len(before) > 0 or len(after) > 0
        assert target_id is not None or all_ids is not None
    
    @pytest.mark.parametrize("filename", [
        "test.docx",
    ])
    def test_view_with_various_documents(self, filename):
        """Test PlainTextView with various test documents."""
        test_file = SYNTHETIC_TEST_DATA_DIR / filename
        model = parse_docx(test_file)
        builder = PlainTextViewBuilder(model)
        
        # Build view for all paragraphs
        if model.paragraph_count > 0:
            scope = TextScope.from_range(0, model.paragraph_count - 1)
            view = builder.build(scope)
            
            # View may have fewer paragraphs due to skip_ghost_paragraphs
            # which skips empty paragraphs
            assert view.paragraph_count > 0
            assert view.paragraph_count <= model.paragraph_count
            
            # Verify position mapping works
            if view.paragraph_boundaries:
                start, end, para_id = view.paragraph_boundaries[0]
                assert view.dom_to_plain(para_id, 0) == start
                
                dom_pos = view.plain_to_dom(start + 1)
                assert dom_pos is not None
                assert dom_pos.para_id == para_id


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
