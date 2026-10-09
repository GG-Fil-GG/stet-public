"""Tests for diff_formatting.py."""

import pytest

from src.diff_formatting import (
    parse_html_formatting,
    build_html_formatting_map,
    get_formatting_for_text_range,
    get_formatting_segments_for_range,
    merge_formatting_for_revision,
)

# =============================================================================
# PARSE HTML FORMATTING TESTS
# =============================================================================

class TestParseHtmlFormatting:
    """Tests for HTML formatting parser."""
    
    def test_plain_text(self):
        """Test plain text without formatting."""
        result = parse_html_formatting("Hello world")
        assert len(result) == 1
        assert result[0] == ("Hello world", set())
    
    def test_bold_text(self):
        """Test bold formatting."""
        result = parse_html_formatting("Hello <strong>world</strong>!")
        assert len(result) == 3
        assert result[0] == ("Hello ", set())
        assert result[1] == ("world", {'bold'})
        assert result[2] == ("!", set())
    
    def test_italic_text(self):
        """Test italic formatting."""
        result = parse_html_formatting("<em>italic</em> text")
        assert result[0] == ("italic", {'italic'})
        assert result[1] == (" text", set())
    
    def test_combined_formatting(self):
        """Test combined bold and italic."""
        result = parse_html_formatting("<strong><em>both</em></strong>")
        assert len(result) == 1
        assert result[0] == ("both", {'bold', 'italic'})
    
    def test_all_formatting_types(self):
        """Test all formatting types."""
        html = "<strong>bold</strong> <em>italic</em> <u>underline</u> <sup>super</sup> <sub>sub</sub>"
        result = parse_html_formatting(html)
        texts = [(t, f) for t, f in result if t.strip()]
        assert ('bold', {'bold'}) in texts
        assert ('italic', {'italic'}) in texts
        assert ('underline', {'underline'}) in texts
        assert ('super', {'superscript'}) in texts
        assert ('sub', {'subscript'}) in texts
    
    def test_br_tag(self):
        """Test line break handling."""
        result = parse_html_formatting("Line 1<br>Line 2")
        texts = [t for t, _ in result]
        assert "Line 1" in texts
        assert "\n" in texts
        assert "Line 2" in texts


class TestBuildHtmlFormattingMap:
    """Tests for formatting map builder."""
    
    def test_simple_map(self):
        """Test building a simple formatting map."""
        result = build_html_formatting_map("Hello <strong>world</strong>!")
        # "Hello " (0-6), "world" (6-11), "!" (11-12)
        assert len(result) == 3
        assert result[0] == (0, 6, set())
        assert result[1] == (6, 11, {'bold'})
        assert result[2] == (11, 12, set())


class TestGetFormattingForTextRange:
    """Tests for getting formatting in a range."""
    
    def test_exact_range(self):
        """Test getting formatting for exact range."""

        fmt_map = build_html_formatting_map("Hello <strong>world</strong>!")
        # "world" is at positions 6-11
        formatting = get_formatting_for_text_range(fmt_map, 6, 11)
        assert formatting == {'bold'}
    
    def test_overlapping_range(self):
        """Test getting formatting that spans multiple regions."""

        fmt_map = build_html_formatting_map("Hello <strong>world</strong>!")
        # Range that spans "o world" (4-11)
        formatting = get_formatting_for_text_range(fmt_map, 4, 11)
        assert formatting == {'bold'}  # Union of overlapping regions
    
    def test_no_formatting_range(self):
        """Test getting formatting for unformatted range."""

        fmt_map = build_html_formatting_map("Hello <strong>world</strong>!")
        # "Hell" is at positions 0-4, no formatting
        formatting = get_formatting_for_text_range(fmt_map, 0, 4)
        assert formatting == set()


