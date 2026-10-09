"""
Threads router - handles thread card display and context operations.

Endpoints:
- GET /thread/{session_id}/{thread_id} - Get thread card HTML
- POST /expand_context/{session_id}/{thread_id} - Expand/contract context
- GET /diff_html/{session_id}/{thread_id} - Get diff HTML
- GET /editable_diff_html/{session_id}/{thread_id} - Get editable diff HTML
- GET /token-count/{session_id}/{thread_id} - Get token count
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional

from src.routes.state import (
    get_session, get_thread_object, save_session, get_templates
)
from src.routes.helpers import (
    get_thread_from_session,
    get_model_from_session,
    get_paragraph_cache,
    get_thread_target_indices,
    parse_table_row,
)
from src.session_utils import convert_placeholders_to_display
from src.context_utils import (
    get_context_paragraphs,
    parse_markdown_table,
    compute_table_diff_cells,
)
from src.diff_utils import (
    compute_diff,
    diff_to_html,
    diff_to_html_paragraph_aware,
    diff_to_editable_html,
)
from src.constants import DEFAULT_INSTRUCTIONS, ThreadStatus
from src import llm_config
from src import token_counter

router = APIRouter()


@router.get("/thread/{session_id}/{thread_id}")
async def get_thread_card(request: Request, session_id: str, thread_id: str):
    """Get a single thread card (for HTMX partial updates)."""
    templates = get_templates()
    session = get_session(session_id)
    
    # Find the thread (works for both DOM and legacy sessions)
    thread = get_thread_from_session(session, thread_id)
    
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    # Get context settings for this thread
    settings = session["context_settings"].get(thread_id, {
        "before_count": 2,
        "after_count": 2,
        "ref_start_offset": 0,
        "ref_end_offset": 0
    })
    
    # Get context paragraphs (pass exact_text for highlighting)
    context_data = get_context_paragraphs(session, thread_id, settings, 
                                          thread.exact_text, thread.exact_text_occurrence)
    
    # Compute diff HTML if there's a suggestion
    suggestion = session["suggestions"].get(thread_id)
    diff_html = None
    editable_diff_html = None  # For unified editor with inline diff
    table_edits_display = None  # For table edits, we show cell changes instead of text diff
    
    if suggestion:
        table_edits = suggestion.get("table_edits")
        
        if table_edits:
            # For table edits, prepare a display of cell changes
            # Get original cell values from the paragraph cache (use current model for table structure)
            paragraph_cache = get_paragraph_cache(session, use_original=False)
            thread_indices = get_thread_target_indices(session, use_original=False)
            
            if thread_id in thread_indices:
                start_idx, _ = thread_indices[thread_id]
                if start_idx < len(paragraph_cache):
                    target_item = paragraph_cache[start_idx]
                    if target_item.get('type') == 'table':
                        # Build table_edits_display with original values for comparison
                        table_edits_display = []
                        table_markdown = target_item.get('table_markdown', '')
                        # Parse original table to get cell values
                        original_cells = parse_markdown_table(table_markdown)
                        
                        for edit in table_edits:
                            row = edit.get('row', 0)
                            col = edit.get('col', 0)
                            revised = edit.get('revised', '')
                            # Get original value if within bounds
                            original = ''
                            if row < len(original_cells) and col < len(original_cells[row]):
                                original = original_cells[row][col]
                            table_edits_display.append({
                                'row': row,
                                'col': col,
                                'original': original,
                                'revised': revised
                            })
        else:
            # Regular text diff - use ORIGINAL document text (not accepted revisions)
            # Compute from original model to get original state before any edits
            original_cache = get_paragraph_cache(session, use_original=True)
            original_thread_indices = get_thread_target_indices(session, use_original=True)
            
            if thread_id in original_thread_indices:
                start_idx, end_idx = original_thread_indices[thread_id]
                # Apply any context expansion from settings
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
                    # Use display_text for UI (has [1] instead of [CITATION_1])
                    original_parts.append(para.get('display_text', para.get('text', '')))
                    # Also get formatted HTML for preserving original formatting
                    original_html_parts.append(para.get('display_formatted_html', para.get('formatted_html', para.get('text', ''))))
                original_text = "\n\n".join(original_parts)
                original_html = "\n\n".join(original_html_parts)
            else:
                original_text = thread.paragraph_text or thread.referenced_text or ""
                original_html = None  # No original HTML available
            
            revised_text = suggestion.get("revised_text", "")
            revised_text_html = suggestion.get("revised_text_html", revised_text)
            
            # Convert [CITATION_X] placeholders back to display text for UI
            # This ensures the UI shows [1] instead of [CITATION_1]
            revised_text_for_display = convert_placeholders_to_display(revised_text, session)
            revised_text_html_for_display = convert_placeholders_to_display(revised_text_html, session)
            
            if original_text and revised_text:
                # Multi-paragraph threads: use positional 1:1 mapping (same as export/accept)
                all_target_para_ids = suggestion.get("all_target_para_ids") or []
                use_positional_mapping = len(all_target_para_ids) > 1
                # Use paragraph-aware diffing for better results when paragraphs are added/removed
                diff_html = diff_to_html_paragraph_aware(
                    original_text, revised_text_for_display,
                    use_positional_mapping=use_positional_mapping
                )
                # Compute editable diff HTML for unified editor
                editable_diff_html = diff_to_editable_html(
                    original_text, revised_text_html_for_display, original_html=original_html,
                    use_positional_mapping=use_positional_mapping
                )
    
    # Get instructions for this thread
    has_custom_instructions = thread_id in session.get("thread_instructions", {})
    thread_instructions = session.get("thread_instructions", {}).get(
        thread_id,
        session.get("default_instructions", DEFAULT_INSTRUCTIONS)
    )
    
    # Check if target is a table row (for styling Revised Text area)
    is_table_row = False
    diff_html_rows = None  # For table rows: list of per-row diff HTML strings
    diff_table_cells = None  # For table rows: 2D list of cell dicts with diff HTML
    if context_data.get('target'):
        # Check for table_row OR table_group types (table rows are grouped for display)
        is_table_row = any(item.get('type') in ('table_row', 'table_group') for item in context_data['target'])
        
        # For table rows, compute diff PER CELL for proper HTML table rendering
        if is_table_row and suggestion and suggestion.get("revised_text"):
            # Get ORIGINAL rows from original model for diff computation
            original_cache = get_paragraph_cache(session, use_original=True)
            original_thread_indices = get_thread_target_indices(session, use_original=True)
            original_cells = []  # List of lists of cell texts
            if thread_id in original_thread_indices:
                start_idx, end_idx = original_thread_indices[thread_id]
                for i in range(start_idx, min(end_idx + 1, len(original_cache))):
                    para = original_cache[i]
                    if para.get('type') == 'table_row':
                        cells = para.get('cells', [])
                        cell_texts = [cell.get('text', '') for cell in cells]
                        original_cells.append(cell_texts)
            
            # Get revised rows (split by newline, filter empty and separator lines)
            revised_text = suggestion.get("revised_text", "")
            revised_lines = [r for r in revised_text.split('\n') if r.strip() and not r.strip().startswith('|---')]
            
            # Parse revised lines into cell lists
            revised_cells = [parse_table_row(line) for line in revised_lines]
            
            # Compute per-cell diffs for HTML table rendering
            diff_table_cells = compute_table_diff_cells(
                original_cells, revised_cells, compute_diff, diff_to_html
            )
            
            # Also compute row-level diffs for backward compatibility (edit mode fallback)
            original_rows = [' | '.join(cells) for cells in original_cells]
            diff_html_rows = []
            for i, orig_row in enumerate(original_rows):
                if i < len(revised_lines):
                    row_diff = compute_diff(orig_row, revised_lines[i])
                    row_html = diff_to_html(row_diff)
                    diff_html_rows.append(row_html)
                else:
                    diff_html_rows.append(f'<span style="text-decoration: line-through; color: #dc3545; background-color: #ffebee;">{orig_row}</span>')
            
            # Handle any extra revised rows (additions)
            for i in range(len(original_rows), len(revised_lines)):
                diff_html_rows.append(f'<span style="color: #28a745; background-color: #e8f5e9;">{revised_lines[i]}</span>')
    
    # Get chat state
    chat_mode_active = session.get("chat_mode_active", {}).get(thread_id, False)
    chat_history = session.get("chat_history", {}).get(thread_id, [])
    chat_completed = session.get("chat_completed", {}).get(thread_id, False)
    
    # Check if this thread has accepted revisions (for export validation)
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
            "editable_diff_html": editable_diff_html,  # For unified editor with inline diff
            "diff_html_rows": diff_html_rows,  # For table rows: list of row HTML strings (fallback)
            "diff_table_cells": diff_table_cells,  # For table rows: 2D list of cell dicts with diff HTML
            "is_table_row": is_table_row,  # For table row styling in Revised Text
            "context_data": context_data,
            "settings": settings,
            "thread_instructions": thread_instructions,
            "has_custom_instructions": has_custom_instructions,
            # Chat mode data
            "chat_mode_active": chat_mode_active,
            "chat_history": chat_history,
            "chat_completed": chat_completed,
            # Attachments
            "attachments": session.get("attachments", {}).get(thread_id, []),
            # Export state
            "has_accepted_revision": has_accepted_revision,
        },
    )


@router.post("/expand_context/{session_id}/{thread_id}")
async def expand_context(
    request: Request, 
    session_id: str, 
    thread_id: str,
    action: str = Form(...),  # before_plus, before_minus, after_plus, after_minus, ref_up_plus, etc.
):
    """Handle context expansion/contraction buttons."""
    session = get_session(session_id)
    # Compute caches on demand from current model
    paragraph_cache = get_paragraph_cache(session, use_original=False)
    thread_indices = get_thread_target_indices(session, use_original=False)
    
    # Initialize settings if not present
    if thread_id not in session["context_settings"]:
        session["context_settings"][thread_id] = {
            "before_count": 2,
            "after_count": 2,
            "ref_start_offset": 0,
            "ref_end_offset": 0
        }
    
    settings = session["context_settings"][thread_id]
    
    # Calculate boundaries
    max_paragraphs = len(paragraph_cache)
    
    # Get current thread position
    thread_start, thread_end = thread_indices.get(thread_id, (0, 0))
    
    # Handle actions
    if action == "before_plus":
        # Add more context before (limited by document start)
        max_before = thread_start + settings.get("ref_start_offset", 0)
        if settings["before_count"] < max_before:
            settings["before_count"] = settings["before_count"] + 1
    elif action == "before_minus":
        settings["before_count"] = max(0, settings["before_count"] - 1)
    elif action == "after_plus":
        # Add more context after (limited by document end)
        effective_end = thread_end + settings.get("ref_end_offset", 0)
        max_after = max_paragraphs - effective_end - 1
        if settings["after_count"] < max_after:
            settings["after_count"] = settings["after_count"] + 1
    elif action == "after_minus":
        settings["after_count"] = max(0, settings["after_count"] - 1)
    # Referenced Text expansion (include preceding/following paragraphs in target)
    elif action == "ref_up_plus":
        # Expand upward (include preceding paragraph as target)
        current_offset = settings.get("ref_start_offset", 0)
        # Can go as far negative as the thread_start allows
        if thread_start + current_offset > 0:
            settings["ref_start_offset"] = current_offset - 1
    elif action == "ref_up_minus":
        # Contract from top (move start back toward original)
        if settings.get("ref_start_offset", 0) < 0:
            settings["ref_start_offset"] = settings.get("ref_start_offset", 0) + 1
    elif action == "ref_down_plus":
        # Expand downward (include following paragraph as target)
        current_offset = settings.get("ref_end_offset", 0)
        effective_end = thread_end + current_offset
        if effective_end < max_paragraphs - 1:
            settings["ref_end_offset"] = current_offset + 1
    elif action == "ref_down_minus":
        settings["ref_end_offset"] = max(settings["ref_end_offset"] - 1, 0)
    
    save_session(session_id)
    
    # Return updated card
    return await get_thread_card(request, session_id, thread_id)


@router.get("/diff_html/{session_id}/{thread_id}")
async def get_diff_html(request: Request, session_id: str, thread_id: str):
    """Get the diff HTML for a thread's revised text (for live diff view updates)."""
    session = get_session(session_id)
    
    suggestion = session["suggestions"].get(thread_id)
    if not suggestion:
        return HTMLResponse("<p class='text-gray-500'>No suggestion</p>")
    
    # Get original text for comparison (use current model for context offsets)
    thread_indices = get_thread_target_indices(session, use_original=False)
    paragraph_cache = get_paragraph_cache(session, use_original=False)
    
    original_text = ""
    original_html = ""
    if thread_id in thread_indices and paragraph_cache:
        start_idx, end_idx = thread_indices[thread_id]
        settings = session["context_settings"].get(thread_id, {
            "ref_start_offset": 0,
            "ref_end_offset": 0
        })
        effective_start = max(0, start_idx + settings.get("ref_start_offset", 0))
        effective_end = min(len(paragraph_cache) - 1, end_idx + settings.get("ref_end_offset", 0))
        
        # Build original text and HTML
        original_parts = []
        original_html_parts = []
        for i in range(effective_start, effective_end + 1):
            para = paragraph_cache[i]
            if para.get('is_ghost', False):
                continue
            # Use display_text for UI (has [1] instead of [CITATION_1])
            text = para.get('display_text', para.get('text', ''))
            html = para.get('display_formatted_html', para.get('formatted_html', '')) or text
            original_parts.append(text)
            original_html_parts.append(html)
        original_text = '\n\n'.join(original_parts)
        original_html = '\n\n'.join(original_html_parts)
    
    # Get revised text (plain and HTML)
    revised_text = suggestion.get('revised_text', '')
    revised_html = suggestion.get('revised_text_html', '')
    
    # Convert [CITATION_X] placeholders back to display text for UI
    revised_text_for_display = convert_placeholders_to_display(revised_text, session)
    
    # Compute diff using plain text
    diff = compute_diff(original_text, revised_text_for_display)
    
    # If no user-added formatting and source has formatting, use formatted diff
    # For now, show plain text diff with source formatting note
    result_diff_html = diff_to_html(diff)
    
    return HTMLResponse(result_diff_html)


