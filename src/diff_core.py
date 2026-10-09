"""Core diff computation: tokenization, DiffOperation types, compute_diff."""

import html
import re
from typing import List, Optional, Tuple

from dataclasses import dataclass
from enum import Enum
from difflib import SequenceMatcher

class DiffOperation(Enum):
    """Type of diff operation."""
    EQUAL = 'equal'
    INSERT = 'insert'
    DELETE = 'delete'


@dataclass
class DiffOp:
    """A single diff operation."""
    op: DiffOperation
    text: str
    
    @property
    def is_change(self) -> bool:
        """True if this is an insert or delete (not equal)."""
        return self.op != DiffOperation.EQUAL
    
    def __repr__(self) -> str:
        return f"DiffOp({self.op.value}, {self.text!r})"


@dataclass
class DiffResult:
    """Complete result of a diff computation."""
    operations: List[DiffOp]
    original: str
    revised: str
    
    @property
    def has_changes(self) -> bool:
        """True if there are any differences."""
        return any(op.is_change for op in self.operations)
    
    @property
    def change_summary(self) -> dict:
        """Summary statistics about the diff."""
        return {
            'total_ops': len(self.operations),
            'insertions': sum(1 for op in self.operations if op.op == DiffOperation.INSERT),
            'deletions': sum(1 for op in self.operations if op.op == DiffOperation.DELETE),
            'unchanged_regions': sum(1 for op in self.operations if op.op == DiffOperation.EQUAL),
        }


# =============================================================================
# TOKENIZATION
# =============================================================================

def tokenize_words(text: str) -> List[str]:
    """
    Tokenize text into words with trailing whitespace attached.
    
    This ensures whitespace is preserved correctly in diffs.
    Punctuation stays attached to words.
    
    Args:
        text: Input string
        
    Returns:
        List of tokens where each token is a word + following whitespace
    
    Example:
        >>> tokenize_words("The quick  fox")
        ['The ', 'quick  ', 'fox']
        
        >>> tokenize_words("Hello, world!")
        ['Hello, ', 'world!']
    """
    if not text:
        return []
    
    # Pattern: non-whitespace characters followed by any whitespace
    # This keeps words with their trailing whitespace
    tokens = []
    current_pos = 0
    
    # Match word (non-whitespace) followed by optional whitespace
    pattern = re.compile(r'(\S+)(\s*)')
    
    for match in pattern.finditer(text):
        word = match.group(1)
        whitespace = match.group(2)
        tokens.append(word + whitespace)
    
    # Handle leading whitespace (rare but possible)
    leading_ws_match = re.match(r'^(\s+)', text)
    if leading_ws_match and tokens:
        # Prepend leading whitespace to first token
        tokens[0] = leading_ws_match.group(1) + tokens[0]
    elif leading_ws_match and not tokens:
        # Text is only whitespace
        tokens = [text]
    
    return tokens


# =============================================================================
# CORE DIFF COMPUTATION
# =============================================================================