class TestGetFormattingSegmentsForRange:
    """Tests for getting segmented formatting for a text range."""
    
    def test_partial_formatting(self):
        """Test getting segments when only part of text is formatted."""
        # HTML: "p<0.001" where only "p" is italic
        html = "<em>p</em>&lt;0.001"
        fmt_map = build_html_formatting_map(html)
        # The full text should be "p<0.001"
        segments = get_formatting_segments_for_range(fmt_map, "p<0.001", 0)
        
        # Should have 2 segments: "p" (italic) and "<0.001" (no formatting)
        assert len(segments) == 2
        assert segments[0] == ("p", {'italic'})
        assert segments[1] == ("<0.001", set())
    
    def test_no_formatting(self):
        """Test getting segments when there's no formatting."""
        html = "plain text"
        fmt_map = build_html_formatting_map(html)
        segments = get_formatting_segments_for_range(fmt_map, "plain text", 0)
        
        assert len(segments) == 1
        assert segments[0] == ("plain text", set())
    
    def test_offset_position(self):
        """Test getting segments with offset position."""
        # HTML: "Hello <strong>world</strong>!"
        html = "Hello <strong>world</strong>!"
        fmt_map = build_html_formatting_map(html)
        # Get segments for just "world" which starts at position 6
        segments = get_formatting_segments_for_range(fmt_map, "world", 6)
        
        assert len(segments) == 1
        assert segments[0] == ("world", {'bold'})


class TestMergeFormattingForRevision:
    """Tests for merging original and user formatting."""
    
    def test_merge_preserves_original_formatting_on_unchanged(self):
        """Test that original formatting is preserved on unchanged text."""
        
        # Original has bold "Results:"
        original_text = "Results: The quick fox"
        original_html = "<strong>Results:</strong> The quick fox"
        revised_text = "Results: The fast fox"
        # In real flow, revised_html comes from TipTap which preserves formatting
        # from the initial merge. Simulate this by including the original formatting.
        revised_html = "<strong>Results:</strong> The fast fox"
        
        merged = merge_formatting_for_revision(
            original_text, original_html, revised_text, revised_html
        )
        
        # "Results:" should still be bold (user kept it)
        assert "<strong>Results:</strong>" in merged
        # "fast" should not be bold (it's new text, user didn't format it)
        assert "fast" in merged
    
    def test_merge_applies_user_formatting_on_insertions(self):
        """Test that user formatting is applied to inserted text."""
        
        original_text = "The value is x"
        original_html = "The value is x"
        revised_text = "The value is p<0.001"
        revised_html = "The value is <em>p</em>&lt;0.001"  # User made "p" italic
        
        merged = merge_formatting_for_revision(
            original_text, original_html, revised_text, revised_html
        )
        
        # "p" should be italic
        assert "<em>p</em>" in merged
        # The rest should be plain
        assert "The value is" in merged
    
    def test_merge_combines_both_formatting_types(self):
        """Test that both original and user formatting are combined."""
        
        # Original has bold "Results:" and italic "SBP"
        original_text = "Results: The SBP value"
        original_html = "<strong>Results:</strong> The <em>SBP</em> value"
        revised_text = "Results: The SBP is p<0.05"
        # In real flow, revised_html comes from TipTap which preserves formatting from initial merge
        # User kept "Results:" bold and "SBP" italic, and made "p" bold
        revised_html = "<strong>Results:</strong> The <em>SBP</em> is <strong>p</strong>&lt;0.05"
        
        merged = merge_formatting_for_revision(
            original_text, original_html, revised_text, revised_html
        )
        
        # "Results:" should still be bold (user kept it)
        assert "<strong>Results:</strong>" in merged
        # "SBP" should still be italic (user kept it)
        assert "<em>SBP</em>" in merged
        # "p" should be bold (user formatting on new text)
        assert "<strong>p</strong>" in merged
    
    def test_merge_user_removes_formatting(self):
        """Test that user can explicitly remove formatting from unchanged text."""
        
        # Original has italic "BMI"
        original_text = "The BMI value"
        original_html = "The <em>BMI</em> value"
        revised_text = "The BMI value"  # Same text
        # User explicitly removed italic from BMI
        revised_html = "The BMI value"
        
        merged = merge_formatting_for_revision(
            original_text, original_html, revised_text, revised_html
        )
        
        # BMI should NOT be italic (user removed it)
        assert "<em>" not in merged
        assert "BMI" in merged
    
    def test_merge_no_changes_returns_original(self):
        """Test that identical text returns original HTML."""
        
        original_text = "Hello world"
        original_html = "<strong>Hello</strong> world"
        revised_text = "Hello world"  # No changes
        
        merged = merge_formatting_for_revision(
            original_text, original_html, revised_text, None
        )
        
        assert merged == original_html


