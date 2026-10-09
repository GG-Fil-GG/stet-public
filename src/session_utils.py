"""
Session model bridge utilities: paragraph cache, context helpers, placeholders.

Re-exports adapter and persistence symbols for backward compatibility.
"""

from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.document_model import DocumentModel
    from src.document_model.comments import CommentThread as DOMCommentThread


def get_model_from_session(session: Dict[str, Any]) -> Optional['DocumentModel']:
    """
    Get the current DocumentModel from a session.

    Args:
        session: Session dictionary

    Returns:
        DocumentModel if present, None for legacy sessions
    """
    return session.get("model")


def get_original_model(session: Dict[str, Any]) -> Optional['DocumentModel']:
    """
    Get the original DocumentModel (snapshot at session creation) from a session.
    
    This is used for computing diffs against the original document state.
    The model is deserialized on demand from original_model_data.

    Args:
        session: Session dictionary

    Returns:
        DocumentModel representing the original document state, or None if not available
    """
    from src.document_model import DocumentModel
    
    original_data = session.get("original_model_data")
    if original_data:
        return DocumentModel.from_dict(original_data)
    return None


def get_paragraph_cache(session: Dict[str, Any], use_original: bool = False) -> list:
    """
    Compute paragraph cache on demand from the DOM model.
    
    This replaces storing paragraph_cache/original_paragraph_cache in session.
    The cache is computed fresh each time, ensuring consistency with the model.

    Args:
        session: Session dictionary
        use_original: If True, compute from original model (for diffs).
                     If False, compute from current model.

    Returns:
        List of paragraph dicts in the standard cache format
    """
    if use_original:
        model = get_original_model(session)
    else:
        model = get_model_from_session(session)
    
    if model:
        return build_paragraph_cache_from_model(model)
    
    # Fallback for tests/legacy sessions that don't have a model
    # but provide paragraph_cache directly
    return session.get("paragraph_cache", [])


def get_thread_target_indices(session: Dict[str, Any], use_original: bool = False) -> Dict[str, tuple]:
    """
    Compute thread target indices on demand from the DOM model.
    
    This replaces storing thread_target_indices/original_thread_target_indices in session.
    The indices are computed fresh each time, ensuring consistency with the model.

    Args:
        session: Session dictionary
        use_original: If True, compute from original model (for diffs).
                     If False, compute from current model.

    Returns:
        Dict mapping thread_id to (start_idx, end_idx) tuple
    """
    if use_original:
        model = get_original_model(session)
    else:
        model = get_model_from_session(session)
    
    if model:
        return build_thread_target_indices_from_model(model)
    
    # Fallback for tests/legacy sessions that don't have a model
    # but provide thread_target_indices directly
    return session.get("thread_target_indices", {})


def is_dom_session(session: Dict[str, Any]) -> bool:
    """
    Check if this is a DOM-based session (Phase 6+).
    
    Args:
        session: Session dictionary
        
    Returns:
        True if session uses DOM model, False if legacy
    """
    return "model" in session and session["model"] is not None


def store_thread_original_text(
    session: Dict[str, Any],
    thread_id: str,
    para_id: str,
    original_text: str
) -> None:
    """
    Store the original text of a paragraph before a thread modifies it.
    
    This is used for thread-aware context generation. When regenerating
    suggestions for a thread, we need to show the document as it was
    before that thread's changes, while including other threads' changes.
    
    Args:
        session: Session dictionary
        thread_id: The thread that is about to modify the paragraph
        para_id: The paragraph being modified
        original_text: The text before modification
    """
    if "thread_original_text" not in session:
        session["thread_original_text"] = {}
    
    if thread_id not in session["thread_original_text"]:
        session["thread_original_text"][thread_id] = {}
    
    # Only store if not already recorded (first modification wins)
    if para_id not in session["thread_original_text"][thread_id]:
        session["thread_original_text"][thread_id][para_id] = original_text


def get_text_excluding_thread(
    session: Dict[str, Any],
    para_id: str,
    exclude_thread_id: str
) -> Optional[str]:
    """
    Get the text of a paragraph as it would appear without a specific thread's changes.
    
    This is the core function for thread-aware context generation. When regenerating
    suggestions for Thread A, we want to show the paragraph text that includes
    all other threads' changes but excludes Thread A's changes.
    
    Args:
        session: Session dictionary
        para_id: The paragraph to get text for
        exclude_thread_id: The thread whose changes should be excluded
        
    Returns:
        The original text if this thread modified the paragraph,
        or None if this thread hasn't modified this paragraph (use current text)
    """
    thread_original_text = session.get("thread_original_text", {})
    thread_data = thread_original_text.get(exclude_thread_id, {})
    return thread_data.get(para_id)