@router.get("/editable_diff_html/{session_id}/{thread_id}")
async def get_editable_diff_html(request: Request, session_id: str, thread_id: str):
    """Get the editable diff HTML for unified editor (includes formatting + diff highlights)."""
    session = get_session(session_id)
    
    suggestion = session["suggestions"].get(thread_id)
    if not suggestion:
        return HTMLResponse("<p class='text-gray-500'>No suggestion</p>")
    
    # Get original text for comparison (use original model for diff accuracy)
    original_thread_indices = get_thread_target_indices(session, use_original=True)
    original_cache = get_paragraph_cache(session, use_original=True)
    
    original_text = ""
    original_html = None
    if thread_id in original_thread_indices and original_cache:
        start_idx, end_idx = original_thread_indices[thread_id]
        settings = session["context_settings"].get(thread_id, {
            "ref_start_offset": 0,
            "ref_end_offset": 0
        })
        effective_start = max(0, start_idx + settings.get("ref_start_offset", 0))
        effective_end = min(len(original_cache) - 1, end_idx + settings.get("ref_end_offset", 0))
        
        # Build original text (plain) and original HTML (formatted) for diffing
        original_parts = []
        original_html_parts = []
        for i in range(effective_start, effective_end + 1):
            para = original_cache[i]
            if para.get('is_ghost', False):
                continue
            # Use display_text for UI (has [1] instead of [CITATION_1])
            original_parts.append(para.get('display_text', para.get('text', '')))
            original_html_parts.append(para.get('display_formatted_html', para.get('formatted_html', para.get('text', ''))))
        original_text = '\n\n'.join(original_parts)
        original_html = '\n\n'.join(original_html_parts)
    
    # Get revised HTML (source of truth) and convert placeholders to display text
    revised_text = suggestion.get('revised_text', '')
    revised_html = suggestion.get('revised_text_html', revised_text)
    revised_html = convert_placeholders_to_display(revised_html, session)
    
    # Multi-paragraph threads: use positional 1:1 mapping (same as export/accept)
    all_target_para_ids = suggestion.get("all_target_para_ids") or []
    use_positional_mapping = len(all_target_para_ids) > 1
    # Compute editable diff HTML with original formatting preserved
    editable_html = diff_to_editable_html(
        original_text, revised_html, original_html=original_html,
        use_positional_mapping=use_positional_mapping
    )
    return HTMLResponse(editable_html)


