"""Tests for diff_core.py."""

import pytest

from src.diff_core import (
    DiffOperation,
    DiffOp,
    DiffResult,
    tokenize_words,
    compute_diff,
    merge_adjacent_ops,
    has_meaningful_changes,
    diff_to_markdown,
)
from src.diff_html import diff_to_html

# =============================================================================
# TOKENIZATION TESTS
# =============================================================================

class TestTokenizeWords:
    """Tests for tokenize_words function."""
    
    def test_simple_sentence(self):
        result = tokenize_words("The quick fox")
        assert result == ["The ", "quick ", "fox"]
    
    def test_multiple_spaces(self):
        result = tokenize_words("The  quick   fox")
        assert result == ["The  ", "quick   ", "fox"]
    
    def test_punctuation_attached(self):
        result = tokenize_words("Hello, world!")
        assert result == ["Hello, ", "world!"]
    
    def test_empty_string(self):
        result = tokenize_words("")
        assert result == []
    
    def test_single_word(self):
        result = tokenize_words("Word")
        assert result == ["Word"]
    
    def test_single_word_with_space(self):
        result = tokenize_words("Word ")
        assert result == ["Word "]
    
    def test_whitespace_only(self):
        result = tokenize_words("   ")
        assert result == ["   "]
    
    def test_leading_whitespace(self):
        result = tokenize_words("  Hello world")
        # Leading whitespace should be preserved with first token
        assert result == ["  Hello ", "world"]
    
    def test_newlines(self):
        result = tokenize_words("Hello\nworld")
        # Newline is whitespace, attached to preceding word
        assert result == ["Hello\n", "world"]
    
    def test_tabs(self):
        result = tokenize_words("Hello\tworld")
        assert result == ["Hello\t", "world"]


# =============================================================================
# COMPUTE_DIFF TESTS
# =============================================================================

class TestComputeDiff:
    """Tests for compute_diff function."""
    
    def test_identical_strings(self):
        result = compute_diff("Same text", "Same text")
        assert not result.has_changes
        assert len(result.operations) == 1
        assert result.operations[0].op == DiffOperation.EQUAL
        assert result.operations[0].text == "Same text"
    
    def test_empty_strings(self):
        result = compute_diff("", "")
        assert not result.has_changes
        assert len(result.operations) == 0
    
    def test_empty_original(self):
        result = compute_diff("", "New text")
        assert result.has_changes
        assert len(result.operations) == 1
        assert result.operations[0].op == DiffOperation.INSERT
        assert result.operations[0].text == "New text"
    
    def test_empty_revised(self):
        result = compute_diff("Old text", "")
        assert result.has_changes
        assert len(result.operations) == 1
        assert result.operations[0].op == DiffOperation.DELETE
        assert result.operations[0].text == "Old text"
    
    def test_single_word_replacement(self):
        result = compute_diff("The quick fox", "The fast fox")
        assert result.has_changes
        
        # Should have: equal, delete, insert, equal
        ops = result.operations
        assert any(op.op == DiffOperation.DELETE and "quick" in op.text for op in ops)
        assert any(op.op == DiffOperation.INSERT and "fast" in op.text for op in ops)
    
    def test_multiple_changes(self):
        result = compute_diff(
            "The quick brown fox",
            "The fast brown dog"
        )
        summary = result.change_summary
        assert summary['deletions'] >= 1  # At least "quick" and "fox"
        assert summary['insertions'] >= 1  # At least "fast" and "dog"
    
    def test_insertion_only(self):
        result = compute_diff(
            "Hello world",
            "Hello beautiful world"
        )
        assert result.has_changes
        assert any(op.op == DiffOperation.INSERT and "beautiful" in op.text for op in result.operations)
    
    def test_deletion_only(self):
        result = compute_diff(
            "Hello beautiful world",
            "Hello world"
        )
        assert result.has_changes
        assert any(op.op == DiffOperation.DELETE and "beautiful" in op.text for op in result.operations)
    
    def test_complete_replacement(self):
        result = compute_diff("Old text", "New content")
        assert result.has_changes
        assert any(op.op == DiffOperation.DELETE for op in result.operations)
        assert any(op.op == DiffOperation.INSERT for op in result.operations)
    
    def test_preserves_original_and_revised(self):
        result = compute_diff("Original", "Revised")
        assert result.original == "Original"
        assert result.revised == "Revised"
    
    def test_change_summary(self):
        result = compute_diff("The quick fox", "The fast dog")
        summary = result.change_summary
        
        assert 'total_ops' in summary
        assert 'insertions' in summary
        assert 'deletions' in summary
        assert 'unchanged_regions' in summary
        assert summary['total_ops'] == len(result.operations)


# =============================================================================
# MERGE_ADJACENT_OPS TESTS
# =============================================================================

