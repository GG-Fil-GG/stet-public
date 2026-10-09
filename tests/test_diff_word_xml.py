"""Tests for diff_word_xml.py."""

import pytest

from src.diff_core import DiffOperation, compute_diff
from src.diff_word_xml import (
    diff_to_word_xml,
    html_to_word_runs,
    diff_to_word_xml_with_formatting,
)

# =============================================================================
# DIFF_TO_WORD_XML TESTS
# =============================================================================

class TestDiffToWordXml:
    """Tests for diff_to_word_xml function."""
    
    def test_no_changes_produces_runs(self):
        result = compute_diff("Same text", "Same text")
        xml_out, next_id = diff_to_word_xml(
            result,
            author="Test",
            timestamp="2026-01-19T12:00:00Z",
            base_revision_id=1,
            rsid="ABC12345"
        )
        assert "<w:r" in xml_out
        assert "<w:t" in xml_out
        assert "Same text" in xml_out
        assert "<w:del" not in xml_out
        assert "<w:ins" not in xml_out
        assert next_id == 1  # No IDs used
    
    def test_deletion_produces_w_del(self):
        result = compute_diff("Hello world", "Hello")
        xml_out, next_id = diff_to_word_xml(
            result,
            author="Test Author",
            timestamp="2026-01-19T12:00:00Z",
            base_revision_id=1,
            rsid="ABC12345"
        )
        assert "<w:del" in xml_out
        assert "w:delText" in xml_out
        assert "Test Author" in xml_out
        assert next_id > 1
    
    def test_insertion_produces_w_ins(self):
        result = compute_diff("Hello", "Hello world")
        xml_out, next_id = diff_to_word_xml(
            result,
            author="Test Author",
            timestamp="2026-01-19T12:00:00Z",
            base_revision_id=1,
            rsid="ABC12345"
        )
        assert "<w:ins" in xml_out
        assert "Test Author" in xml_out
        assert next_id > 1
    
    def test_replacement_produces_del_and_ins(self):
        result = compute_diff("old", "new")
        xml_out, next_id = diff_to_word_xml(
            result,
            author="Test",
            timestamp="2026-01-19T12:00:00Z",
            base_revision_id=1,
            rsid="ABC12345"
        )
        assert "<w:del" in xml_out
        assert "<w:ins" in xml_out
        assert next_id >= 3  # At least 2 IDs used
    
    def test_author_escaping(self):
        result = compute_diff("old", "new")
        xml_out, _ = diff_to_word_xml(
            result,
            author="O'Brien & Co.",
            timestamp="2026-01-19T12:00:00Z",
            base_revision_id=1,
            rsid="ABC12345"
        )
        assert "O&#x27;Brien" in xml_out or "O'Brien" in xml_out  # Should be escaped
        assert "&amp;" in xml_out
    
    def test_newlines_to_br(self):
        result = compute_diff("line1", "line1\nline2")
        xml_out, _ = diff_to_word_xml(
            result,
            author="Test",
            timestamp="2026-01-19T12:00:00Z",
            base_revision_id=1,
            rsid="ABC12345"
        )
        assert "<w:br/>" in xml_out
    
    def test_revision_ids_increment(self):
        result = compute_diff("a b c", "x y z")  # Multiple changes
        _, next_id = diff_to_word_xml(
            result,
            author="Test",
            timestamp="2026-01-19T12:00:00Z",
            base_revision_id=100,
            rsid="ABC12345"
        )
        assert next_id > 100
    
    def test_rsid_included(self):
        result = compute_diff("old", "new")
        xml_out, _ = diff_to_word_xml(
            result,
            author="Test",
            timestamp="2026-01-19T12:00:00Z",
            base_revision_id=1,
            rsid="MYRSID99"
        )
        assert "MYRSID99" in xml_out


# =============================================================================
# HTML TO WORD XML TESTS
# =============================================================================

class TestHtmlToWordRuns:
    """Tests for HTML to Word XML conversion."""
    
    def test_plain_text(self):
        """Test plain text without formatting."""
        result = html_to_word_runs("Hello world", "12345678")
        assert '<w:t xml:space="preserve">Hello world</w:t>' in result
        assert '<w:rPr>' not in result
    
    def test_bold_formatting(self):
        """Test bold text conversion."""
        result = html_to_word_runs("The <strong>quick</strong> fox", "12345678")
        assert '<w:b/>' in result
        assert 'quick' in result
        assert 'The ' in result
        assert ' fox' in result
    
    def test_italic_formatting(self):
        """Test italic text conversion."""
        result = html_to_word_runs("The <em>quick</em> fox", "12345678")
        assert '<w:i/>' in result
        assert 'quick' in result
    
    def test_underline_formatting(self):
        """Test underline text conversion."""
        result = html_to_word_runs("The <u>quick</u> fox", "12345678")
        assert '<w:u w:val="single"/>' in result
    
    def test_superscript_formatting(self):
        """Test superscript text conversion."""
        result = html_to_word_runs("x<sup>2</sup>", "12345678")
        assert '<w:vertAlign w:val="superscript"/>' in result
        assert '2' in result
    
    def test_subscript_formatting(self):
        """Test subscript text conversion."""
        result = html_to_word_runs("H<sub>2</sub>O", "12345678")
        assert '<w:vertAlign w:val="subscript"/>' in result
        assert '2' in result
    
    def test_combined_formatting(self):
        """Test combined bold and italic."""
        result = html_to_word_runs("<strong><em>bold italic</em></strong>", "12345678")
        assert '<w:b/>' in result
        assert '<w:i/>' in result
        assert 'bold italic' in result
    
    def test_nested_formatting(self):
        """Test nested formatting tags."""
        result = html_to_word_runs("<strong>bold <em>both</em> bold</strong>", "12345678")
        # Should have multiple runs
        assert result.count('<w:r') >= 3
    
    def test_html_entity_handling(self):
        """Test HTML entity handling."""
        result = html_to_word_runs("a &lt; b &gt; c", "12345678")
        # Should preserve the literal < and > after unescaping
        # Then escape them again for XML
        assert '&lt;' in result  # XML escaped
    
    def test_empty_input(self):
        """Test empty input."""
        result = html_to_word_runs("", "12345678")
        assert '<w:t' in result  # Should still produce valid XML
    
    def test_alternative_tags(self):
        """Test alternative HTML tags (b, i)."""
        result = html_to_word_runs("<b>bold</b> <i>italic</i>", "12345678")
        assert '<w:b/>' in result
        assert '<w:i/>' in result


