"""Tests for diff_html.py."""

import pytest

from src.diff_core import DiffOperation, compute_diff
from src.diff_html import (
    diff_to_html,
    diff_to_html_paragraph_aware,
    diff_to_editable_html,
    strip_html_tags,
    highlight_text_in_html,
)

# =============================================================================
# DIFF_TO_HTML TESTS
# =============================================================================

class TestDiffToHtml:
    """Tests for diff_to_html function."""
    
    def test_no_changes(self):
        result = compute_diff("Same text", "Same text")
        html_out = diff_to_html(result)
        assert "Same text" in html_out
        assert "<span" not in html_out  # No styling needed
    
    def test_delete_styling(self):
        result = compute_diff("Hello world", "Hello")
        html_out = diff_to_html(result)
        assert "line-through" in html_out
        assert "world" in html_out
    
    def test_insert_styling(self):
        result = compute_diff("Hello", "Hello world")
        html_out = diff_to_html(result)
        assert "#28a745" in html_out or "green" in html_out.lower()
        assert "world" in html_out
    
    def test_hide_deletions(self):
        result = compute_diff("Hello world", "Hello")
        html_out = diff_to_html(result, show_deletions=False)
        assert "world" not in html_out
    
    def test_custom_styles(self):
        result = compute_diff("old", "new")
        html_out = diff_to_html(
            result,
            delete_style="color: blue;",
            insert_style="color: purple;"
        )
        assert "color: blue" in html_out
        assert "color: purple" in html_out
    
    def test_html_escaping(self):
        result = compute_diff("<script>", "<div>")
        html_out = diff_to_html(result)
        assert "&lt;script&gt;" in html_out
        assert "&lt;div&gt;" in html_out
    
    def test_newlines_to_br(self):
        result = compute_diff("line1", "line1\nline2")
        html_out = diff_to_html(result)
        assert "<br>" in html_out


# =============================================================================
# DIFF_TO_HTML_PARAGRAPH_AWARE TESTS
# =============================================================================

class TestDiffToHtmlParagraphAware:
    """Tests for diff_to_html_paragraph_aware function."""
    
    def test_identical_text(self):
        """Test that identical text shows no changes."""
        
        original = "First paragraph.\n\nSecond paragraph."
        revised = "First paragraph.\n\nSecond paragraph."
        html_out = diff_to_html_paragraph_aware(original, revised)
        
        assert "First paragraph." in html_out
        assert "Second paragraph." in html_out
        # No styling spans for identical text
        assert "line-through" not in html_out
        assert "#28a745" not in html_out
    
    def test_new_paragraph_at_start(self):
        """Test adding a new paragraph at the beginning."""
        
        original = "Original paragraph with some text here."
        revised = "New heading\n\nOriginal paragraph with some text here."
        html_out = diff_to_html_paragraph_aware(original, revised)
        
        # New heading should be marked as insertion
        assert "#28a745" in html_out or "e8f5e9" in html_out  # insert style
        assert "New heading" in html_out
        # Original text should be unchanged (no strikethrough)
        assert "Original paragraph with some text here." in html_out
    
    def test_new_paragraph_preserves_alignment(self):
        """Test that adding a paragraph doesn't misalign subsequent text."""
        
        original = "Discussion: These findings support the hypothesis."
        revised = "Discussion\n\nThese findings support the hypothesis."
        html_out = diff_to_html_paragraph_aware(original, revised)
        
        # "Discussion" as new paragraph should be insertion
        # "Discussion:" should be deletion
        # "These findings support the hypothesis." should be mostly unchanged
        assert "These findings support the hypothesis" in html_out
        # The bulk of text shouldn't be shown as all-new
        parts = html_out.split("<br><br>")
        # Should have paragraph separator
        assert len(parts) >= 2 or "<br><br>" in html_out
    
    def test_deleted_paragraph(self):
        """Test removing a paragraph."""
        
        original = "First para.\n\nSecond para to delete.\n\nThird para."
        revised = "First para.\n\nThird para."
        html_out = diff_to_html_paragraph_aware(original, revised)
        
        # Deleted paragraph should have strikethrough
        assert "line-through" in html_out
        assert "Second para to delete" in html_out
    
    def test_modified_paragraph(self):
        """Test modifying text within a paragraph."""
        
        original = "The quick brown fox."
        revised = "The fast brown dog."
        html_out = diff_to_html_paragraph_aware(original, revised)
        
        # Should show word-level changes
        assert "quick" in html_out
        assert "fast" in html_out
        assert "fox" in html_out
        assert "dog" in html_out
    
    def test_empty_inputs(self):
        """Test handling of empty inputs."""
        
        assert diff_to_html_paragraph_aware("", "") == ""
        
        # All new
        result = diff_to_html_paragraph_aware("", "New text")
        assert "New text" in result
        assert "#28a745" in result or "e8f5e9" in result
        
        # All deleted
        result = diff_to_html_paragraph_aware("Old text", "")
        assert "Old text" in result
        assert "line-through" in result


