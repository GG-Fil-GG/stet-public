"""HTML formatting parsing and merge for revisions."""

import html
import re
from typing import List, Optional, Tuple

from .diff_core import DiffOperation, compute_diff
from .diff_html import strip_html_tags

def parse_html_formatting(html_content: str) -> List[Tuple[str, set]]:
    """
    Parse HTML content and return list of (text, formatting_tags) tuples.
    
    Each tuple represents a text segment with its formatting.
    Formatting tags are: 'bold', 'italic', 'underline', 'superscript', 'subscript'
    
    Example:
        "Hello <strong>world</strong>!" -> [("Hello ", set()), ("world", {'bold'}), ("!", set())]
    """
    from html.parser import HTMLParser
    
    class FormattingParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.segments: List[Tuple[str, set]] = []
            self.current_formatting: set = set()
            self.tag_stack: List[str] = []
            
        def handle_starttag(self, tag, attrs):
            tag_lower = tag.lower()
            if tag_lower in ('strong', 'b'):
                self.current_formatting.add('bold')
                self.tag_stack.append('bold')
            elif tag_lower in ('em', 'i'):
                self.current_formatting.add('italic')
                self.tag_stack.append('italic')
            elif tag_lower == 'u':
                self.current_formatting.add('underline')
                self.tag_stack.append('underline')
            elif tag_lower == 'sup':
                self.current_formatting.add('superscript')
                self.tag_stack.append('superscript')
            elif tag_lower == 'sub':
                self.current_formatting.add('subscript')
                self.tag_stack.append('subscript')
            elif tag_lower == 'br':
                # Treat <br> as a newline character
                self.segments.append(('\n', self.current_formatting.copy()))
            else:
                self.tag_stack.append(None)  # Non-formatting tag
                
        def handle_endtag(self, tag):
            tag_lower = tag.lower()
            if tag_lower in ('strong', 'b'):
                self.current_formatting.discard('bold')
                if self.tag_stack and self.tag_stack[-1] == 'bold':
                    self.tag_stack.pop()
            elif tag_lower in ('em', 'i'):
                self.current_formatting.discard('italic')
                if self.tag_stack and self.tag_stack[-1] == 'italic':
                    self.tag_stack.pop()
            elif tag_lower == 'u':
                self.current_formatting.discard('underline')
                if self.tag_stack and self.tag_stack[-1] == 'underline':
                    self.tag_stack.pop()
            elif tag_lower == 'sup':
                self.current_formatting.discard('superscript')
                if self.tag_stack and self.tag_stack[-1] == 'superscript':
                    self.tag_stack.pop()
            elif tag_lower == 'sub':
                self.current_formatting.discard('subscript')
                if self.tag_stack and self.tag_stack[-1] == 'subscript':
                    self.tag_stack.pop()
            elif self.tag_stack:
                self.tag_stack.pop()
                
        def handle_data(self, data):
            if data:
                self.segments.append((data, self.current_formatting.copy()))
                
        def handle_entityref(self, name):
            import html as html_module
            text = html_module.unescape(f'&{name};')
            if text:
                self.segments.append((text, self.current_formatting.copy()))
                
        def handle_charref(self, name):
            import html as html_module
            text = html_module.unescape(f'&#{name};')
            if text:
                self.segments.append((text, self.current_formatting.copy()))
        
        def get_segments(self) -> List[Tuple[str, set]]:
            return self.segments
    
    parser = FormattingParser()
    try:
        parser.feed(html_content)
        return parser.get_segments()
    except Exception:
        # Fallback: return plain text with no formatting
        plain = strip_html_tags(html_content)
        return [(plain, set())] if plain else []


def build_html_formatting_map(html_content: str) -> List[Tuple[int, int, set]]:
    """
    Build a map of character positions to formatting in the plain text extracted from HTML.
    
    Returns list of (start_pos, end_pos, formatting_set) tuples.
    """
    segments = parse_html_formatting(html_content)
    result = []
    pos = 0
    for text, formatting in segments:
        if text:
            result.append((pos, pos + len(text), formatting))
            pos += len(text)
    return result