def compute_diff(
    original: str,
    revised: str,
    *,
    ignore_whitespace_changes: bool = False
) -> DiffResult:
    """
    Compute word-level diff between two strings.
    
    Uses difflib.SequenceMatcher on word tokens to identify
    insertions, deletions, and unchanged regions.
    
    Args:
        original: The original text
        revised: The revised text
        ignore_whitespace_changes: If True, treat whitespace-only 
            differences as equal (default: False)
    
    Returns:
        DiffResult with list of operations
    
    Example:
        >>> result = compute_diff("The quick brown fox", "The fast brown dog")
        >>> for op in result.operations:
        ...     print(op)
        DiffOp(equal, 'The ')
        DiffOp(delete, 'quick ')
        DiffOp(insert, 'fast ')
        DiffOp(equal, 'brown ')
        DiffOp(delete, 'fox')
        DiffOp(insert, 'dog')
    """
    # Handle edge cases
    if original == revised:
        if original:
            return DiffResult([DiffOp(DiffOperation.EQUAL, original)], original, revised)
        else:
            return DiffResult([], original, revised)
    
    if not original:
        # Everything is an insertion
        return DiffResult([DiffOp(DiffOperation.INSERT, revised)], original, revised)
    
    if not revised:
        # Everything is a deletion
        return DiffResult([DiffOp(DiffOperation.DELETE, original)], original, revised)
    
    # Tokenize both strings
    original_tokens = tokenize_words(original)
    revised_tokens = tokenize_words(revised)
    
    # Use SequenceMatcher to find matching blocks
    # NOTE: autojunk=False is critical! With autojunk=True (default), SequenceMatcher
    # can severely underestimate similarity for scientific/technical text with repeated
    # patterns, causing most text to appear as changed when it's actually unchanged.
    matcher = SequenceMatcher(None, original_tokens, revised_tokens, autojunk=False)
    
    operations = []
    
    # get_opcodes returns: [(tag, i1, i2, j1, j2), ...]
    # tag is 'replace', 'delete', 'insert', or 'equal'
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            text = ''.join(original_tokens[i1:i2])
            if text:
                operations.append(DiffOp(DiffOperation.EQUAL, text))
        elif tag == 'replace':
            # Delete old, insert new
            deleted_text = ''.join(original_tokens[i1:i2])
            inserted_text = ''.join(revised_tokens[j1:j2])
            if deleted_text:
                operations.append(DiffOp(DiffOperation.DELETE, deleted_text))
            if inserted_text:
                operations.append(DiffOp(DiffOperation.INSERT, inserted_text))
        elif tag == 'delete':
            text = ''.join(original_tokens[i1:i2])
            if text:
                operations.append(DiffOp(DiffOperation.DELETE, text))
        elif tag == 'insert':
            text = ''.join(revised_tokens[j1:j2])
            if text:
                operations.append(DiffOp(DiffOperation.INSERT, text))
    
    # Optionally merge whitespace-only changes into adjacent equal blocks
    if ignore_whitespace_changes:
        operations = _merge_whitespace_changes(operations)
    
    # Merge adjacent operations of same type
    operations = merge_adjacent_ops(operations)
    
    return DiffResult(operations, original, revised)


def _merge_whitespace_changes(operations: List[DiffOp]) -> List[DiffOp]:
    """Merge whitespace-only insert/delete operations into equal blocks."""
    result = []
    for op in operations:
        if op.is_change and op.text.strip() == '':
            # Whitespace-only change - convert to equal
            if result and result[-1].op == DiffOperation.EQUAL:
                # Merge with previous equal
                result[-1] = DiffOp(DiffOperation.EQUAL, result[-1].text + op.text)
            else:
                result.append(DiffOp(DiffOperation.EQUAL, op.text))
        else:
            result.append(op)
    return result


def merge_adjacent_ops(operations: List[DiffOp]) -> List[DiffOp]:
    """
    Merge consecutive operations of the same type.
    
    Args:
        operations: List of DiffOp objects
        
    Returns:
        New list with adjacent same-type operations combined
    
    Example:
        [DiffOp(DELETE, 'a'), DiffOp(DELETE, 'b')] → [DiffOp(DELETE, 'ab')]
    """
    if not operations:
        return []
    
    result = [operations[0]]
    
    for op in operations[1:]:
        if op.op == result[-1].op:
            # Merge with previous
            result[-1] = DiffOp(op.op, result[-1].text + op.text)
        else:
            result.append(op)
    
    return result


def has_meaningful_changes(result: DiffResult, min_char_change: int = 1) -> bool:
    """
    Check if diff contains meaningful changes (not just whitespace).
    
    Args:
        result: The diff result
        min_char_change: Minimum non-whitespace chars to count as meaningful
        
    Returns:
        True if there are substantive changes
    """
    for op in result.operations:
        if op.is_change:
            if len(op.text.strip()) >= min_char_change:
                return True
    return False


# =============================================================================
# HTML TRANSFORMER (for Streamlit UI)
# =============================================================================

def diff_to_markdown(result: DiffResult) -> str:
    """
    Convert diff to Markdown with strikethrough and bold.
    
    Useful for console output or Markdown-capable UIs.
    
    Returns:
        String with ~~deleted~~ and **inserted** markup
    
    Example:
        "The ~~quick~~ **fast** brown fox"
    """
    parts = []
    
    for op in result.operations:
        text = op.text
        
        if op.op == DiffOperation.EQUAL:
            parts.append(text)
        elif op.op == DiffOperation.DELETE:
            # Strikethrough for deletions
            # Handle multi-line: apply ~~ to each line
            lines = text.split('\n')
            md_lines = [f'~~{line}~~' if line else '' for line in lines]
            parts.append('\n'.join(md_lines))
        elif op.op == DiffOperation.INSERT:
            # Bold for insertions
            lines = text.split('\n')
            md_lines = [f'**{line}**' if line else '' for line in lines]
            parts.append('\n'.join(md_lines))
    
    return ''.join(parts)


# =============================================================================
# FORMATTING MERGE FOR VIRTUAL STATE
# =============================================================================