class TestStripHtmlTags:
    """Tests for HTML tag stripping."""
    
    def test_simple_tags(self):
        """Test stripping simple tags."""
        result = strip_html_tags("<strong>bold</strong> text")
        assert result == "bold text"
    
    def test_nested_tags(self):
        """Test stripping nested tags."""
        result = strip_html_tags("<strong><em>nested</em></strong>")
        assert result == "nested"
    
    def test_mixed_content(self):
        """Test mixed formatted content."""
        result = strip_html_tags("The <strong>quick</strong> <em>brown</em> fox")
        assert result == "The quick brown fox"
    
    def test_html_entities(self):
        """Test HTML entity handling."""
        result = strip_html_tags("a &lt; b &amp; c")
        assert result == "a < b & c"
    
    def test_no_tags(self):
        """Test text without tags."""
        result = strip_html_tags("plain text")
        assert result == "plain text"
    
    def test_empty_input(self):
        """Test empty input."""
        result = strip_html_tags("")
        assert result == ""
    
    def test_paragraph_tags_preserved(self):
        """Test that paragraph tags are converted to double newlines."""
        result = strip_html_tags("<p>First paragraph</p><p>Second paragraph</p>")
        assert result == "First paragraph\n\nSecond paragraph"
    
    def test_div_tags_preserved(self):
        """Test that div tags are converted to double newlines."""
        result = strip_html_tags("<div>First block</div><div>Second block</div>")
        assert result == "First block\n\nSecond block"
    
    def test_br_tags_preserved(self):
        """Test that br tags are converted to single newlines."""
        result = strip_html_tags("Line one<br>Line two<br/>Line three")
        assert result == "Line one\nLine two\nLine three"
    
    def test_mixed_block_elements(self):
        """Test mixed block elements with formatting."""
        result = strip_html_tags("<p>The <strong>first</strong> paragraph</p><p>The <em>second</em> paragraph</p>")
        assert result == "The first paragraph\n\nThe second paragraph"
    
    def test_tiptap_style_html(self):
        """Test HTML as produced by TipTap editor."""
        # TipTap produces <p> tags for each paragraph
        html = "<p>Paragraph one with some text.</p><p>Paragraph two with more text.</p><p>Paragraph three.</p>"
        result = strip_html_tags(html)
        assert result == "Paragraph one with some text.\n\nParagraph two with more text.\n\nParagraph three."
    
    def test_preserve_paragraphs_false(self):
        """Test that paragraph preservation can be disabled."""
        result = strip_html_tags("<p>First</p><p>Second</p>", preserve_paragraphs=False)
        assert result == "FirstSecond"  # No newlines when disabled
    
    def test_triple_newlines_collapsed(self):
        """Test that excessive newlines are collapsed to double."""
        # Edge case: content with both closing and opening tags creating extra newlines
        result = strip_html_tags("<p>One</p>\n\n<p>Two</p>")
        # Should have clean double newlines, not triple+
        assert "\n\n\n" not in result
        assert "One" in result and "Two" in result


# =============================================================================
# HIGHLIGHT_TEXT_IN_HTML TESTS
# =============================================================================