def clear_thread_original_text(
    session: Dict[str, Any],
    thread_id: str
) -> None:
    """
    Clear the stored original text for a thread.
    
    Called when a thread's acceptance is undone/regenerated, so we can
    re-record the original text on the next acceptance.
    
    Args:
        session: Session dictionary
        thread_id: The thread to clear original text for
    """
    thread_original_text = session.get("thread_original_text", {})
    if thread_id in thread_original_text:
        del thread_original_text[thread_id]


def get_paragraph_text_for_llm(
    session: Dict[str, Any],
    para_id: str,
    current_thread_id: str
) -> str:
    """
    Get the paragraph text to show in LLM context for a specific thread.
    
    This implements thread-aware context generation:
    - If the current thread has previously modified this paragraph,
      return the text as it was BEFORE that thread's changes
      (which includes any other threads' prior changes)
    - Otherwise, return the current paragraph text from the model
    
    This ensures that when regenerating suggestions for Thread A,
    the LLM sees the paragraph without Thread A's own prior changes,
    but with all other threads' changes included.
    
    Args:
        session: Session dictionary
        para_id: The paragraph to get text for
        current_thread_id: The thread we're generating suggestions for
        
    Returns:
        The appropriate paragraph text for LLM context
    """
    # Check if this thread has previously modified this paragraph
    thread_original_text = get_text_excluding_thread(session, para_id, current_thread_id)
    
    if thread_original_text is not None:
        # This thread modified this paragraph before - use the stored original
        return thread_original_text
    
    # This thread hasn't modified this paragraph - use current model text
    model = get_model_from_session(session)
    if model:
        para = model.get_paragraph(para_id)
        if para:
            return para.plain_text
    
    # Fallback: return empty string
    return ""


def get_threads_from_session(session: Dict[str, Any]) -> list:
    """
    Get thread objects from a session, regardless of whether it's DOM or legacy.
    
    For DOM sessions, converts DOM CommentThreads to a compatible format.
    For legacy sessions, returns the thread_objects list.
    
    Args:
        session: Session dictionary
        
    Returns:
        List of thread objects
    """
    if is_dom_session(session):
        model = session["model"]
        return list(model.comments.threads.values())
    else:
        return session.get("thread_objects", [])

def build_paragraph_cache_from_model(model: 'DocumentModel') -> list:
    """
    Build a paragraph cache compatible with the legacy format from a DocumentModel.
    
    This allows the existing LLMHandler context generation to work with DOM models.
    
    For tables, each row becomes a 'table_row' entry with cells array.
    For regular paragraphs, creates 'paragraph' entries.
    
    Each entry includes:
    - 'text': Text with [CITATION_X] placeholders (for internal/export use)
    - 'display_text': Text with original display (e.g., [1]) for UI display
    - 'formatted_html' / 'display_formatted_html': Same distinction for HTML
    
    Args:
        model: The DocumentModel to build cache from
        
    Returns:
        List of paragraph dicts in legacy format
    """
    from src.document_model.model import Table, Paragraph
    
    cache = []
    idx = 0
    
    for element in model.body.elements:
        if isinstance(element, Table):
            # Handle table - each row becomes a table_row entry
            total_rows = len(element.rows)
            for row_num, row in enumerate(element.rows):
                # Build cells array with both text versions and formatted HTML
                cells = []
                cell_texts = []
                cell_display_texts = []
                cell_formatted_htmls = []
                cell_display_formatted_htmls = []
                for cell in row:
                    # plain_text has placeholders, raw_text has original display
                    # to_html() generates HTML with formatting tags
                    # to_display_html() does the same but with display text
                    cells.append({
                        'para_id': cell.para_id,
                        'text': cell.plain_text,
                        'display_text': cell.raw_text,
                        'formatted_html': cell.to_html(),
                        'display_formatted_html': cell.to_display_html(),
                    })
                    cell_texts.append(cell.plain_text)
                    cell_display_texts.append(cell.raw_text)
                    cell_formatted_htmls.append(cell.to_html())
                    cell_display_formatted_htmls.append(cell.to_display_html())
                
                # Row text is pipe-separated cells
                row_text = ' | '.join(cell_texts)
                row_display_text = ' | '.join(cell_display_texts)
                row_formatted_html = ' | '.join(cell_formatted_htmls)
                row_display_formatted_html = ' | '.join(cell_display_formatted_htmls)
                
                # Use first cell's para_id as the row's para_id
                row_para_id = row[0].para_id if row else ''
                
                cache.append({
                    'idx': idx,
                    'para_id': row_para_id,
                    'text': row_text,
                    'display_text': row_display_text,
                    'type': 'table_row',
                    'cells': cells,
                    'row_number': row_num + 1,
                    'total_rows': total_rows,
                    'col_count': len(cells),
                    'formatted_html': row_formatted_html,
                    'display_formatted_html': row_display_formatted_html,
                })
                idx += 1
        elif isinstance(element, Paragraph):
            # Regular paragraph with HTML formatting
            # plain_text has placeholders, raw_text has original display
            # to_html() generates HTML with formatting tags (bold, italic, etc.)
            # to_display_html() does the same but with display text for field codes
            cache.append({
                'idx': idx,
                'para_id': element.para_id,
                'text': element.plain_text,
                'display_text': element.raw_text,
                'type': 'paragraph',
                'formatted_html': element.to_html(),
                'display_formatted_html': element.to_display_html(),
            })
            idx += 1
    
    return cache