def get_formatting_for_text_range(
    formatting_map: List[Tuple[int, int, set]],
    start: int,
    end: int
) -> set:
    """
    Get the formatting for a specific text range.
    
    If the range spans multiple formatting regions, returns the union of all formatting.
    """
    result = set()
    for seg_start, seg_end, formatting in formatting_map:
        # Check if ranges overlap
        if seg_start < end and seg_end > start:
            result.update(formatting)
    return result


def get_formatting_segments_for_range(
    formatting_map: List[Tuple[int, int, set]],
    text: str,
    text_start_pos: int
) -> List[Tuple[str, set]]:
    """
    Get text segments with their specific formatting for a given text range.
    
    Instead of returning uniform formatting for the whole range, this returns
    a list of (text_segment, formatting) tuples that preserve formatting boundaries.
    
    Args:
        formatting_map: The formatting map from build_html_formatting_map
        text: The text to segment
        text_start_pos: Position in the original HTML text where this text starts
        
    Returns:
        List of (text_segment, formatting_set) tuples
    """
    if not formatting_map or not text:
        return [(text, set())]
    
    text_end_pos = text_start_pos + len(text)
    result = []
    current_pos = text_start_pos
    
    # Find all formatting segments that overlap with our text range
    relevant_segments = []
    for seg_start, seg_end, formatting in formatting_map:
        if seg_start < text_end_pos and seg_end > text_start_pos:
            # Clip to our text range
            clipped_start = max(seg_start, text_start_pos)
            clipped_end = min(seg_end, text_end_pos)
            relevant_segments.append((clipped_start, clipped_end, formatting))
    
    if not relevant_segments:
        return [(text, set())]
    
    # Sort by start position
    relevant_segments.sort(key=lambda x: x[0])
    
    # Build result segments
    for seg_start, seg_end, formatting in relevant_segments:
        # If there's a gap before this segment, add unformatted text
        if seg_start > current_pos:
            gap_text = text[current_pos - text_start_pos:seg_start - text_start_pos]
            if gap_text:
                result.append((gap_text, set()))
        
        # Add this segment
        seg_text = text[seg_start - text_start_pos:seg_end - text_start_pos]
        if seg_text:
            result.append((seg_text, formatting))
        
        current_pos = seg_end
    
    # If there's remaining text after the last segment
    if current_pos < text_end_pos:
        remaining_text = text[current_pos - text_start_pos:]
        if remaining_text:
            result.append((remaining_text, set()))
    
    return result if result else [(text, set())]


def formatting_set_to_html_tags(formatting: set, text: str) -> str:
    """
    Wrap text with HTML tags based on formatting set.
    
    Args:
        formatting: Set of formatting types ('bold', 'italic', etc.)
        text: The text to wrap
        
    Returns:
        Text wrapped with appropriate HTML tags
    """
    if not formatting or not text:
        return html.escape(text) if text else ''
    
    result = html.escape(text)
    
    # Apply tags in consistent order (innermost first)
    if 'subscript' in formatting:
        result = f'<sub>{result}</sub>'
    if 'superscript' in formatting:
        result = f'<sup>{result}</sup>'
    if 'underline' in formatting:
        result = f'<u>{result}</u>'
    if 'italic' in formatting:
        result = f'<em>{result}</em>'
    if 'bold' in formatting:
        result = f'<strong>{result}</strong>'
    
    return result