class TestDiffToEditableHtml:
    """Tests for diff_to_editable_html function (unified editor)."""
    
    def test_simple_insertion(self):
        """Test that insertions are highlighted with diff-insert class."""
        original = "The brown fox"
        revised = "The quick brown fox"
        result = diff_to_editable_html(original, revised)
        
        assert 'diff-insert' in result
        assert 'quick' in result
        assert 'brown fox' in result
    
    def test_simple_deletion(self):
        """Test that deletions are shown with diff-delete class."""
        original = "The quick brown fox"
        revised = "The brown fox"
        result = diff_to_editable_html(original, revised)
        
        assert 'diff-delete' in result
        assert 'contenteditable="false"' in result  # Deletions are non-editable
        assert 'quick' in result
    
    def test_preserves_formatting_in_equal_parts(self):
        """Test that formatting is preserved in unchanged text."""
        original = "Hello world"
        revised = "<strong>Hello</strong> world"
        result = diff_to_editable_html(original, revised)
        
        assert '<strong>Hello</strong>' in result
        # No diff markers since text is identical
        assert 'diff-insert' not in result
        assert 'diff-delete' not in result
    
    def test_preserves_formatting_in_insertions(self):
        """Test that formatting in inserted text is preserved."""
        original = "The data"
        revised = "The <em>new</em> data"
        result = diff_to_editable_html(original, revised)
        
        assert 'diff-insert' in result
        assert '<em>new</em>' in result
    
    def test_insertion_and_deletion_combined(self):
        """Test combined insertion and deletion (replacement)."""
        original = "The quick fox"
        revised = "The fast fox"
        result = diff_to_editable_html(original, revised)
        
        assert 'diff-delete' in result
        assert 'quick' in result
        assert 'diff-insert' in result
        assert 'fast' in result
    
    def test_complex_formatting_preserved(self):
        """Test that complex formatting is preserved through diff."""
        original = "Results: The data shows BMI."
        revised = "<strong>Results:</strong> The data shows <em>BMI</em> values."
        result = diff_to_editable_html(original, revised)
        
        assert '<strong>Results:</strong>' in result
        assert '<em>BMI</em>' in result
        assert 'values' in result
    
    def test_empty_inputs(self):
        """Test handling of empty inputs."""
        assert diff_to_editable_html("", "") == ""
        assert diff_to_editable_html("hello", "hello") == "hello"


class TestHighlightTextInHtml:
    """Tests for highlight_text_in_html function."""
    
    def test_simple_highlight(self):
        """Test highlighting plain text without HTML tags."""
        html = "The data shows BMI values."
        result = highlight_text_in_html(html, "BMI")
        
        assert '<mark class="bg-yellow-200 px-0.5 rounded">BMI</mark>' in result
        assert "The data shows" in result
        assert "values." in result
    
    def test_highlight_preserves_formatting(self):
        """Test that highlighting preserves surrounding HTML formatting."""
        html = "<strong>Results:</strong> The data shows BMI."
        result = highlight_text_in_html(html, "BMI")
        
        assert "<strong>Results:</strong>" in result
        assert '<mark class="bg-yellow-200 px-0.5 rounded">BMI</mark>' in result
    
    def test_highlight_text_spanning_html_tags(self):
        """Test highlighting text that spans across HTML tags."""
        html = "<strong>Results:</strong> baseline <em>BMI</em>."
        result = highlight_text_in_html(html, "baseline BMI.")
        
        # The <em> tag should be preserved inside the mark
        assert '<mark class="bg-yellow-200 px-0.5 rounded">baseline <em>BMI</em>.</mark>' in result
        assert "<strong>Results:</strong>" in result
    
    def test_highlight_full_paragraph_with_formatting(self):
        """Test highlighting text in a full paragraph with multiple formatting."""
        html = '<strong>Results:</strong> The <em>SBP</em> was reduced. This effect was consistent across baseline <em>BMI</em>.'
        text_to_highlight = 'This effect was consistent across baseline BMI.'
        result = highlight_text_in_html(html, text_to_highlight)
        
        # Original formatting should be preserved
        assert "<strong>Results:</strong>" in result
        assert "<em>SBP</em>" in result
        # Highlighted text should include the <em>BMI</em>
        assert '<mark class="bg-yellow-200 px-0.5 rounded">This effect was consistent across baseline <em>BMI</em>.</mark>' in result
    
    def test_highlight_second_occurrence(self):
        """Test highlighting the second occurrence of text."""
        html = "BMI is important. The BMI value was high."
        result = highlight_text_in_html(html, "BMI", occurrence=2)
        
        # First BMI should NOT be highlighted
        assert result.startswith("BMI is important.")
        # Second BMI should be highlighted
        assert 'The <mark class="bg-yellow-200 px-0.5 rounded">BMI</mark> value' in result
    
    def test_text_not_found_returns_original(self):
        """Test that non-matching text returns original HTML."""
        html = "<strong>Results:</strong> The data."
        result = highlight_text_in_html(html, "nonexistent")
        
        assert result == html
    
    def test_empty_inputs(self):
        """Test handling of empty inputs."""
        assert highlight_text_in_html("", "text") == ""
        assert highlight_text_in_html("some text", "") == "some text"
        assert highlight_text_in_html("", "") == ""
    
    def test_html_entities_preserved(self):
        """Test that HTML entities are handled correctly."""
        html = "The value is p&lt;0.05 and significant."
        result = highlight_text_in_html(html, "p<0.05")
        
        # The entity should be matched and highlighted
        assert '<mark class="bg-yellow-200 px-0.5 rounded">p&lt;0.05</mark>' in result