class TestMergeAdjacentOps:
    """Tests for merge_adjacent_ops function."""
    
    def test_empty_list(self):
        result = merge_adjacent_ops([])
        assert result == []
    
    def test_single_op(self):
        ops = [DiffOp(DiffOperation.EQUAL, "text")]
        result = merge_adjacent_ops(ops)
        assert len(result) == 1
        assert result[0].text == "text"
    
    def test_merge_adjacent_equals(self):
        ops = [
            DiffOp(DiffOperation.EQUAL, "a"),
            DiffOp(DiffOperation.EQUAL, "b"),
            DiffOp(DiffOperation.EQUAL, "c"),
        ]
        result = merge_adjacent_ops(ops)
        assert len(result) == 1
        assert result[0].text == "abc"
        assert result[0].op == DiffOperation.EQUAL
    
    def test_merge_adjacent_deletes(self):
        ops = [
            DiffOp(DiffOperation.DELETE, "old"),
            DiffOp(DiffOperation.DELETE, "text"),
        ]
        result = merge_adjacent_ops(ops)
        assert len(result) == 1
        assert result[0].text == "oldtext"
        assert result[0].op == DiffOperation.DELETE
    
    def test_no_merge_different_types(self):
        ops = [
            DiffOp(DiffOperation.EQUAL, "a"),
            DiffOp(DiffOperation.DELETE, "b"),
            DiffOp(DiffOperation.INSERT, "c"),
        ]
        result = merge_adjacent_ops(ops)
        assert len(result) == 3


# =============================================================================
# HAS_MEANINGFUL_CHANGES TESTS
# =============================================================================

class TestHasMeaningfulChanges:
    """Tests for has_meaningful_changes function."""
    
    def test_no_changes(self):
        result = compute_diff("Same", "Same")
        assert not has_meaningful_changes(result)
    
    def test_with_changes(self):
        result = compute_diff("Old", "New")
        assert has_meaningful_changes(result)
    
    def test_whitespace_only_change(self):
        # Create a result with only whitespace change
        result = DiffResult(
            operations=[
                DiffOp(DiffOperation.EQUAL, "text"),
                DiffOp(DiffOperation.DELETE, "  "),
                DiffOp(DiffOperation.INSERT, " "),
            ],
            original="text  ",
            revised="text "
        )
        assert not has_meaningful_changes(result)
    
    def test_min_char_threshold(self):
        result = DiffResult(
            operations=[DiffOp(DiffOperation.INSERT, "a")],
            original="",
            revised="a"
        )
        assert has_meaningful_changes(result, min_char_change=1)
        assert not has_meaningful_changes(result, min_char_change=2)


# =============================================================================
# DIFF_TO_MARKDOWN TESTS
# =============================================================================

class TestDiffToMarkdown:
    """Tests for diff_to_markdown function."""
    
    def test_no_changes(self):
        result = compute_diff("Same", "Same")
        md_out = diff_to_markdown(result)
        assert md_out == "Same"
    
    def test_deletion_strikethrough(self):
        result = compute_diff("Hello world", "Hello")
        md_out = diff_to_markdown(result)
        assert "~~" in md_out
        assert "world" in md_out
    
    def test_insertion_bold(self):
        result = compute_diff("Hello", "Hello world")
        md_out = diff_to_markdown(result)
        assert "**" in md_out
        assert "world" in md_out
    
    def test_replacement(self):
        result = compute_diff("old text", "new text")
        md_out = diff_to_markdown(result)
        assert "~~" in md_out
        assert "**" in md_out


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests with realistic scenarios."""
    
    def test_scientific_text_revision(self):
        original = "The study showed a significant effect (p < 0.05) in the treatment group."
        revised = "The study demonstrated a highly significant effect (p < 0.001) in the active treatment group."
        
        result = compute_diff(original, revised)
        assert result.has_changes
        
        # Should detect key changes
        summary = result.change_summary
        assert summary['deletions'] > 0
        assert summary['insertions'] > 0
    
    def test_preserves_punctuation(self):
        result = compute_diff("Hello, world.", "Hello world!")
        assert result.has_changes
        # The punctuation change should be detected
    
    def test_long_text_diff(self):
        original = " ".join([f"word{i}" for i in range(100)])
        revised = " ".join([f"word{i}" if i != 50 else "changed" for i in range(100)])
        
        result = compute_diff(original, revised)
        assert result.has_changes
        assert "changed" in ''.join(op.text for op in result.operations if op.op == DiffOperation.INSERT)
    
    def test_roundtrip_html_contains_all_text(self):
        original = "The quick brown fox"
        revised = "The fast brown dog"
        
        result = compute_diff(original, revised)
        html_out = diff_to_html(result)
        
        # HTML should contain all words from both versions
        assert "The " in html_out
        assert "quick" in html_out
        assert "fast" in html_out
        assert "brown " in html_out
        assert "fox" in html_out
        assert "dog" in html_out


