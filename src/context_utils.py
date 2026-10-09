"""
Context Utilities - Paragraph context extraction and table handling.

This module provides functions for:
- Extracting context paragraphs around referenced text
- Grouping table rows for proper HTML rendering
- Highlighting text within table cells
- Parsing markdown tables
- Computing per-cell table diffs

These functions were extracted from main.py to centralize context-related logic.
"""

import re
from typing import List, Dict, Any, Optional, Tuple


# =============================================================================
# TABLE PARSING AND FORMATTING
# =============================================================================

def highlight_cell_in_row(row_text: str, search_text: str, occurrence: int = 1) -> str:
    """
    Highlight the matching cell text within a pipe-separated row.
    
    Handles whitespace variations:
    - Extra spaces around commas ("Name1, Name2" vs "Name1 ,  Name2")
    - Multiple spaces normalized to single space
    - Leading/trailing whitespace in cells
    
    Args:
        row_text: Pipe-separated row string (e.g., "AUTHOR(S): | Name1, Name2 | Note")
        search_text: The text to highlight
        occurrence: Which occurrence to highlight (1-based, default 1)
        
    Returns:
        Row with matching cell wrapped in <mark> tags
    """
    if not search_text or not row_text:
        return row_text
    
    search_text = search_text.strip()
    
    # Method 1: Try exact match on the full row, finding the Nth occurrence
    if search_text in row_text:
        # Find the Nth occurrence
        pos = -1
        for i in range(occurrence):
            pos = row_text.find(search_text, pos + 1)
            if pos == -1:
                # Occurrence not found, highlight first one
                pos = row_text.find(search_text)
                break
        
        if pos != -1:
            return row_text[:pos] + f'<mark>{search_text}</mark>' + row_text[pos + len(search_text):]
    
    # Method 2: Build a flexible regex pattern that allows varying whitespace
    def build_flexible_pattern(text: str) -> str:
        # Escape regex special characters
        escaped = re.escape(text)
        # Replace literal spaces with pattern that matches 1+ whitespace chars
        flexible = escaped.replace(r'\ ', r'\s+')
        # Also allow optional whitespace around commas
        flexible = flexible.replace(r',', r'\s*,\s*')
        return flexible
    
    pattern = build_flexible_pattern(search_text)
    
    try:
        match = re.search(pattern, row_text, re.IGNORECASE)
        if match:
            matched_text = match.group(0)
            return row_text.replace(matched_text, f'<mark>{matched_text}</mark>', 1)
    except re.error:
        pass  # Invalid regex, fall through to cell-by-cell matching
    
    # Method 3: Cell-by-cell matching with normalization
    cells = row_text.split(' | ')
    highlighted_cells = []
    found_match = False
    
    # Normalize function: collapse whitespace, normalize punctuation spacing
    def normalize(text: str) -> str:
        text = ' '.join(text.split())  # Collapse whitespace
        text = re.sub(r'\s*,\s*', ', ', text)  # Normalize comma spacing
        return text
    
    normalized_search = normalize(search_text)
    
    for cell in cells:
        if found_match:
            highlighted_cells.append(cell)
            continue
            
        cell_stripped = cell.strip()
        normalized_cell = normalize(cell_stripped)
        
        # Check if normalized search text matches normalized cell (exact or substring)
        if normalized_search == normalized_cell:
            # Entire cell matches - highlight whole cell
            highlighted_cells.append(f'<mark>{cell}</mark>')
            found_match = True
            continue
        elif normalized_search in normalized_cell:
            # Partial match within cell - highlight whole cell (safer than trying to find exact span)
            highlighted_cells.append(f'<mark>{cell}</mark>')
            found_match = True
            continue
        elif normalized_cell and normalized_cell in normalized_search:
            # Cell content is a substring of search text (multi-cell reference)
            # This can happen if the comment references text spanning multiple cells
            # Highlight this cell but keep looking for more matches
            highlighted_cells.append(f'<mark>{cell}</mark>')
            continue
        
        highlighted_cells.append(cell)
    
    return ' | '.join(highlighted_cells)