@router.get("/token-count/{session_id}/{thread_id}")
async def get_token_count(
    session_id: str, 
    thread_id: str,
    provider: str = "openai",
    model: Optional[str] = None,
    format: str = "html"  # "html" for HTMX, "json" for API
):
    """
    Get token count for a thread's prompt.
    
    This calculates the approximate token count for the prompt that would be
    sent to the LLM when generating a suggestion for this thread.
    
    Args:
        format: "html" returns styled HTML snippet for HTMX, "json" returns raw data
    
    Returns token count, context window limit, and status.
    """
    session = get_session(session_id)
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        if format == "html":
            return HTMLResponse('<span class="text-red-500 text-xs">Thread not found</span>')
        return JSONResponse({"error": "Thread not found"}, status_code=404)
    
    # Get context settings for this thread
    settings = session["context_settings"].get(thread_id, {
        "before_count": 2,
        "after_count": 2,
        "ref_start_offset": 0,
        "ref_end_offset": 0
    })
    
    # Get custom instructions
    custom_instructions = session["thread_instructions"].get(
        thread_id,
        session.get("default_instructions", DEFAULT_INSTRUCTIONS)
    )
    
    # Build an approximate prompt to count tokens
    # This mirrors what LLMHandler does, but simplified
    prompt_parts = []
    
    # System instructions
    prompt_parts.append(custom_instructions)
    
    # Thread info
    prompt_parts.append(f"Comment: {' | '.join(c.text for c in thread.comments)}")
    prompt_parts.append(f"Author: {thread.comments[0].author}")
    prompt_parts.append(f"Referenced Text: {thread.referenced_text}")
    
    # Context from paragraph cache (computed on demand from current model)
    paragraph_cache = get_paragraph_cache(session, use_original=False)
    thread_indices = get_thread_target_indices(session, use_original=False)
    
    if thread_id in thread_indices and paragraph_cache:
        start_idx, end_idx = thread_indices[thread_id]
        
        # Apply offsets
        effective_start = max(0, start_idx + settings.get("ref_start_offset", 0))
        effective_end = min(len(paragraph_cache) - 1, end_idx + settings.get("ref_end_offset", 0))
        
        # Get context counts
        before_count = settings.get("before_count", 2)
        after_count = settings.get("after_count", 2)
        
        # Add preceding context - collect N non-ghost paragraphs going backwards
        before_texts = []
        i = effective_start - 1
        while i >= 0 and len(before_texts) < before_count:
            para = paragraph_cache[i]
            if not para.get('is_ghost', False):
                before_texts.append(para.get('text', ''))
            i -= 1
        for text in reversed(before_texts):
            prompt_parts.append(f"[Context - Preceding]: {text}")
        
        # Add target text (with any accepted revisions)
        for i in range(effective_start, effective_end + 1):
            para = paragraph_cache[i]
            para_id = para.get('para_id', '')
            text = session.get("accepted_revisions", {}).get(para_id, para.get('text', ''))
            prompt_parts.append(f"[Target]: {text}")
        
        # Add following context - collect N non-ghost paragraphs going forwards
        after_collected = 0
        i = effective_end + 1
        while i < len(paragraph_cache) and after_collected < after_count:
            para = paragraph_cache[i]
            if not para.get('is_ghost', False):
                prompt_parts.append(f"[Context - Following]: {para.get('text', '')}")
                after_collected += 1
            i += 1
    
    # Add attachment content
    attachments = session.get("attachments", {}).get(thread_id, [])
    for attachment in attachments:
        if "parsed_content" in attachment:
            prompt_parts.append(f"[Attachment - {attachment['filename']}]:\n{attachment['parsed_content']}")
    
    # Combine into approximate prompt
    full_prompt = "\n\n".join(prompt_parts)
    
    # Get default model if not specified
    if not model:
        model = llm_config.get_default_model(provider)
    
    # Count tokens and check limit
    result = token_counter.check_token_limit(full_prompt, provider, model)
    
    # Add formatted display
    result["display"] = token_counter.format_token_display(
        result["token_count"], 
        result["context_window"]
    )
    
    # Add cost estimate (for paid models)
    estimated_output = 500  # Rough estimate for typical response
    result["estimated_cost"] = token_counter.estimate_cost(
        result["token_count"], 
        estimated_output, 
        provider, 
        model
    )
    
    # Return HTML for HTMX or JSON for API
    if format == "html":
        # Determine color based on status
        if result["status"] == "error":
            color_class = "text-red-600"
            icon = "⚠️"
        elif result["status"] == "warning":
            color_class = "text-yellow-600"
            icon = "⚠️"
        else:
            color_class = "text-gray-500"
            icon = "📊"
        
        # Format token count nicely
        token_k = result["token_count"] / 1000
        context_k = result["context_window"] / 1000
        
        if token_k >= 1:
            display = f"{token_k:.1f}K / {context_k:.0f}K"
        else:
            display = f"{result['token_count']:,} / {context_k:.0f}K"
        
        html = f'<span class="{color_class}">{icon} {display}</span>'
        return HTMLResponse(html)
    
    return JSONResponse(result)