def build_paragraph_cache_for_thread(
    session: Dict[str, Any],
    thread_id: str
) -> list:
    """
    Build a paragraph cache with thread-aware text for LLM context generation.
    
    This is similar to build_paragraph_cache_from_model(), but overrides the
    text for paragraphs that this thread has previously modified, showing
    the text as it was BEFORE this thread's changes.
    
    This implements the key thread-aware context rule:
    - When regenerating for Thread A, show text without Thread A's changes
    - Other threads' changes are included (they were part of the baseline
      when Thread A originally modified the paragraph)
    
    Args:
        session: Session dictionary
        thread_id: The thread we're generating suggestions for
        
    Returns:
        List of paragraph dicts with thread-aware text
    """
    model = get_model_from_session(session)
    if not model:
        return []
    
    # Start with the normal paragraph cache
    base_cache = build_paragraph_cache_from_model(model)
    
    # Get the stored original text for this thread's modifications
    thread_original_text = session.get("thread_original_text", {}).get(thread_id, {})
    
    if not thread_original_text:
        # This thread hasn't modified any paragraphs, return as-is
        return base_cache
    
    # Override text for paragraphs this thread has modified
    for entry in base_cache:
        para_id = entry.get("para_id")
        if para_id and para_id in thread_original_text:
            # Use the stored original text instead of current model text
            original_text = thread_original_text[para_id]
            entry["text"] = original_text
            entry["display_text"] = original_text  # For consistency
            # Note: We can't restore original HTML formatting here as we only stored text
            # The formatting merge will happen later using original model
        
        # For table rows, also check cell para_ids
        if entry.get("type") == "table_row" and "cells" in entry:
            cell_texts = []
            for cell in entry["cells"]:
                cell_para_id = cell.get("para_id")
                if cell_para_id and cell_para_id in thread_original_text:
                    original_cell_text = thread_original_text[cell_para_id]
                    cell["text"] = original_cell_text
                    cell["display_text"] = original_cell_text
                    cell_texts.append(original_cell_text)
                else:
                    cell_texts.append(cell.get("text", ""))
            # Update row text
            entry["text"] = " | ".join(cell_texts)
            entry["display_text"] = " | ".join(cell_texts)
    
    return base_cache