def parse_table_row(row_text: str) -> List[str]:
    """
    Parse a markdown table row into a list of cell values.
    
    Handles format: | cell1 | cell2 | cell3 |
    
    Args:
        row_text: Pipe-separated row string
        
    Returns:
        List of cell values (stripped of whitespace)
    """
    row_text = row_text.strip()
    
    # Remove leading/trailing pipes if present
    if row_text.startswith('|'):
        row_text = row_text[1:]
    if row_text.endswith('|'):
        row_text = row_text[:-1]
    
    # Split by pipe
    cells = row_text.split('|')
    
    # Strip whitespace from each cell
    return [cell.strip() for cell in cells]


def compute_table_diff_cells(
    original_rows: List[List[str]],
    revised_rows: List[List[str]],
    compute_diff_func,
    diff_to_html_func
) -> List[List[Dict[str, Any]]]:
    """
    Compute per-cell diffs for table rows.
    
    Args:
        original_rows: List of rows, each row is a list of cell texts
        revised_rows: List of rows, each row is a list of cell texts
        compute_diff_func: Function to compute diff between two strings
        diff_to_html_func: Function to convert diff result to HTML
        
    Returns:
        List of rows, each row is a list of dicts with:
        - 'html': The diff HTML for this cell
        - 'changed': Whether this cell changed
        - 'added': Whether this is a new row
        - 'deleted': Whether this row was deleted
    """
    result = []
    max_rows = max(len(original_rows), len(revised_rows))
    
    # Determine max columns across all rows
    max_cols = 0
    for row in original_rows + revised_rows:
        max_cols = max(max_cols, len(row))
    
    for i in range(max_rows):
        row_cells = []
        
        if i < len(original_rows) and i < len(revised_rows):
            # Both original and revised exist - compute diff per cell
            orig_row = original_rows[i]
            rev_row = revised_rows[i]
            
            for j in range(max_cols):
                orig_cell = orig_row[j] if j < len(orig_row) else ""
                rev_cell = rev_row[j] if j < len(rev_row) else ""
                
                if orig_cell == rev_cell:
                    row_cells.append({
                        'html': rev_cell,
                        'changed': False,
                        'added': False,
                        'deleted': False
                    })
                else:
                    diff_result = compute_diff_func(orig_cell, rev_cell)
                    diff_html = diff_to_html_func(diff_result)
                    row_cells.append({
                        'html': diff_html,
                        'changed': True,
                        'added': False,
                        'deleted': False
                    })
        elif i < len(revised_rows):
            # New row added
            rev_row = revised_rows[i]
            for j in range(max_cols):
                cell = rev_row[j] if j < len(rev_row) else ""
                row_cells.append({
                    'html': f'<span style="color: #28a745; background-color: #e8f5e9;">{cell}</span>',
                    'changed': True,
                    'added': True,
                    'deleted': False
                })
        else:
            # Row deleted
            orig_row = original_rows[i]
            for j in range(max_cols):
                cell = orig_row[j] if j < len(orig_row) else ""
                row_cells.append({
                    'html': f'<span style="text-decoration: line-through; color: #dc3545; background-color: #ffebee;">{cell}</span>',
                    'changed': True,
                    'added': False,
                    'deleted': True
                })
        
        result.append(row_cells)
    
    return result


def parse_markdown_table(markdown: str) -> List[List[str]]:
    """
    Parse a markdown table into a 2D array of cell values.
    
    Args:
        markdown: Markdown table string
        
    Returns:
        2D list of cell values: [[row0_col0, row0_col1], [row1_col0, row1_col1], ...]
    """
    rows = []
    lines = markdown.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            continue
        # Skip separator lines (|---|---|)
        if line.replace('|', '').replace('-', '').replace(':', '').strip() == '':
            continue
        # Parse cells
        cells = [c.strip() for c in line.split('|')]
        # Remove empty first/last elements from split
        if cells and cells[0] == '':
            cells = cells[1:]
        if cells and cells[-1] == '':
            cells = cells[:-1]
        rows.append(cells)
    return rows


