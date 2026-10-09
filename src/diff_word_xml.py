"""Word track-changes XML emission from diffs."""

import html
import re
from typing import List, Optional, Tuple

from .diff_core import DiffOperation, DiffResult
from .diff_formatting import build_html_formatting_map, get_formatting_segments_for_range

def diff_to_word_xml(
    result: DiffResult,
    *,
    author: str,
    timestamp: str,
    base_revision_id: int,
    rsid: str,
    handle_newlines: bool = True
) -> Tuple[str, int]:
    """
    Convert diff to Word track changes XML.
    
    Generates <w:r>, <w:del>, and <w:ins> elements for each operation.
    
    Args:
        result: The diff result to convert
        author: Author name (will be XML-escaped)
        timestamp: ISO 8601 timestamp (e.g., '2026-01-19T10:30:00Z')
        base_revision_id: Starting w:id for del/ins elements
        rsid: Revision Save ID (8-char hex)
        handle_newlines: If True, convert \\n to <w:br/> elements
    
    Returns:
        Tuple of:
        - XML string containing runs (NOT wrapped in <w:p>)
        - Next available revision ID (for subsequent calls)
    
    Note:
        Caller is responsible for:
        - Wrapping in <w:p> with paragraph properties
        - Preserving comment markers and references
        - Handling field codes (call compute_diff only on safe regions)
    """
    safe_author = html.escape(author)
    parts = []
    current_id = base_revision_id
    
    for op in result.operations:
        if op.op == DiffOperation.EQUAL:
            # Regular run with unchanged text
            text_xml = _text_to_word_runs(op.text, rsid, handle_newlines)
            parts.append(text_xml)
            
        elif op.op == DiffOperation.DELETE:
            # Deleted text wrapped in w:del
            del_id = current_id
            current_id += 1
            
            del_text = html.escape(op.text)
            # For deletions, newlines become just text (delText doesn't support br)
            parts.append(
                f'<w:del w:id="{del_id}" w:author="{safe_author}" w:date="{timestamp}">'
                f'<w:r w:rsidDel="{rsid}">'
                f'<w:delText xml:space="preserve">{del_text}</w:delText>'
                f'</w:r>'
                f'</w:del>'
            )
            
        elif op.op == DiffOperation.INSERT:
            # Inserted text wrapped in w:ins
            ins_id = current_id
            current_id += 1
            
            if handle_newlines and '\n' in op.text:
                # Split by newlines and create runs with <w:br/>
                ins_content = _text_to_word_runs_with_breaks(op.text, rsid)
            else:
                ins_text = html.escape(op.text)
                ins_content = (
                    f'<w:r w:rsidR="{rsid}">'
                    f'<w:t xml:space="preserve">{ins_text}</w:t>'
                    f'</w:r>'
                )
            
            parts.append(
                f'<w:ins w:id="{ins_id}" w:author="{safe_author}" w:date="{timestamp}">'
                f'{ins_content}'
                f'</w:ins>'
            )
    
    return ''.join(parts), current_id


def _text_to_word_runs(text: str, rsid: str, handle_newlines: bool = True) -> str:
    """Convert text to Word XML runs, handling newlines."""
    if handle_newlines and '\n' in text:
        return _text_to_word_runs_with_breaks(text, rsid)
    else:
        safe_text = html.escape(text)
        return f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'


