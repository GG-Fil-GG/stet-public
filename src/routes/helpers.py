"""
Shared helper functions for route modules.

These functions operate on session data and are used across multiple routers.
"""

from fastapi import Request
from fastapi.responses import HTMLResponse

from src.session_utils import (
    get_model_from_session,
    convert_dom_thread_for_llm,
    get_paragraph_cache,
    get_thread_target_indices,
    convert_placeholders_to_display,
    build_paragraph_cache_for_thread,
    build_thread_target_indices_from_model,
    store_thread_original_text,
    get_text_excluding_thread,
)
from src.context_utils import (
    get_context_paragraphs,
    parse_table_row,
    compute_table_diff_cells,
)
from src.diff_utils import compute_diff, diff_to_html, diff_to_html_paragraph_aware, diff_to_editable_html
from src.constants import DEFAULT_INSTRUCTIONS, ThreadStatus


def get_thread_from_session(session: dict, thread_id: str):
    """
    Get a thread from a session.
    
    Returns an LLM-compatible thread object, or None if not found.
    """
    dom_model = get_model_from_session(session)
    dom_thread = dom_model.comments.get_thread(thread_id)
    if dom_thread:
        return convert_dom_thread_for_llm(dom_thread, dom_model)
    return None


def find_threads_sharing_paragraphs(session: dict, para_ids: set, exclude_thread_id: str = None) -> list:
    """
    Find all thread IDs that target any of the given paragraph IDs.

    Args:
        session: The session dict
        para_ids: Set of paragraph IDs to check
        exclude_thread_id: Thread ID to exclude from results (typically the accepted thread)

    Returns:
        List of thread IDs that share paragraphs with the given set
    """
    thread_indices = get_thread_target_indices(session, use_original=False)
    paragraph_cache = get_paragraph_cache(session, use_original=False)

    sharing_threads = []

    for thread_id, indices in thread_indices.items():
        if exclude_thread_id and thread_id == exclude_thread_id:
            continue

        start_idx, end_idx = indices
        for i in range(start_idx, min(end_idx + 1, len(paragraph_cache))):
            para = paragraph_cache[i]
            para_id = para.get('para_id')
            if para_id and para_id in para_ids:
                sharing_threads.append(thread_id)
                break

    return sharing_threads


def find_threads_with_context_overlap(session: dict, para_ids: set, exclude_thread_id: str = None) -> list:
    """
    Find all thread IDs whose CONTEXT (before/after) includes any of the given paragraph IDs.
    
    This is used to refresh cards when another thread modifies paragraphs that appear
    in this thread's context (before/after) areas, not just the target.

    Args:
        session: The session dict
        para_ids: Set of paragraph IDs to check
        exclude_thread_id: Thread ID to exclude from results

    Returns:
        List of thread IDs that have the given paragraphs in their context
    """
    thread_indices = get_thread_target_indices(session, use_original=False)
    paragraph_cache = get_paragraph_cache(session, use_original=False)
    context_settings_by_thread = session.get("context_settings", {})
    
    para_id_to_idx = {}
    for i, para in enumerate(paragraph_cache):
        pid = para.get('para_id')
        if pid:
            para_id_to_idx[pid] = i
    
    affected_threads = []
    
    for thread_id, (start_idx, end_idx) in thread_indices.items():
        if exclude_thread_id and thread_id == exclude_thread_id:
            continue
        
        thread_settings = context_settings_by_thread.get(thread_id, {})
        before_count = thread_settings.get("before_count", 2)
        after_count = thread_settings.get("after_count", 2)
        
        context_start = max(0, start_idx - before_count - 3)
        context_end = min(len(paragraph_cache) - 1, end_idx + after_count + 3)
        
        for affected_pid in para_ids:
            affected_idx = para_id_to_idx.get(affected_pid)
            if affected_idx is not None:
                if context_start <= affected_idx <= context_end:
                    if not (start_idx <= affected_idx <= end_idx):
                        affected_threads.append(thread_id)
                        break
    
    return affected_threads