def group_consecutive_table_rows(paragraphs: list) -> list:
    """
    Group consecutive table rows into table_group elements.
    
    Takes a flat list of paragraphs and returns a list where consecutive
    table rows are grouped together for proper HTML table rendering.
    
    Args:
        paragraphs: List of paragraph dicts
        
    Returns:
        List where each element is either:
        - A single paragraph dict (for non-table paragraphs)
        - A dict with type='table_group' containing 'rows' list
    """
    if not paragraphs:
        return []
    
    result = []
    current_table_rows = []
    
    for para in paragraphs:
        if para.get('type') == 'table_row':
            # Accumulate table rows
            current_table_rows.append(para)
        else:
            # Flush any accumulated table rows first
            if current_table_rows:
                # Determine if table continues above/below this group
                first_row = current_table_rows[0]
                last_row = current_table_rows[-1]
                continues_above = first_row.get('row_number', 1) > 1
                continues_below = last_row.get('row_number', 0) < last_row.get('total_rows', 0)
                
                result.append({
                    'type': 'table_group',
                    'rows': current_table_rows,
                    'continues_above': continues_above,
                    'continues_below': continues_below
                })
                current_table_rows = []
            
            # Add the non-table paragraph
            result.append(para)
    
    # Flush any remaining table rows
    if current_table_rows:
        first_row = current_table_rows[0]
        last_row = current_table_rows[-1]
        continues_above = first_row.get('row_number', 1) > 1
        continues_below = last_row.get('row_number', 0) < last_row.get('total_rows', 0)
        
        result.append({
            'type': 'table_group',
            'rows': current_table_rows,
            'continues_above': continues_above,
            'continues_below': continues_below
        })
    
    return result


# =============================================================================
# CONTEXT EXTRACTION
# =============================================================================