def _text_to_word_runs_with_breaks(text: str, rsid: str) -> str:
    """Convert text with newlines to Word XML runs with <w:br/> elements."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    parts = []
    
    for i, line in enumerate(lines):
        if line:
            safe_line = html.escape(line)
            parts.append(
                f'<w:r w:rsidR="{rsid}">'
                f'<w:t xml:space="preserve">{safe_line}</w:t>'
                f'</w:r>'
            )
        if i < len(lines) - 1:  # Add break after all but last line
            parts.append(f'<w:r w:rsidR="{rsid}"><w:br/></w:r>')
    
    return ''.join(parts)


# =============================================================================
# HTML TO WORD XML CONVERSION (for formatted text)
# =============================================================================

def html_to_word_runs(html_content: str, rsid: str) -> str:
    """
    Convert HTML-formatted text to Word XML runs with formatting.
    
    Supports: <strong>/<b>, <em>/<i>, <u>, <sup>, <sub>
    
    Args:
        html_content: HTML string with formatting tags
        rsid: Revision Save ID (8-char hex)
    
    Returns:
        Word XML string with <w:r> elements including <w:rPr> for formatting
    """
    from html.parser import HTMLParser
    
    class FormattedTextParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.runs = []
            self.current_text = ''
            self.formatting_stack = []  # Stack of active formatting tags
            
        def _flush_text(self):
            """Flush current text as a run with current formatting."""
            if self.current_text:
                self.runs.append({
                    'text': self.current_text,
                    'formatting': list(self.formatting_stack)
                })
                self.current_text = ''
        
        def handle_starttag(self, tag, attrs):
            self._flush_text()
            tag_lower = tag.lower()
            if tag_lower in ('strong', 'b'):
                self.formatting_stack.append('bold')
            elif tag_lower in ('em', 'i'):
                self.formatting_stack.append('italic')
            elif tag_lower == 'u':
                self.formatting_stack.append('underline')
            elif tag_lower == 'sup':
                self.formatting_stack.append('superscript')
            elif tag_lower == 'sub':
                self.formatting_stack.append('subscript')
            elif tag_lower == 'br':
                # Line break - add as special run
                self.runs.append({'break': True})
        
        def handle_endtag(self, tag):
            self._flush_text()
            tag_lower = tag.lower()
            # Remove the corresponding formatting from stack
            format_map = {
                'strong': 'bold', 'b': 'bold',
                'em': 'italic', 'i': 'italic',
                'u': 'underline',
                'sup': 'superscript',
                'sub': 'subscript'
            }
            if tag_lower in format_map:
                fmt = format_map[tag_lower]
                if fmt in self.formatting_stack:
                    self.formatting_stack.remove(fmt)
        
        def handle_data(self, data):
            self.current_text += data
        
        def handle_entityref(self, name):
            # Handle HTML entities like &amp;
            import html as html_module
            self.current_text += html_module.unescape(f'&{name};')
        
        def handle_charref(self, name):
            # Handle numeric character references
            import html as html_module
            self.current_text += html_module.unescape(f'&#{name};')
        
        def get_runs(self):
            self._flush_text()
            return self.runs
    
    # Parse the HTML
    parser = FormattedTextParser()
    try:
        parser.feed(html_content)
    except Exception:
        # Fallback to plain text if parsing fails
        safe_text = html.escape(html_content)
        return f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
    
    runs = parser.get_runs()
    
    # Convert runs to Word XML
    parts = []
    for run in runs:
        if run.get('break'):
            parts.append(f'<w:r w:rsidR="{rsid}"><w:br/></w:r>')
            continue
            
        text = run.get('text', '')
        if not text:
            continue
            
        formatting = run.get('formatting', [])
        safe_text = html.escape(text)
        
        # Build run properties if any formatting
        rPr = ''
        if formatting:
            rPr_parts = []
            if 'bold' in formatting:
                rPr_parts.append('<w:b/>')
            if 'italic' in formatting:
                rPr_parts.append('<w:i/>')
            if 'underline' in formatting:
                rPr_parts.append('<w:u w:val="single"/>')
            if 'superscript' in formatting:
                rPr_parts.append('<w:vertAlign w:val="superscript"/>')
            if 'subscript' in formatting:
                rPr_parts.append('<w:vertAlign w:val="subscript"/>')
            
            if rPr_parts:
                rPr = f'<w:rPr>{"".join(rPr_parts)}</w:rPr>'
        
        parts.append(
            f'<w:r w:rsidR="{rsid}">'
            f'{rPr}'
            f'<w:t xml:space="preserve">{safe_text}</w:t>'
            f'</w:r>'
        )
    
    return ''.join(parts) if parts else f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve"></w:t></w:r>'


def text_to_word_runs_with_formatting(
    text: str,
    formatting: set,
    rsid: str,
    handle_newlines: bool = True
) -> str:
    """
    Convert text to Word runs with specified formatting.
    
    Args:
        text: The text content
        formatting: Set of formatting tags ('bold', 'italic', 'underline', 'superscript', 'subscript')
        rsid: Revision Save ID
        handle_newlines: If True, convert newlines to <w:br/>
        
    Returns:
        Word XML string with formatted runs
    """
    # Build run properties
    rPr = ''
    if formatting:
        rPr_parts = []
        if 'bold' in formatting:
            rPr_parts.append('<w:b/>')
        if 'italic' in formatting:
            rPr_parts.append('<w:i/>')
        if 'underline' in formatting:
            rPr_parts.append('<w:u w:val="single"/>')
        if 'superscript' in formatting:
            rPr_parts.append('<w:vertAlign w:val="superscript"/>')
        if 'subscript' in formatting:
            rPr_parts.append('<w:vertAlign w:val="subscript"/>')
        if rPr_parts:
            rPr = f'<w:rPr>{"".join(rPr_parts)}</w:rPr>'
    
    if handle_newlines and '\n' in text:
        # Split by newlines and create runs with <w:br/>
        parts = []
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if line:
                safe_text = html.escape(line)
                parts.append(
                    f'<w:r w:rsidR="{rsid}">'
                    f'{rPr}'
                    f'<w:t xml:space="preserve">{safe_text}</w:t>'
                    f'</w:r>'
                )
            if i < len(lines) - 1:
                parts.append(f'<w:r w:rsidR="{rsid}">{rPr}<w:br/></w:r>')
        return ''.join(parts)
    else:
        safe_text = html.escape(text)
        return (
            f'<w:r w:rsidR="{rsid}">'
            f'{rPr}'
            f'<w:t xml:space="preserve">{safe_text}</w:t>'
            f'</w:r>'
        )


def text_to_word_runs_with_segmented_formatting(
    text: str,
    formatting_segments: List[Tuple[str, set]],
    rsid: str,
    handle_newlines: bool = True,
    track_formatting_changes: bool = False,
    author: Optional[str] = None,
    timestamp: Optional[str] = None
) -> str:
    """
    Convert text to Word runs with per-segment formatting.
    
    Each segment can have different formatting, allowing for partial formatting
    within an insertion (e.g., only "p" is italic in "p<0.001").
    
    Args:
        text: The full text (for validation)
        formatting_segments: List of (text_segment, formatting_set) tuples
        rsid: Revision Save ID
        handle_newlines: If True, convert newlines to <w:br/>
        track_formatting_changes: If True, add <w:rPrChange> to track formatting on new text
        author: Author for rPrChange (required if track_formatting_changes=True)
        timestamp: Timestamp for rPrChange (required if track_formatting_changes=True)
        
    Returns:
        Word XML string with multiple runs, each with appropriate formatting
    """
    parts = []
    safe_author = html.escape(author) if author else "Unknown"
    
    for seg_text, formatting in formatting_segments:
        if not seg_text:
            continue
            
        # Build run properties for this segment
        rPr = ''
        if formatting:
            rPr_parts = []
            if 'bold' in formatting:
                rPr_parts.append('<w:b/>')
            if 'italic' in formatting:
                rPr_parts.append('<w:i/>')
            if 'underline' in formatting:
                rPr_parts.append('<w:u w:val="single"/>')
            if 'superscript' in formatting:
                rPr_parts.append('<w:vertAlign w:val="superscript"/>')
            if 'subscript' in formatting:
                rPr_parts.append('<w:vertAlign w:val="subscript"/>')
            
            if rPr_parts:
                # If tracking formatting changes, add rPrChange to show the formatting was added
                # The "original" for new text is no formatting, so rPrChange has empty rPr
                if track_formatting_changes and author and timestamp:
                    rPr = (
                        f'<w:rPr>'
                        f'{"".join(rPr_parts)}'
                        f'<w:rPrChange w:id="0" w:author="{safe_author}" w:date="{timestamp}">'
                        f'<w:rPr/>'  # Empty - original had no formatting
                        f'</w:rPrChange>'
                        f'</w:rPr>'
                    )
                else:
                    rPr = f'<w:rPr>{"".join(rPr_parts)}</w:rPr>'
        
        if handle_newlines and '\n' in seg_text:
            # Split by newlines and create runs with <w:br/>
            lines = seg_text.split('\n')
            for i, line in enumerate(lines):
                if line:
                    safe_text = html.escape(line)
                    parts.append(
                        f'<w:r w:rsidR="{rsid}">'
                        f'{rPr}'
                        f'<w:t xml:space="preserve">{safe_text}</w:t>'
                        f'</w:r>'
                    )
                if i < len(lines) - 1:
                    parts.append(f'<w:r w:rsidR="{rsid}">{rPr}<w:br/></w:r>')
        else:
            safe_text = html.escape(seg_text)
            parts.append(
                f'<w:r w:rsidR="{rsid}">'
                f'{rPr}'
                f'<w:t xml:space="preserve">{safe_text}</w:t>'
                f'</w:r>'
            )
    
    return ''.join(parts) if parts else f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve"></w:t></w:r>'


def diff_to_word_xml_with_formatting(
    result: DiffResult,
    *,
    author: str,
    timestamp: str,
    base_revision_id: int,
    rsid: str,
    revised_text_html: Optional[str] = None,
    handle_newlines: bool = True
) -> Tuple[str, int]:
    """
    Convert diff to Word track changes XML with optional formatting on insertions.
    
    This extends diff_to_word_xml to support user-applied formatting:
    - EQUAL: Creates regular runs (no formatting applied - preserves diff granularity)
    - DELETE: Wraps text in <w:del>
    - INSERT: Applies formatting from revised_text_html if provided
    
    This maintains word-level diff granularity while applying user formatting
    to inserted text only.
    """
    safe_author = html.escape(author)
    parts = []
    current_id = base_revision_id
    
    # Build formatting map from HTML if provided
    formatting_map = None
    if revised_text_html:
        formatting_map = build_html_formatting_map(revised_text_html)
    
    # Track position in revised text (for mapping to formatting)
    revised_pos = 0
    
    for op in result.operations:
        if op.op == DiffOperation.EQUAL:
            # Regular run with unchanged text
            text_xml = _text_to_word_runs(op.text, rsid, handle_newlines)
            parts.append(text_xml)
            # Advance position in revised text (EQUAL text appears in both)
            revised_pos += len(op.text)
            
        elif op.op == DiffOperation.DELETE:
            # Deleted text wrapped in w:del
            del_id = current_id
            current_id += 1
            
            del_text = html.escape(op.text)
            # For deletions, newlines become just text (delText doesn't support br)
            parts.append(
                f'<w:del w:id="{del_id}" w:author="{safe_author}" w:date="{timestamp}">'
                f'<w:r w:rsidDel="{rsid}">'
                f'<w:delText xml:space="preserve">{del_text}</w:delText>'
                f'</w:r>'
                f'</w:del>'
            )
            # DELETE doesn't advance revised_pos (deleted text isn't in revised)
            
        elif op.op == DiffOperation.INSERT:
            # Inserted text wrapped in w:ins
            ins_id = current_id
            current_id += 1
            
            # Get segmented formatting for this insertion from HTML
            # This preserves formatting boundaries within the inserted text
            if formatting_map:
                formatting_segments = get_formatting_segments_for_range(
                    formatting_map,
                    op.text,
                    revised_pos
                )
                ins_content = text_to_word_runs_with_segmented_formatting(
                    op.text, formatting_segments, rsid, handle_newlines
                )
            else:
                # No formatting - use simple run
                ins_content = text_to_word_runs_with_formatting(
                    op.text, set(), rsid, handle_newlines
                )
            
            parts.append(
                f'<w:ins w:id="{ins_id}" w:author="{safe_author}" w:date="{timestamp}">'
                f'{ins_content}'
                f'</w:ins>'
            )
            # Advance position in revised text
            revised_pos += len(op.text)
    
    return ''.join(parts), current_id


# =============================================================================
# MARKDOWN TRANSFORMER (for debugging/logging)
# =============================================================================