async def render_thread_card(
    request: Request, 
    session_id: str, 
    thread_id: str, 
    session: dict, 
    thread,
    templates
) -> HTMLResponse:
    """
    Helper function to render a thread card with all necessary context.
    Used by multiple endpoints to return consistent card HTML.
    """
    settings = session["context_settings"].get(thread_id, {
        "before_count": 2,
        "after_count": 2,
        "ref_start_offset": 0,
        "ref_end_offset": 0
    })
    
    context_data = get_context_paragraphs(session, thread_id, settings, 
                                          thread.exact_text, thread.exact_text_occurrence)
    
    suggestion = session["suggestions"].get(thread_id)
    diff_html = None
    editable_diff_html = None
    diff_html_rows = None
    diff_table_cells = None
    is_table_row = False
    
    if suggestion:
        if context_data.get('target'):
            is_table_row = any(item.get('type') in ('table_row', 'table_group') for item in context_data['target'])
            
            original_cache = get_paragraph_cache(session, use_original=True)
            original_thread_indices = get_thread_target_indices(session, use_original=True)
            
            if is_table_row and suggestion.get("revised_text"):
                original_cells = []
                if thread_id in original_thread_indices:
                    start_idx, end_idx = original_thread_indices[thread_id]
                    for i in range(start_idx, min(end_idx + 1, len(original_cache))):
                        para = original_cache[i]
                        if para.get('type') == 'table_row':
                            cells = para.get('cells', [])
                            cell_texts = [cell.get('text', '') for cell in cells]
                            original_cells.append(cell_texts)
                
                revised_text = suggestion.get("revised_text", "")
                revised_lines = [r for r in revised_text.split('\n') if r.strip() and not r.strip().startswith('|---')]
                
                revised_cells = [parse_table_row(line) for line in revised_lines]
                
                diff_table_cells = compute_table_diff_cells(
                    original_cells, revised_cells, compute_diff, diff_to_html
                )
                
                original_rows = [' | '.join(cells) for cells in original_cells]
                diff_html_rows = []
                for i, orig_row in enumerate(original_rows):
                    if i < len(revised_lines):
                        row_diff = compute_diff(orig_row, revised_lines[i])
                        row_html = diff_to_html(row_diff)
                        diff_html_rows.append(row_html)
                    else:
                        diff_html_rows.append(f'<span style="text-decoration: line-through; color: #dc3545; background-color: #ffebee;">{orig_row}</span>')
                
                for i in range(len(original_rows), len(revised_lines)):
                    diff_html_rows.append(f'<span style="color: #28a745; background-color: #e8f5e9;">{revised_lines[i]}</span>')
            else:
                original_html = None
                if thread_id in original_thread_indices:
                    start_idx, end_idx = original_thread_indices[thread_id]
                    ref_start_offset = settings.get("ref_start_offset", 0)
                    ref_end_offset = settings.get("ref_end_offset", 0)
                    effective_start = max(0, start_idx + ref_start_offset)
                    effective_end = min(len(original_cache) - 1, end_idx + ref_end_offset)
                    
                    original_parts = []
                    original_html_parts = []
                    for i in range(effective_start, effective_end + 1):
                        para = original_cache[i]
                        if para.get('is_ghost', False):
                            continue
                        original_parts.append(para.get('display_text', para.get('text', '')))
                        original_html_parts.append(para.get('display_formatted_html', para.get('formatted_html', para.get('text', ''))))
                    original_text = "\n\n".join(original_parts)
                    original_html = "\n\n".join(original_html_parts)
                else:
                    original_text = thread.paragraph_text or thread.referenced_text or ""
                
                revised_text = suggestion.get("revised_text", "")
                revised_text_html = suggestion.get("revised_text_html", revised_text)
                
                revised_text_for_display = convert_placeholders_to_display(revised_text, session)
                revised_text_html_for_display = convert_placeholders_to_display(revised_text_html, session)
                
                if original_text and revised_text:
                    # Multi-paragraph threads: use positional 1:1 mapping (same as export/accept)
                    all_target_para_ids = suggestion.get("all_target_para_ids") or []
                    use_positional_mapping = len(all_target_para_ids) > 1
                    diff_html = diff_to_html_paragraph_aware(
                        original_text, revised_text_for_display,
                        use_positional_mapping=use_positional_mapping
                    )
                    editable_diff_html = diff_to_editable_html(
                        original_text, revised_text_html_for_display, original_html=original_html,
                        use_positional_mapping=use_positional_mapping
                    )
    
    has_custom_instructions = thread_id in session.get("thread_instructions", {})
    thread_instructions = session.get("thread_instructions", {}).get(
        thread_id,
        session.get("default_instructions", DEFAULT_INSTRUCTIONS)
    )
    
    chat_mode_active = session.get("chat_mode_active", {}).get(thread_id, False)
    chat_history = session.get("chat_history", {}).get(thread_id, [])
    chat_completed = session.get("chat_completed", {}).get(thread_id, False)
    
    attachments = session.get("attachments", {}).get(thread_id, [])
    
    thread_status_val = session["thread_status"].get(thread_id, ThreadStatus.PENDING)
    has_accepted_revision = (
        thread_status_val == ThreadStatus.ACCEPTED or 
        (suggestion and suggestion.get("accepted_at"))
    )
    
    return templates.TemplateResponse(
        request,
        "partials/card.html",
        {
            "session_id": session_id,
            "thread": thread,
            "thread_status": session["thread_status"].get(thread_id, ThreadStatus.PENDING),
            "suggestion": suggestion,
            "diff_html": diff_html,
            "editable_diff_html": editable_diff_html,
            "diff_html_rows": diff_html_rows,
            "diff_table_cells": diff_table_cells,
            "is_table_row": is_table_row,
            "context_data": context_data,
            "settings": settings,
            "thread_instructions": thread_instructions,
            "has_custom_instructions": has_custom_instructions,
            "chat_mode_active": chat_mode_active,
            "chat_history": chat_history,
            "chat_completed": chat_completed,
            "attachments": attachments,
            "has_accepted_revision": has_accepted_revision,
        },
    )