def create_paragraph_entry(
    para: dict,
    accepted_revisions: dict,
    session: dict = None,  # Now used for original_paragraph_cache lookup
    thread_original_text: dict = None  # Para IDs that THIS thread modified
) -> dict:
    """
    Create a display entry from a paragraph, applying any accepted revisions.
    
    IMPORTANT: This function is thread-aware when thread_original_text is provided.
    It shows revisions from OTHER threads but NOT from the current thread.

    Args:
        para: Paragraph dict from paragraph_cache (contains display_text for UI)
        accepted_revisions: Dict mapping para_id to revised HTML (source of truth)
                           Contains merged HTML with formatting preserved.
        session: Session dict (used to access original_paragraph_cache for formatting)
        thread_original_text: Dict of para_id -> original_text for paragraphs
                             that the CURRENT thread has modified

    Returns:
        Entry dict suitable for template rendering
    """
    from src.diff_utils import strip_html_tags
    from src.session_utils import get_paragraph_cache
    
    thread_original_text = thread_original_text or {}
    
    # Build lookup for original formatting from original model (Phase 4.5 refactor)
    original_para_by_id = {}
    if session:
        original_cache = get_paragraph_cache(session, use_original=True)
        for orig_para in original_cache:
            pid = orig_para.get('para_id')
            if pid:
                original_para_by_id[pid] = orig_para
            if orig_para.get('type') == 'table_row' and 'cells' in orig_para:
                for cell in orig_para['cells']:
                    cell_pid = cell.get('para_id')
                    if cell_pid:
                        original_para_by_id[cell_pid] = cell

    para_id = para.get('para_id')
    para_type = para.get('type', 'paragraph')

    if para_type == 'table_row':
        cells = para.get('cells', [])
        cell_texts = []
        cell_data = []  # For template rendering
        is_revised = False

        for cell in cells:
            cell_para_id = cell.get('para_id')
            cell_alignment = cell.get('alignment', '')
            
            # Check if THIS thread modified this cell
            is_this_thread_cell = cell_para_id in thread_original_text if cell_para_id else False
            is_other_thread_cell = (cell_para_id in accepted_revisions and not is_this_thread_cell) if cell_para_id else False

            if is_this_thread_cell:
                # This thread's revision - use original text and formatting
                cell_text = thread_original_text[cell_para_id]
                # Get original formatting from original_paragraph_cache
                orig_cell = original_para_by_id.get(cell_para_id, {})
                cell_formatted_html = orig_cell.get('display_formatted_html', orig_cell.get('formatted_html', cell.get('formatted_html', '')))
                cell_is_revised = False
            elif is_other_thread_cell:
                # Other thread's revision - use revised text
                cell_formatted_html = accepted_revisions[cell_para_id]
                cell_text = strip_html_tags(cell_formatted_html)
                is_revised = True
                cell_is_revised = True
            else:
                # Use display_text fields (already have original [1] instead of [CITATION_1])
                cell_text = cell.get('display_text', cell.get('text', ''))
                cell_formatted_html = cell.get('display_formatted_html', cell.get('formatted_html', ''))
                cell_is_revised = False

            cell_texts.append(cell_text)
            cell_data.append({
                'text': cell_text,
                'formatted_html': cell_formatted_html,
                'alignment': cell_alignment,
                'para_id': cell_para_id,
                'is_revised': cell_is_revised
            })
        
        text = ' | '.join(cell_texts)
        return {
            'text': text,
            'para_id': para_id,
            'is_revised': is_revised,
            'type': 'table_row',
            'row_number': para.get('row_number', 0),
            'total_rows': para.get('total_rows', 0),
            'col_count': para.get('col_count', len(cells)),
            'cells': cell_data  # Pass cells array for HTML table rendering
        }
    else:
        # Check if THIS thread modified this paragraph
        is_this_thread_revision = para_id in thread_original_text if para_id else False
        is_other_thread_revision = (para_id in accepted_revisions and not is_this_thread_revision) if para_id else False
        
        # accepted_revisions contains HTML (source of truth)
        # For revised paragraphs, use HTML directly from accepted_revisions
        # For non-revised paragraphs, use display_text fields from cache
        if is_this_thread_revision:
            # This thread's revision - use original text and formatting
            text = thread_original_text[para_id]
            # Get original formatting from original_paragraph_cache
            orig_para = original_para_by_id.get(para_id, {})
            formatted_html = orig_para.get('display_formatted_html', orig_para.get('formatted_html', para.get('formatted_html', '')))
            is_revised = False
        elif is_other_thread_revision:
            formatted_html = accepted_revisions.get(para_id, '')
            text = strip_html_tags(formatted_html)
            is_revised = True
        else:
            # Use display_text fields (already have original [1] instead of [CITATION_1])
            text = para.get('display_text', para.get('text', ''))
            formatted_html = para.get('display_formatted_html', para.get('formatted_html', ''))
            is_revised = False
        
        return {
            'text': text,
            'formatted_html': formatted_html,
            'alignment': para.get('alignment', ''),
            'para_id': para_id,
            'is_revised': is_revised,
            'type': para_type
        }