class TestDiffToWordXmlWithFormatting:
    """Tests for format-aware diff to Word XML conversion."""
    
    def test_no_formatting(self):
        """Test diff without formatting - should behave like regular diff."""
        from src.diff_core import compute_diff
        from src.diff_word_xml import diff_to_word_xml_with_formatting
        
        diff_result = compute_diff("hello world", "hello there")
        xml, _ = diff_to_word_xml_with_formatting(
            diff_result,
            author="Test",
            timestamp="2026-01-01T00:00:00Z",
            base_revision_id=1,
            rsid="00112233"
        )
        
        assert '<w:del' in xml  # "world" deleted
        assert '<w:ins' in xml  # "there" inserted
        assert 'hello' in xml   # Unchanged
    
    def test_with_formatting_on_insertion(self):
        """Test that formatting is applied to inserted text."""
        from src.diff_core import compute_diff
        from src.diff_word_xml import diff_to_word_xml_with_formatting
        
        diff_result = compute_diff("hello world", "hello there")
        # "there" is at position 6-11 in revised text
        # Make it bold in HTML
        revised_html = "hello <strong>there</strong>"
        
        xml, _ = diff_to_word_xml_with_formatting(
            diff_result,
            author="Test",
            timestamp="2026-01-01T00:00:00Z",
            base_revision_id=1,
            rsid="00112233",
            revised_text_html=revised_html
        )
        
        # Check that insertion contains bold formatting
        assert '<w:ins' in xml
        assert '<w:b/>' in xml
    
    def test_partial_formatting_in_insertion(self):
        """Test that only specific text within insertion gets formatting."""
        from src.diff_core import compute_diff
        from src.diff_word_xml import diff_to_word_xml_with_formatting
        
        # Original: "value is x" → Revised: "value is p<0.001"
        # User makes only "p" italic
        diff_result = compute_diff("value is x", "value is p<0.001")
        # "p<0.001" is inserted, but only "p" is italic
        revised_html = "value is <em>p</em>&lt;0.001"
        
        xml, _ = diff_to_word_xml_with_formatting(
            diff_result,
            author="Test",
            timestamp="2026-01-01T00:00:00Z",
            base_revision_id=1,
            rsid="00112233",
            revised_text_html=revised_html
        )
        
        # Check that we have italic formatting
        assert '<w:i/>' in xml
        # Check that we have multiple runs in the insertion (one italic, one not)
        # The insertion should have "p" (italic) and "<0.001" (not italic) as separate runs
        import re
        ins_match = re.search(r'<w:ins[^>]*>(.*?)</w:ins>', xml, re.DOTALL)
        assert ins_match
        ins_content = ins_match.group(1)
        # Should have at least 2 runs
        runs = re.findall(r'<w:r[^>]*>.*?</w:r>', ins_content, re.DOTALL)
        assert len(runs) >= 2, f"Expected at least 2 runs, got {len(runs)}: {ins_content}"
        # One run should have italic, at least one should not
        runs_with_italic = [r for r in runs if '<w:i/>' in r]
        runs_without_italic = [r for r in runs if '<w:i/>' not in r]
        assert len(runs_with_italic) >= 1, "Expected at least one run with italic"
        assert len(runs_without_italic) >= 1, "Expected at least one run without italic"
    
    def test_formatting_not_applied_to_deletions(self):
        """Test that formatting doesn't affect deleted text."""
        from src.diff_core import compute_diff
        from src.diff_word_xml import diff_to_word_xml_with_formatting
        
        diff_result = compute_diff("hello world", "hello there")
        revised_html = "hello <strong>there</strong>"
        
        xml, _ = diff_to_word_xml_with_formatting(
            diff_result,
            author="Test",
            timestamp="2026-01-01T00:00:00Z",
            base_revision_id=1,
            rsid="00112233",
            revised_text_html=revised_html
        )
        
        # Deletion should not have formatting
        import re
        del_match = re.search(r'<w:del[^>]*>.*?</w:del>', xml, re.DOTALL)
        assert del_match
        del_content = del_match.group(0)
        assert '<w:b/>' not in del_content


