"""HTML diff presentation for UI display."""

import html
import re
from typing import List, Optional, Tuple

from difflib import SequenceMatcher

from .diff_core import DiffOperation, DiffResult, compute_diff

def diff_to_html(
    result: DiffResult,
    *,
    delete_style: str = "text-decoration: line-through; color: #dc3545; background-color: #ffebee;",
    insert_style: str = "color: #28a745; background-color: #e8f5e9;",
    equal_style: str = "",
    show_deletions: bool = True,
    escape_html_text: bool = True
) -> str:
    """
    Convert diff to HTML with inline styles.
    
    Args:
        result: The diff result to convert
        delete_style: CSS for deleted text (strikethrough red by default)
        insert_style: CSS for inserted text (green highlight by default)
        equal_style: CSS for unchanged text (none by default)
        show_deletions: If False, deleted text is hidden entirely
        escape_html_text: If True, escape < > & in text (recommended)
    
    Returns:
        HTML string safe for use in st.markdown(unsafe_allow_html=True)
    
    Example Output:
        'The <span style="text-decoration: line-through; color: #dc3545;">quick </span>'
        '<span style="color: #28a745;">fast </span>brown fox'
    """
    parts = []
    
    for op in result.operations:
        text = html.escape(op.text) if escape_html_text else op.text
        # Convert newlines to <br> for HTML display
        text = text.replace('\n', '<br>')
        
        if op.op == DiffOperation.EQUAL:
            if equal_style:
                parts.append(f'<span style="{equal_style}">{text}</span>')
            else:
                parts.append(text)
        elif op.op == DiffOperation.DELETE:
            if show_deletions:
                parts.append(f'<span style="{delete_style}">{text}</span>')
            # If not showing deletions, just skip
        elif op.op == DiffOperation.INSERT:
            parts.append(f'<span style="{insert_style}">{text}</span>')
    
    return ''.join(parts)