def get_context_paragraphs(
    session: dict, 
    thread_id: str, 
    settings: dict, 
    exact_text: str = None, 
    exact_text_occurrence: int = 1
) -> dict:
    """
    Get context paragraphs for a thread based on settings.
    
    IMPORTANT: This function is thread-aware. It shows paragraphs with revisions
    from OTHER threads, but NOT from the current thread. This ensures the UI
    shows what the LLM will receive as context.
    
    Args:
        session: The session dict containing paragraph_cache, thread_target_indices, etc.
        thread_id: The thread ID
        settings: Context settings with before_count, after_count, ref_start_offset, ref_end_offset
        exact_text: The exact text the comment references (for highlighting)
        exact_text_occurrence: Which occurrence of exact_text to highlight (1-based)
    
    Returns:
        {
            'before': [...],  # Grouped list (table_group or single paragraphs)
            'target': [...],  # Grouped list
            'after': [...]    # Grouped list
        }
        
    Each element in the lists is either:
    - A paragraph dict (type != 'table_group')
    - A table_group dict: {'type': 'table_group', 'rows': [...], 'continues_above': bool, 'continues_below': bool}
    
    Note: accepted_revisions contains HTML (source of truth for formatting).
    """
    from src.diff_utils import strip_html_tags
    from src.session_utils import get_paragraph_cache, get_thread_target_indices
    
    # Compute caches on demand from DOM model (Phase 4.5 refactor)
    paragraph_cache = get_paragraph_cache(session, use_original=False)
    thread_indices = get_thread_target_indices(session, use_original=False)
    accepted_revisions = session.get("accepted_revisions", {})
    
    # Get paragraphs that THIS thread has modified - we should show the ORIGINAL text
    # for these, not the accepted revision (to match what the LLM sees)
    thread_original_text = session.get("thread_original_text", {}).get(thread_id, {})
    
    # Get original paragraph cache for retrieving original formatting
    # Compute from original model to get formatting from before any edits
    original_paragraph_cache = get_paragraph_cache(session, use_original=True)
    # Build a lookup from para_id to original paragraph entry
    original_para_by_id = {}
    for para in original_paragraph_cache:
        pid = para.get('para_id')
        if pid:
            original_para_by_id[pid] = para
        # Also index cell para_ids for table rows
        if para.get('type') == 'table_row' and 'cells' in para:
            for cell in para['cells']:
                cell_pid = cell.get('para_id')
                if cell_pid:
                    original_para_by_id[cell_pid] = cell
    
    if thread_id not in thread_indices:
        return {'before': [], 'target': [], 'after': []}
    
    start_idx, end_idx = thread_indices[thread_id]
    
    # Apply ref offsets to expand/contract target range
    effective_start = max(0, start_idx + settings.get("ref_start_offset", 0))
    effective_end = min(len(paragraph_cache) - 1, end_idx + settings.get("ref_end_offset", 0))
    
    # Get requested context counts
    before_count = settings.get("before_count", 2)
    after_count = settings.get("after_count", 2)
    
    result = {
        'before': [],
        'target': [],
        'after': []
    }
    
    # Build before context - collect N non-ghost paragraphs going backwards
    # This ensures clicking + always adds a visible paragraph (if one exists)
    before_entries = []
    i = effective_start - 1
    while i >= 0 and len(before_entries) < before_count:
        para = paragraph_cache[i]
        # Skip ghost paragraphs (only deleted content, not visible in Word)
        if not para.get('is_ghost', False):
            before_entries.append(create_paragraph_entry(
                para, accepted_revisions, session, thread_original_text
            ))
        i -= 1
    # Reverse to get correct order (earliest first)
    result['before'] = list(reversed(before_entries))
    
    # Build target (referenced text) - show revised text if available
    # Skip ghost paragraphs (empty paragraphs from track changes)
    for i in range(effective_start, effective_end + 1):
        para = paragraph_cache[i]
        
        # Skip ghost paragraphs in target range too
        if para.get('is_ghost', False):
            continue
            
        para_id = para.get('para_id')
        para_type = para.get('type', 'paragraph')
        
        # Check if this is an original target or an expanded one
        is_original = start_idx <= i <= end_idx
        
        # Handle table_row: format row text with highlighting
        if para_type == 'table_row':
            cells = para.get('cells', [])
            # Use revised cell text if available (but not from THIS thread)
            cell_texts = []
            cell_data = []  # For template rendering
            is_revised = False
            
            for cell in cells:
                cell_para_id = cell.get('para_id')
                cell_text = cell.get('text', '')
                cell_formatted_html = cell.get('formatted_html', '')
                cell_alignment = cell.get('alignment', '')
                
                # Check if THIS thread modified this cell
                is_this_thread_cell = cell_para_id in thread_original_text if cell_para_id else False
                is_other_thread_cell = (cell_para_id in accepted_revisions and not is_this_thread_cell) if cell_para_id else False
                
                if is_this_thread_cell:
                    # This thread's revision - use original text and formatting
                    cell_text = thread_original_text[cell_para_id]
                    # Get original formatting from original_paragraph_cache
                    orig_cell = original_para_by_id.get(cell_para_id, {})
                    cell_formatted_html = orig_cell.get('display_formatted_html', orig_cell.get('formatted_html', cell_formatted_html))
                    cell_is_revised = False
                elif is_other_thread_cell:
                    # Other thread's revision - use revised text
                    cell_formatted_html = accepted_revisions[cell_para_id]
                    cell_text = strip_html_tags(cell_formatted_html)
                    is_revised = True
                    cell_is_revised = True
                else:
                    # Use display_text fields (already have original [1] instead of [CITATION_1])
                    cell_text = cell.get('display_text', cell_text)
                    cell_formatted_html = cell.get('display_formatted_html', cell_formatted_html)
                    cell_is_revised = False
                    
                cell_texts.append(cell_text)
                cell_data.append({
                    'text': cell_text,
                    'formatted_html': cell_formatted_html,
                    'alignment': cell_alignment,
                    'para_id': cell_para_id,
                    'is_revised': cell_is_revised
                })
            
            display_text = ' | '.join(cell_texts)
            
            entry = {
                'text': display_text,
                'para_id': para_id,
                'is_revised': is_revised,
                'is_original_target': is_original,
                'type': 'table_row',
                'row_number': para.get('row_number', 0),
                'total_rows': para.get('total_rows', 0),
                'col_count': para.get('col_count', len(cells)),
                'cells': cell_data  # Pass cells array for HTML table rendering
            }
            
            # Highlight the referenced cell if this is the original target
            if is_original and exact_text:
                highlighted_text = highlight_cell_in_row(display_text, exact_text, exact_text_occurrence)
                entry['text_highlighted'] = highlighted_text
        else:
            # Regular paragraph - use revised text if available
            # BUT: if THIS thread modified this paragraph, show ORIGINAL text
            # (to match what the LLM sees)
            is_this_thread_revision = para_id in thread_original_text if para_id else False
            is_other_thread_revision = (para_id in accepted_revisions and not is_this_thread_revision) if para_id else False
            
            # accepted_revisions contains HTML (source of truth)
            # For revised paragraphs, use HTML directly
            # For non-revised paragraphs, use original formatting from source
            if is_this_thread_revision:
                # This thread's revision - show the ORIGINAL text and formatting
                display_text = thread_original_text[para_id]
                # Use original formatting from original_paragraph_cache
                orig_para = original_para_by_id.get(para_id, {})
                formatted_html = orig_para.get('display_formatted_html', orig_para.get('formatted_html', para.get('formatted_html', '')))
                # Mark as NOT revised (since we're showing original)
                is_revised = False
            elif is_other_thread_revision:
                # Other thread's revision - show the revised text
                formatted_html = accepted_revisions.get(para_id, '')
                display_text = strip_html_tags(formatted_html)
                is_revised = True
            else:
                # Use display_text fields (already have original [1] instead of [CITATION_1])
                display_text = para.get('display_text', para.get('text', ''))
                formatted_html = para.get('display_formatted_html', para.get('formatted_html', ''))
                is_revised = False
            
            entry = {
                'text': display_text,
                'formatted_html': formatted_html,
                'alignment': para.get('alignment', ''),
                'para_id': para_id,
                'is_revised': is_revised,
                'is_original_target': is_original,
                'type': para_type
            }
        
        result['target'].append(entry)
    
    # Build after context - collect N non-ghost paragraphs going forwards
    i = effective_end + 1
    while i < len(paragraph_cache) and len(result['after']) < after_count:
        para = paragraph_cache[i]
        # Skip ghost paragraphs (only deleted content, not visible in Word)
        if not para.get('is_ghost', False):
            result['after'].append(create_paragraph_entry(
                para, accepted_revisions, session, thread_original_text
            ))
        i += 1
    
    # Group consecutive table rows for proper HTML table rendering
    return {
        'before': group_consecutive_table_rows(result['before']),
        'target': group_consecutive_table_rows(result['target']),
        'after': group_consecutive_table_rows(result['after'])
    }