def build_thread_target_indices_from_model(model: 'DocumentModel') -> Dict[str, Tuple[int, int]]:
    """
    Build thread target indices compatible with the legacy format from a DocumentModel.
    
    This maps thread_id to (start_idx, end_idx) in the paragraph cache.
    For table cells, maps to the containing row's index.
    
    Args:
        model: The DocumentModel to analyze
        
    Returns:
        Dict mapping thread_id to (start_idx, end_idx) tuple
    """
    from typing import Tuple
    from src.document_model.model import Table, Paragraph
    
    # First, build a para_id to cache_idx mapping
    # This handles table rows where all cell para_ids map to the row index
    para_id_to_cache_idx: Dict[str, int] = {}
    cache_idx = 0
    
    for element in model.body.elements:
        if isinstance(element, Table):
            for row in element.rows:
                # Map ALL cell para_ids in this row to the row's cache index
                for cell in row:
                    para_id_to_cache_idx[cell.para_id] = cache_idx
                cache_idx += 1
        elif isinstance(element, Paragraph):
            para_id_to_cache_idx[element.para_id] = cache_idx
            cache_idx += 1
    
    # Now build thread indices using the mapping
    indices: Dict[str, Tuple[int, int]] = {}
    
    for thread_id, thread in model.comments.threads.items():
        if thread.root.anchor:
            anchor = thread.root.anchor
            start_para_id = anchor.para_id
            end_para_id = anchor.end_para_id  # May be None for single-paragraph anchors
            
            start_idx = para_id_to_cache_idx.get(start_para_id, -1)
            
            if start_idx >= 0:
                if end_para_id and end_para_id != start_para_id:
                    # Multi-paragraph anchor - find the end paragraph index
                    end_idx = para_id_to_cache_idx.get(end_para_id, start_idx)
                    # Ensure start <= end (handle edge cases)
                    if end_idx < start_idx:
                        start_idx, end_idx = end_idx, start_idx
                    indices[thread_id] = (start_idx, end_idx)
                else:
                    # Single-paragraph anchor
                    indices[thread_id] = (start_idx, start_idx)
    
    return indices


def convert_placeholders_to_display(
    text: str,
    session: Dict[str, Any],
    para_id: Optional[str] = None
) -> str:
    """
    Convert [CITATION_X] placeholders back to display text for UI display.
    
    This is necessary because:
    1. Field codes (EndNote citations) are replaced with placeholders at parse time
    2. The LLM receives and returns text with placeholders
    3. The UI should show the original display text (e.g., [1]), not placeholders
    
    Args:
        text: Text potentially containing [CITATION_X] placeholders
        session: Session dictionary containing the DocumentModel
        para_id: Optional paragraph ID to limit scope (uses all paragraphs if None)
        
    Returns:
        Text with placeholders replaced by original display text
    """
    import re
    
    # Quick check - if no placeholders, return as-is
    if '[CITATION_' not in text:
        return text
    
    result = text
    
    # Try current model first
    model = get_model_from_session(session)
    if model:
        # If para_id is specified, only check that paragraph
        if para_id:
            para = model.get_paragraph(para_id)
            if para and para.field_codes:
                result = para.get_display_text(result)
        else:
            # Check all paragraphs with field codes
            for para in model.body.iter_paragraphs():
                if para.field_codes:
                    result = para.get_display_text(result)
    
    # If placeholders still remain, try original_model_data as fallback
    # This handles cases where paragraphs with field_codes were modified/removed
    if '[CITATION_' in result:
        original_model = get_original_model(session)
        if original_model:
            if para_id:
                para = original_model.get_paragraph(para_id)
                if para and para.field_codes:
                    result = para.get_display_text(result)
            else:
                for para in original_model.body.iter_paragraphs():
                    if para.field_codes:
                        result = para.get_display_text(result)
    
    return result

from .session_adapters import CommentContext, ThreadContext, convert_dom_thread_for_llm
from .session_persistence import (
    count_thread_statuses,
    create_empty_session,
    create_session_from_model,
    deserialize_session_data,
    load_session_from_file,
    merge_loaded_session,
    save_session_to_file,
    serialize_session_for_save,
)

__all__ = [
    'CommentContext',
    'ThreadContext',
    'convert_dom_thread_for_llm',
    'create_empty_session',
    'create_session_from_model',
    'serialize_session_for_save',
    'deserialize_session_data',
    'save_session_to_file',
    'load_session_from_file',
    'merge_loaded_session',
    'count_thread_statuses',
    'get_model_from_session',
    'get_original_model',
    'get_paragraph_cache',
    'get_thread_target_indices',
    'is_dom_session',
    'store_thread_original_text',
    'get_text_excluding_thread',
    'clear_thread_original_text',
    'get_paragraph_text_for_llm',
    'get_threads_from_session',
    'build_paragraph_cache_from_model',
    'build_paragraph_cache_for_thread',
    'build_thread_target_indices_from_model',
    'convert_placeholders_to_display',
]