def _normalize_revised_paragraphs(revised_text: str, n_expected: int) -> List[str]:
    """
    When the LLM returns one block with single newlines instead of \\n\\n between
    paragraphs, split into n_expected segments so positional mapping works.
    """
    if revised_text is None or n_expected <= 0:
        return [p.strip() for p in (revised_text or "").split('\n\n') if p.strip()]
    paras = [p.strip() for p in revised_text.split('\n\n') if p.strip()]
    if len(paras) >= n_expected:
        return paras[:n_expected]
    if len(paras) == 1 and n_expected > 1 and '\n' in revised_text:
        lines = [ln.strip() for ln in revised_text.split('\n') if ln.strip()]
        if len(lines) >= n_expected:
            indices = [(i * len(lines)) // n_expected for i in range(n_expected + 1)]
            return ['\n'.join(lines[indices[i] : indices[i + 1]]) for i in range(n_expected)]
    return paras


def diff_to_html_paragraph_aware(
    original_text: str,
    revised_text: str,
    *,
    delete_style: str = "text-decoration: line-through; color: #dc3545; background-color: #ffebee;",
    insert_style: str = "color: #28a745; background-color: #e8f5e9;",
    paragraph_separator: str = "<br><br>",
    similarity_threshold: float = 0.4,
    use_positional_mapping: bool = False,
) -> str:
    """
    Paragraph-aware diff to HTML.
    
    Instead of diffing the entire text as one block, this function:
    1. Splits both texts into paragraphs (by \\n\\n)
    2. Aligns paragraphs by position (if use_positional_mapping and same count) or by similarity
    3. Diffs each paragraph pair independently
    4. Combines results with proper paragraph separators
    
    When use_positional_mapping is True and paragraph counts match, pairs orig_paras[i]
    with rev_paras[i] (same as export/accept). Use this for multi-paragraph threads
    where we know the order is preserved.
    
    Args:
        original_text: The original document text
        revised_text: The revised text (may have different paragraph count)
        delete_style: CSS for deleted text
        insert_style: CSS for inserted text
        paragraph_separator: HTML to insert between paragraphs
        similarity_threshold: Minimum ratio to consider paragraphs as matching
        use_positional_mapping: If True and len(orig_paras)==len(rev_paras), pair by index (no similarity)
        
    Returns:
        HTML string with proper diff highlighting
    """
    from difflib import SequenceMatcher

    original_text = original_text or ""
    revised_text = revised_text or ""

    # Split into paragraphs
    orig_paras = [p.strip() for p in original_text.split('\n\n') if p.strip()]
    rev_paras = [p.strip() for p in revised_text.split('\n\n') if p.strip()]

    # Multi-paragraph positional: if LLM used single newlines we get one rev block; normalize to match orig count
    if use_positional_mapping and len(orig_paras) > 1 and len(rev_paras) < len(orig_paras):
        rev_paras = _normalize_revised_paragraphs(revised_text, len(orig_paras))

    # Handle edge cases
    if not orig_paras and not rev_paras:
        return ""
    if not orig_paras:
        # All new paragraphs
        all_new = paragraph_separator.join(
            f'<span style="{insert_style}">{html.escape(p).replace(chr(10), "<br>")}</span>'
            for p in rev_paras
        )
        return all_new
    if not rev_paras:
        # All deleted paragraphs
        all_deleted = paragraph_separator.join(
            f'<span style="{delete_style}">{html.escape(p).replace(chr(10), "<br>")}</span>'
            for p in orig_paras
        )
        return all_deleted
    
    if len(orig_paras) == 1 and len(rev_paras) == 1:
        diff_result = compute_diff(orig_paras[0], rev_paras[0])
        return diff_to_html(
            diff_result, delete_style=delete_style, insert_style=insert_style
        )
    
    # Positional 1:1 mapping when requested and counts match (same as export/accept)
    if use_positional_mapping and len(orig_paras) == len(rev_paras):
        result_parts = []
        for i in range(len(orig_paras)):
            diff_result = compute_diff(orig_paras[i], rev_paras[i])
            result_parts.append(diff_to_html(
                diff_result, delete_style=delete_style, insert_style=insert_style
            ))
        return paragraph_separator.join(result_parts)
    
    # Align paragraphs using greedy similarity matching
    # Each revised paragraph tries to match with an original paragraph
    alignment = []  # List of (orig_idx or None, rev_idx or None)
    used_orig = set()
    used_rev = set()
    
    # Build similarity matrix
    # NOTE: autojunk=False is critical! With autojunk=True (default), SequenceMatcher
    # can severely underestimate similarity for scientific/technical text with repeated
    # patterns, returning ratios like 0.08 for text that's actually 88% similar.
    similarities = []
    for ri, rev_para in enumerate(rev_paras):
        for oi, orig_para in enumerate(orig_paras):
            ratio = SequenceMatcher(None, orig_para, rev_para, autojunk=False).ratio()
            if ratio >= similarity_threshold:
                similarities.append((ratio, oi, ri))
    
    # Sort by similarity (highest first) and greedily match
    similarities.sort(reverse=True)
    matches = {}  # rev_idx -> orig_idx
    for ratio, oi, ri in similarities:
        if oi not in used_orig and ri not in used_rev:
            matches[ri] = oi
            used_orig.add(oi)
            used_rev.add(ri)
    
    # Build alignment sequence in order of appearance
    # Track which original paragraphs were deleted (not matched)
    result_parts = []
    
    # Process in revised paragraph order, inserting deletions where appropriate
    last_matched_orig = -1
    
    for ri, rev_para in enumerate(rev_paras):
        if ri in matches:
            oi = matches[ri]
            
            # First, show any deleted original paragraphs between last match and this one
            for deleted_oi in range(last_matched_orig + 1, oi):
                if deleted_oi not in used_orig:
                    used_orig.add(deleted_oi)
                    deleted_html = f'<span style="{delete_style}">{html.escape(orig_paras[deleted_oi]).replace(chr(10), "<br>")}</span>'
                    result_parts.append(deleted_html)
            
            # Now diff this matched pair
            diff_result = compute_diff(orig_paras[oi], rev_para)
            para_html = diff_to_html(
                diff_result,
                delete_style=delete_style,
                insert_style=insert_style
            )
            result_parts.append(para_html)
            last_matched_orig = oi
        else:
            # New paragraph (no match in original)
            new_html = f'<span style="{insert_style}">{html.escape(rev_para).replace(chr(10), "<br>")}</span>'
            result_parts.append(new_html)
    
    # Show any remaining deleted paragraphs at the end
    for oi in range(len(orig_paras)):
        if oi not in used_orig:
            deleted_html = f'<span style="{delete_style}">{html.escape(orig_paras[oi]).replace(chr(10), "<br>")}</span>'
            result_parts.append(deleted_html)
    
    return paragraph_separator.join(result_parts)


def diff_to_editable_html(
    original_text: str,
    revised_html: str,
    *,
    original_html: str = None,
    insert_class: str = "diff-insert",
    delete_class: str = "diff-delete",
    similarity_threshold: float = 0.4,
    use_positional_mapping: bool = False,
) -> str:
    """
    Generate HTML for a unified editor with inline diff highlights.
    
    This creates HTML suitable for a contenteditable element where:
    - Insertions are highlighted (editable), formatting from revised_html
    - Deletions are shown with strikethrough (non-editable)
    - Equal text preserves formatting from revised_html
    
    Paragraphs are aligned by position (if use_positional_mapping and same count)
    or by similarity. Use positional mapping for multi-paragraph threads where
    order is preserved (same as export/accept).
    
    Args:
        original_text: Plain text of the original content
        revised_html: HTML of the revised content (with user formatting)
        original_html: HTML of the original content (optional, unused but kept for API compat)
        insert_class: CSS class for inserted text
        delete_class: CSS class for deleted text
        similarity_threshold: Minimum ratio to consider paragraphs as matching
        use_positional_mapping: If True and same paragraph count, pair by index (no similarity)
        
    Returns:
        HTML string suitable for contenteditable with diff highlights
    """
    revised_html = revised_html or ""
    original_text = original_text or ""
    revised_text = strip_html_tags(revised_html)

    # Split into paragraphs for alignment
    orig_paras = [p.strip() for p in original_text.split('\n\n') if p.strip()]
    rev_paras = [p.strip() for p in revised_text.split('\n\n') if p.strip()]

    # Multi-paragraph positional: normalize when LLM returned one block with single newlines
    if use_positional_mapping and len(orig_paras) > 1 and len(rev_paras) < len(orig_paras):
        rev_paras = _normalize_revised_paragraphs(revised_text, len(orig_paras))

    # Also split revised HTML by paragraph tags - we need to track HTML for each paragraph
    # The revised_html uses <p>...</p> tags
    import re
    rev_html_paras = re.findall(r'<p[^>]*>(.*?)</p>', revised_html, re.DOTALL)
    if not rev_html_paras:
        # No <p> tags, treat whole thing as one paragraph
        rev_html_paras = [revised_html]
    
    # Handle edge cases
    if not orig_paras and not rev_paras:
        return ""
    if not orig_paras:
        # All new - wrap entire revised HTML as insert
        return (
            f'<span class="{insert_class}" '
            f'style="background-color: #d4edda; border-bottom: 2px solid #28a745;">'
            f'{revised_html}</span>'
        )
    if not rev_paras:
        # All deleted
        escaped = html.escape(original_text)
        return (
            f'<span class="{delete_class}" contenteditable="false" '
            f'style="text-decoration: line-through; color: #dc3545; background-color: #ffebee; '
            f'opacity: 0.8; cursor: not-allowed;">{escaped}</span>'
        )
    
    if len(orig_paras) == 1 and len(rev_paras) == 1:
        rev_para_html = rev_html_paras[0] if rev_html_paras else html.escape(rev_paras[0])
        return _diff_paragraph_to_editable_html(
            orig_paras[0], rev_paras[0], rev_para_html, insert_class, delete_class
        )
    
    # Positional 1:1 mapping when requested and counts match (same as export/accept)
    if use_positional_mapping and len(orig_paras) == len(rev_paras):
        result_parts = []
        for i in range(len(orig_paras)):
            rev_para_html = rev_html_paras[i] if i < len(rev_html_paras) else html.escape(rev_paras[i])
            para_diff_html = _diff_paragraph_to_editable_html(
                orig_paras[i], rev_paras[i], rev_para_html, insert_class, delete_class
            )
            result_parts.append(para_diff_html)
        return '<br>'.join(result_parts)
    
    # Align paragraphs using similarity matching
    # NOTE: autojunk=False is critical for accurate similarity on technical text
    used_orig = set()
    used_rev = set()
    similarities = []
    
    for ri, rev_para in enumerate(rev_paras):
        for oi, orig_para in enumerate(orig_paras):
            ratio = SequenceMatcher(None, orig_para, rev_para, autojunk=False).ratio()
            if ratio >= similarity_threshold:
                similarities.append((ratio, oi, ri))
    
    # Sort by similarity (highest first) and greedily match
    similarities.sort(reverse=True)
    matches = {}  # rev_idx -> orig_idx
    for ratio, oi, ri in similarities:
        if oi not in used_orig and ri not in used_rev:
            matches[ri] = oi
            used_orig.add(oi)
            used_rev.add(ri)
    
    # Build result by processing in revised paragraph order
    result_parts = []
    last_matched_orig = -1
    
    for ri, rev_para in enumerate(rev_paras):
        # Get HTML for this revised paragraph
        rev_para_html = rev_html_paras[ri] if ri < len(rev_html_paras) else html.escape(rev_para)
        
        if ri in matches:
            oi = matches[ri]
            orig_para = orig_paras[oi]
            
            # Show any deleted paragraphs between last match and this one
            for skip_oi in range(last_matched_orig + 1, oi):
                if skip_oi not in used_orig:
                    escaped = html.escape(orig_paras[skip_oi])
                    result_parts.append(
                        f'<span class="{delete_class}" contenteditable="false" '
                        f'style="text-decoration: line-through; color: #dc3545; background-color: #ffebee; '
                        f'opacity: 0.8; cursor: not-allowed;">{escaped}</span>'
                    )
            
            last_matched_orig = oi
            
            # Compute word-level diff for this paragraph pair
            para_diff_html = _diff_paragraph_to_editable_html(
                orig_para, rev_para, rev_para_html, insert_class, delete_class
            )
            result_parts.append(para_diff_html)
        else:
            # This is a new paragraph - mark all as insert
            result_parts.append(
                f'<span class="{insert_class}" '
                f'style="background-color: #d4edda; border-bottom: 2px solid #28a745;">'
                f'{rev_para_html}</span>'
            )
    
    # Show any remaining deleted paragraphs at the end
    for oi in range(last_matched_orig + 1, len(orig_paras)):
        if oi not in used_orig:
            escaped = html.escape(orig_paras[oi])
            result_parts.append(
                f'<span class="{delete_class}" contenteditable="false" '
                f'style="text-decoration: line-through; color: #dc3545; background-color: #ffebee; '
                f'opacity: 0.8; cursor: not-allowed;">{escaped}</span>'
            )
    
    # Join paragraphs with a single line break
    # Minimal separation to avoid extra blank lines in the UI
    return '<br>'.join(result_parts)


def _diff_paragraph_to_editable_html(
    orig_para: str,
    rev_para: str,
    rev_para_html: str,
    insert_class: str,
    delete_class: str,
) -> str:
    """
    Compute word-level diff for a single paragraph pair.
    
    Returns HTML with diff highlighting, preserving formatting from rev_para_html.
    """
    # Compute diff on plain text
    diff_result = compute_diff(orig_para, rev_para)
    
    parts = []
    revised_text_pos = 0
    revised_html_pos = 0
    
    for op in diff_result.operations:
        if op.op == DiffOperation.DELETE:
            # Deleted text - show as non-editable strikethrough
            escaped_text = html.escape(op.text)
            parts.append(
                f'<span class="{delete_class}" contenteditable="false" '
                f'style="text-decoration: line-through; color: #dc3545; background-color: #ffebee; '
                f'opacity: 0.8; cursor: not-allowed;">{escaped_text}</span>'
            )
            
        elif op.op == DiffOperation.INSERT:
            # Inserted text - highlight and preserve formatting from revised_html
            insert_len = len(op.text)
            
            # Extract the corresponding HTML portion
            html_segment = _extract_html_for_text_range(
                rev_para_html, revised_html_pos, revised_text_pos, insert_len
            )
            
            # Wrap in insert highlight
            parts.append(
                f'<span class="{insert_class}" '
                f'style="background-color: #d4edda; border-bottom: 2px solid #28a745;">'
                f'{html_segment}</span>'
            )
            
            revised_text_pos += insert_len
            revised_html_pos += len(html_segment)
            
        elif op.op == DiffOperation.EQUAL:
            # Equal text - use revised HTML (user's formatting)
            equal_len = len(op.text)
            
            revised_segment = _extract_html_for_text_range(
                rev_para_html, revised_html_pos, revised_text_pos, equal_len
            )
            parts.append(revised_segment)
            
            revised_text_pos += equal_len
            revised_html_pos += len(revised_segment)
    
    return ''.join(parts)


def _extract_html_for_text_range(
    html_content: str,
    html_start: int,
    text_start: int,
    text_length: int
) -> str:
    """
    Extract a portion of HTML that corresponds to a text range.
    
    This walks through HTML from html_start, tracking text positions,
    and extracts the HTML that covers text_length characters of text.
    
    Args:
        html_content: The full HTML string
        html_start: Starting position in HTML string
        text_start: Starting position in plain text (for reference)
        text_length: Number of text characters to extract
        
    Returns:
        HTML substring covering the text range
    """
    if text_length == 0:
        return ''
    
    result = []
    text_count = 0
    i = html_start
    
    while i < len(html_content) and text_count < text_length:
        char = html_content[i]
        
        if char == '<':
            # HTML tag - find the end and include it
            tag_end = html_content.find('>', i)
            if tag_end == -1:
                # Malformed HTML, just take the rest
                result.append(html_content[i:])
                break
            result.append(html_content[i:tag_end + 1])
            i = tag_end + 1
        elif char == '&':
            # HTML entity - find the end
            entity_end = html_content.find(';', i)
            if entity_end == -1 or entity_end - i > 10:
                # Not a valid entity, treat as regular char
                result.append(char)
                text_count += 1
                i += 1
            else:
                result.append(html_content[i:entity_end + 1])
                text_count += 1  # Entity represents one character
                i = entity_end + 1
        else:
            # Regular character
            result.append(char)
            text_count += 1
            i += 1
    
    # Consume any trailing closing tags so they stay with the text they
    # belong to rather than leaking into the next extracted segment.
    while i < len(html_content) and html_content[i] == '<':
        if html_content[i:i+2] == '</':
            tag_end = html_content.find('>', i)
            if tag_end == -1:
                break
            result.append(html_content[i:tag_end + 1])
            i = tag_end + 1
        else:
            break
    
    return ''.join(result)


# =============================================================================
# WORD XML TRANSFORMER (for Track Changes)
# =============================================================================

def strip_html_tags(html_content: Optional[str], preserve_paragraphs: bool = True) -> str:
    """
    Strip HTML tags from content, returning plain text.

    Useful for extracting plain text from HTML-formatted content.

    Args:
        html_content: HTML string to strip (None treated as "")
        preserve_paragraphs: If True, converts paragraph elements (<p>, <div>, <br>)
                            to newlines, preserving document structure. Default True.
    """
    if html_content is None:
        return ""
    from html.parser import HTMLParser
    
    # Tags that indicate paragraph/block boundaries
    BLOCK_TAGS = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
    
    class TagStripper(HTMLParser):
        def __init__(self, preserve_paras: bool):
            super().__init__()
            self.parts = []
            self.preserve_paras = preserve_paras
            self._pending_newline = False
            
        def handle_starttag(self, tag, attrs):
            tag_lower = tag.lower()
            if self.preserve_paras and tag_lower in BLOCK_TAGS:
                if tag_lower == 'br':
                    # <br> is self-closing, add newline immediately
                    self.parts.append('\n')
                elif self.parts:
                    # For other block tags, add newline before (if we have content)
                    self._pending_newline = True
        
        def handle_startendtag(self, tag, attrs):
            # Handle self-closing tags like <br/>
            tag_lower = tag.lower()
            if self.preserve_paras and tag_lower == 'br':
                self.parts.append('\n')
            
        def handle_endtag(self, tag):
            if self.preserve_paras and tag.lower() in BLOCK_TAGS:
                # For closing block tags, add newline after
                if tag.lower() == 'br':
                    self.parts.append('\n')
                elif tag.lower() in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                    # Paragraph boundaries become double newlines
                    self.parts.append('\n\n')
            
        def handle_data(self, data):
            if self._pending_newline and data.strip():
                self.parts.append('\n\n')
                self._pending_newline = False
            self.parts.append(data)
            
        def handle_entityref(self, name):
            import html as html_module
            self.parts.append(html_module.unescape(f'&{name};'))
            
        def handle_charref(self, name):
            import html as html_module
            self.parts.append(html_module.unescape(f'&#{name};'))
        
        def get_text(self):
            text = ''.join(self.parts)
            if self.preserve_paras:
                # Clean up multiple consecutive newlines
                text = re.sub(r'\n{3,}', '\n\n', text)
                # Strip leading/trailing whitespace
                text = text.strip()
            return text
    
    stripper = TagStripper(preserve_paragraphs)
    try:
        stripper.feed(html_content)
        return stripper.get_text()
    except Exception:
        # Fallback: simple regex strip with paragraph handling.
        # Must decode HTML entities so plain text matches main path (e.g. &#8805; -> ≥, &gt; -> >).
        if preserve_paragraphs:
            result = html_content
            result = re.sub(r'<br\s*/?>', '\n', result, flags=re.IGNORECASE)
            result = re.sub(r'</(?:p|div|li|tr|h[1-6])>', '\n\n', result, flags=re.IGNORECASE)
            result = re.sub(r'<[^>]+>', '', result)
            result = re.sub(r'\n{3,}', '\n\n', result)
            result = result.strip()
        else:
            result = re.sub(r'<[^>]+>', '', html_content)
        return html.unescape(result) if result else ""


def highlight_text_in_html(
    html_content: str, 
    text_to_highlight: str, 
    occurrence: int = 1,
    mark_class: str = "bg-yellow-200 px-0.5 rounded"
) -> str:
    """
    Insert <mark> tags around text_to_highlight within HTML content,
    preserving all existing HTML tags and formatting.
    
    Args:
        html_content: HTML string potentially containing formatting tags
        text_to_highlight: Plain text to find and highlight
        occurrence: Which occurrence to highlight (1-based, default 1)
        mark_class: CSS class for the mark element
        
    Returns:
        HTML with <mark> tags inserted around the highlighted text
        
    Example:
        highlight_text_in_html(
            "<strong>Results:</strong> The data shows BMI.",
            "BMI",
            1
        ) -> "<strong>Results:</strong> The data shows <mark class=\"...\">BMI</mark>."
    """
    if not html_content or not text_to_highlight:
        return html_content
    
    # Get plain text to find the position
    plain_text = strip_html_tags(html_content)
    
    # Find the Nth occurrence in plain text
    start_pos = -1
    for i in range(occurrence):
        start_pos = plain_text.find(text_to_highlight, start_pos + 1)
        if start_pos == -1:
            # Text not found at this occurrence
            return html_content
    
    end_pos = start_pos + len(text_to_highlight)
    
    # Now walk through the HTML, tracking text position, and insert marks
    # We need to find where in the HTML string corresponds to text positions
    result = []
    text_index = 0  # Current position in plain text
    html_index = 0  # Current position in HTML string
    mark_start_inserted = False
    mark_end_inserted = False
    
    while html_index < len(html_content):
        char = html_content[html_index]
        
        if char == '<':
            # We're at a tag - find the end and copy it as-is
            tag_end = html_content.find('>', html_index)
            if tag_end == -1:
                # Malformed HTML, just copy rest
                result.append(html_content[html_index:])
                break
            
            # Check if we need to insert mark before this tag
            if not mark_start_inserted and text_index == start_pos:
                result.append(f'<mark class="{mark_class}">')
                mark_start_inserted = True
            
            # Copy the tag
            result.append(html_content[html_index:tag_end + 1])
            html_index = tag_end + 1
        elif char == '&':
            # HTML entity - find the end
            entity_end = html_content.find(';', html_index)
            if entity_end == -1:
                # Not a valid entity, treat as regular char
                entity_end = html_index
            
            # Check if we need to insert mark start
            if not mark_start_inserted and text_index == start_pos:
                result.append(f'<mark class="{mark_class}">')
                mark_start_inserted = True
            
            # Copy the entity
            result.append(html_content[html_index:entity_end + 1])
            html_index = entity_end + 1
            text_index += 1  # Entity represents one character
            
            # Check if we need to insert mark end
            if mark_start_inserted and not mark_end_inserted and text_index == end_pos:
                result.append('</mark>')
                mark_end_inserted = True
        else:
            # Regular character
            # Check if we need to insert mark start
            if not mark_start_inserted and text_index == start_pos:
                result.append(f'<mark class="{mark_class}">')
                mark_start_inserted = True
            
            result.append(char)
            html_index += 1
            text_index += 1
            
            # Check if we need to insert mark end
            if mark_start_inserted and not mark_end_inserted and text_index == end_pos:
                result.append('</mark>')
                mark_end_inserted = True
    
    # If we started but didn't end the mark (shouldn't happen with valid input)
    if mark_start_inserted and not mark_end_inserted:
        result.append('</mark>')
    
    return ''.join(result)