def merge_formatting_for_revision(
    original_text: str,
    original_html: str,
    revised_text: str,
    revised_html: Optional[str] = None
) -> str:
    """
    Merge original formatting with user formatting to create combined HTML.
    
    This creates a complete formatted HTML representation of the revised text where:
    - For unchanged text: use user formatting if present, otherwise original formatting
    - For inserted text: use user formatting if present, otherwise no formatting
    
    This allows users to both:
    - Preserve original formatting (bold "Results:") when they don't change it
    - Apply new formatting to unchanged text (underline "effect") when they want
    
    Args:
        original_text: Plain text of the original paragraph
        original_html: HTML-formatted version of the original (with source formatting)
        revised_text: Plain text of the revision
        revised_html: Optional HTML from user's rich editor (contains user formatting)
        
    Returns:
        Combined HTML with user formatting taking precedence, falling back to 
        original formatting for unchanged text
    """
    # Compute the diff
    diff_result = compute_diff(original_text, revised_text)
    
    if not diff_result.has_changes:
        # No text changes - but user might have changed formatting!
        # Use user's HTML if provided, otherwise original
        if revised_html:
            return revised_html
        return original_html or html.escape(original_text)
    
    # Build formatting maps from both sources
    original_fmt_map = build_html_formatting_map(original_html) if original_html else []
    revised_fmt_map = build_html_formatting_map(revised_html) if revised_html else []
    
    # Track positions in original and revised text
    original_pos = 0
    revised_pos = 0
    
    result_parts = []
    
    for op in diff_result.operations:
        if op.op == DiffOperation.EQUAL:
            # Unchanged text - use user's formatting if they provided HTML
            # This respects both formatting additions AND removals by the user
            if revised_fmt_map:
                # User provided HTML - use their formatting (whether they added, kept, or removed it)
                user_segments = get_formatting_segments_for_range(
                    revised_fmt_map,
                    op.text,
                    revised_pos
                )
                for seg_text, formatting in user_segments:
                    result_parts.append(formatting_set_to_html_tags(formatting, seg_text))
            else:
                # No user HTML - use original formatting
                segments = get_formatting_segments_for_range(
                    original_fmt_map,
                    op.text,
                    original_pos
                ) if original_fmt_map else [(op.text, set())]
                
                for seg_text, formatting in segments:
                    result_parts.append(formatting_set_to_html_tags(formatting, seg_text))
            
            original_pos += len(op.text)
            revised_pos += len(op.text)
            
        elif op.op == DiffOperation.DELETE:
            # Deleted text - skip (not in result)
            original_pos += len(op.text)
            
        elif op.op == DiffOperation.INSERT:
            # Inserted text - use user's formatting
            segments = get_formatting_segments_for_range(
                revised_fmt_map,
                op.text,
                revised_pos
            ) if revised_fmt_map else [(op.text, set())]
            
            for seg_text, formatting in segments:
                result_parts.append(formatting_set_to_html_tags(formatting, seg_text))
            
            revised_pos += len(op.text)
    
    result = ''.join(result_parts)
    
    # Convert double newlines to proper paragraph HTML
    # This ensures multi-paragraph content is properly structured
    # Using </p><p> so strip_html_tags() will convert back to \n\n
    if '\n\n' in result:
        # Wrap in <p> tags and split on paragraph breaks
        paragraphs = result.split('\n\n')
        result = '<p>' + '</p><p>'.join(paragraphs) + '</p>'
    
    return result


# =============================================================================
# CLI FOR TESTING
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("diff_utils.py - Interactive Demo")
    print("=" * 60)
    
    # Demo 1: Basic diff
    print("\n1. Basic word replacement:")
    result = compute_diff(
        "The quick brown fox jumps over the lazy dog.",
        "The fast brown fox leaps over the sleepy dog."
    )
    print(f"   Original: {result.original}")
    print(f"   Revised:  {result.revised}")
    print(f"   Has changes: {result.has_changes}")
    print(f"   Summary: {result.change_summary}")
    print("   Operations:")
    for op in result.operations:
        print(f"      {op}")
    
    # Demo 2: HTML output
    print("\n2. HTML output:")
    html_output = diff_to_html(result)
    print(f"   {html_output[:200]}...")
    
    # Demo 3: Markdown output
    print("\n3. Markdown output:")
    md_output = diff_to_markdown(result)
    print(f"   {md_output}")
    
    # Demo 4: Word XML output
    print("\n4. Word XML output (first 300 chars):")
    xml_output, next_id = diff_to_word_xml(
        result,
        author="Test Author",
        timestamp="2026-01-19T12:00:00Z",
        base_revision_id=1,
        rsid="ABC12345"
    )
    print(f"   {xml_output[:300]}...")
    print(f"   Next revision ID: {next_id}")
    
    # Demo 5: Edge cases
    print("\n5. Edge cases:")
    
    # Identical strings
    result = compute_diff("Same text", "Same text")
    print(f"   Identical: has_changes={result.has_changes}, ops={len(result.operations)}")
    
    # Empty original
    result = compute_diff("", "New text")
    print(f"   Empty original: ops={result.operations}")
    
    # Empty revised
    result = compute_diff("Old text", "")
    print(f"   Empty revised: ops={result.operations}")
    
    # Complete replacement
    result = compute_diff("Old text", "New content")
    print(f"   Complete replacement: ops={result.operations}")
    
    print("\n" + "=" * 60)
    print("Demo complete!")
