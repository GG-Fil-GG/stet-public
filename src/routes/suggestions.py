"""
Suggestions router - handles suggestion generation, acceptance, and updates.

Endpoints:
- POST /generate/{session_id}/{thread_id} - Generate LLM suggestion
- POST /accept/{session_id}/{thread_id} - Accept and apply suggestion
- POST /skip/{session_id}/{thread_id} - Skip thread
- POST /regenerate/{session_id}/{thread_id} - Regenerate suggestion
- POST /update_suggestion/{session_id}/{thread_id} - Update suggestion text
"""

import html as html_module
import re
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional
from datetime import datetime


def format_llm_error(error: Exception) -> str:
    """
    Format LLM API errors into user-friendly messages.
    
    Handles common OpenAI/API errors and returns clean, actionable messages.
    """
    error_str = str(error)
    
    # Check for quota/billing errors (429 with insufficient_quota)
    if "insufficient_quota" in error_str or "exceeded your current quota" in error_str.lower():
        return "OpenAI API quota exceeded. Please check your billing details at platform.openai.com"
    
    # Check for rate limiting (429 without quota issue)
    if "429" in error_str and "rate" in error_str.lower():
        return "Rate limit exceeded. Please wait a moment and try again."
    
    # Check for invalid API key
    if "invalid_api_key" in error_str or "Incorrect API key" in error_str:
        return "Invalid OpenAI API key. Please check your API key in Settings."
    
    # Check for authentication errors
    if "401" in error_str or "authentication" in error_str.lower():
        return "API authentication failed. Please check your API key in Settings."
    
    # Check for model not found
    if "model_not_found" in error_str or "does not exist" in error_str:
        return "The selected model is not available. Please choose a different model in Settings."
    
    # Check for context length exceeded
    if "context_length" in error_str or "maximum context" in error_str.lower():
        return "The document content is too long for this model. Try a model with larger context window."
    
    # Check for timeout
    if "timeout" in error_str.lower() or "timed out" in error_str.lower():
        return "Request timed out. The server may be busy - please try again."
    
    # Check for connection errors
    if "connection" in error_str.lower() and ("refused" in error_str.lower() or "error" in error_str.lower()):
        return "Could not connect to the API. Please check your internet connection."
    
    # For Ollama-specific errors
    if "ollama" in error_str.lower():
        if "connection refused" in error_str.lower():
            return "Could not connect to Ollama. Make sure Ollama is running (ollama serve)."
        if "model" in error_str.lower() and "not found" in error_str.lower():
            return "Ollama model not found. Run 'ollama pull <model>' to download it."
    
    # Generic fallback - try to extract just the message part
    # Look for 'message': '...' pattern in the error
    message_match = re.search(r"'message':\s*'([^']+)'", error_str)
    if message_match:
        return message_match.group(1)
    
    # If nothing else, return a cleaned-up version (limit length)
    clean_error = error_str[:200]
    if len(error_str) > 200:
        clean_error += "..."
    return f"LLM error: {clean_error}"

from src.routes.state import (
    sessions, get_session, save_session, get_templates
)
from src.constants import DEFAULT_INSTRUCTIONS, ThreadStatus
from src.paths import get_sessions_dir

OUTPUT_DIR = get_sessions_dir()
from src.routes.helpers import (
    get_model_from_session,
    get_paragraph_cache,
    get_thread_target_indices,
    build_paragraph_cache_for_thread,
    build_thread_target_indices_from_model,
    convert_dom_thread_for_llm,
    store_thread_original_text,
    get_text_excluding_thread,
    find_threads_sharing_paragraphs,
    find_threads_with_context_overlap,
    parse_table_row,
)
from src.llm_handler import LLMHandler
from src.document_model import DocumentEdit, EditType, Run
from src.document_model.plain_text import apply_revision_from_plain_text
from src.diff_utils import strip_html_tags, merge_formatting_for_revision
from src.session_utils import convert_placeholders_to_display
from src.output_manager import save_llm_suggestion

router = APIRouter()


def _verify_session_token() -> bool:
    """Verify the build token is valid (placeholder for future implementation)."""
    return True


@router.post("/generate/{session_id}/{thread_id}")
async def generate_suggestion(
    request: Request, 
    session_id: str, 
    thread_id: str,
    provider: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    ollama_url: Optional[str] = Form(None)
):
    """Generate an LLM suggestion for a thread."""
    # Import here to avoid circular import
    from src.routes.threads import get_thread_card
    
    # Verify build validity
    if not _verify_session_token():
        raise HTTPException(status_code=403, detail="Session expired. Please update to the latest version.")
    
    session = get_session(session_id)
    
    # Get thread from DOM model
    dom_model = get_model_from_session(session)
    dom_thread = dom_model.comments.get_thread(thread_id)
    if not dom_thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    # Convert to LLM-compatible format
    thread = convert_dom_thread_for_llm(dom_thread, dom_model)
    # Build thread-aware paragraph cache for LLM context
    # This excludes the current thread's own prior changes, so regenerating
    # for Thread A shows the paragraph as it was before Thread A modified it
    paragraph_cache = build_paragraph_cache_for_thread(session, thread_id)
    thread_target_indices = build_thread_target_indices_from_model(dom_model)
    # DOM model tracks revisions directly (no virtual state needed)
    accepted_revisions = {}
    
    try:
        # Get context settings
        settings = session["context_settings"].get(thread_id, {
            "before_count": 2,
            "after_count": 2,
            "ref_start_offset": 0,
            "ref_end_offset": 0,
        })
        
        # Use provider/model from form or defaults
        llm_provider = provider or "openai"
        llm_model = model or None  # Let LLMHandler use its default
        
        # Get custom instructions (thread-specific or session default)
        custom_instructions = session["thread_instructions"].get(
            thread_id, 
            session.get("default_instructions", DEFAULT_INSTRUCTIONS)
        )
        
        # Create LLM handler with API credentials from frontend
        handler = LLMHandler(
            provider=llm_provider,
            model=llm_model,
            docx_path=session["filepath"],
            api_key=api_key,
            ollama_url=ollama_url
        )
        
        # Generate suggestion with expanded referenced text if applicable
        # Pass paragraph_cache so tables are handled correctly
        # Pass attachments for context
        attachments = session.get("attachments", {}).get(thread_id, [])
        suggestion = handler.generate_suggestion(
            thread=thread,
            accepted_revisions=accepted_revisions,
            context_before_count=settings.get("before_count", 2),
            context_after_count=settings.get("after_count", 2),
            ref_start_offset=settings.get("ref_start_offset", 0),
            ref_end_offset=settings.get("ref_end_offset", 0),
            custom_instructions=custom_instructions,
            paragraph_cache=paragraph_cache,
            thread_target_indices=thread_target_indices,
            attachments=attachments
        )
        
        # Store the suggestion
        session["suggestions"][thread_id] = suggestion.to_dict()
        
        # Create merged HTML (original formatting + LLM text) for proper display.
        # If merge fails (e.g. original_html contains "<" and confuses the parser),
        # fall back to plain escaped HTML so the suggestion is still saved and shown.
        original_cache = get_paragraph_cache(session, use_original=True)
        original_thread_indices = get_thread_target_indices(session, use_original=True)

        merged_ok = False
        if thread_id in original_thread_indices and original_cache:
            start_idx, end_idx = original_thread_indices[thread_id]
            original_texts = []
            original_htmls = []
            for i in range(start_idx, min(end_idx + 1, len(original_cache))):
                para = original_cache[i]
                original_texts.append(para.get("display_text", para.get("text", "")))
                original_htmls.append(para.get("display_formatted_html", para.get("formatted_html", para.get("text", ""))))

            original_text = "\n\n".join(original_texts) if len(original_texts) > 1 else (original_texts[0] if original_texts else "")
            original_html = "\n\n".join(original_htmls) if len(original_htmls) > 1 else (original_htmls[0] if original_htmls else "")

            revised_text_for_merge = convert_placeholders_to_display(suggestion.revised_text, session)

            try:
                merged_html = merge_formatting_for_revision(
                    original_text=original_text,
                    original_html=original_html,
                    revised_text=revised_text_for_merge,
                    revised_html=""
                )
                session["suggestions"][thread_id]["revised_text_html"] = merged_html
                merged_ok = True
            except Exception:
                pass  # Fall back to plain escaped HTML below

        if not merged_ok:
            # Fallback when merge failed (e.g. "<" in original content): safe HTML from revised_text only
            plain = convert_placeholders_to_display(suggestion.revised_text, session)
            parts = [html_module.escape(p).replace("\n", "<br>") for p in plain.split("\n\n")]
            session["suggestions"][thread_id]["revised_text_html"] = "<p>" + "</p><p>".join(parts) + "</p>"

        # Save to disk for persistence
        save_llm_suggestion(
            session["filepath"],
            thread_id,
            session["suggestions"][thread_id],  # Use updated dict with revised_text_html
            str(OUTPUT_DIR)
        )
        
        # Return updated card
        return await get_thread_card(request, session_id, thread_id)
        
    except Exception as e:
        # Log the full traceback for debugging. Use safe encoding so we never
        # raise UnicodeEncodeError (e.g. charmap on Windows when error text contains < or ≥).
        import traceback
        try:
            print(f"[ERROR] Generate suggestion failed: {e}", flush=True)
            traceback.print_exc()
        except UnicodeEncodeError:
            safe_msg = str(e).encode("ascii", errors="replace").decode("ascii")
            print(f"[ERROR] Generate suggestion failed: {safe_msg}", flush=True)
            tb_str = traceback.format_exc()
            print(tb_str.encode("ascii", errors="replace").decode("ascii"), flush=True)

        # Format the error into a user-friendly message
        user_friendly_error = format_llm_error(e)
        
        # Return error in the card
        return get_templates().TemplateResponse(
            request,
            "partials/error.html",
            {"error": user_friendly_error},
            status_code=500,
        )


@router.post("/accept/{session_id}/{thread_id}")
async def accept_suggestion(request: Request, session_id: str, thread_id: str):
    """Accept a suggestion and apply it to the document.
    
    For DOM sessions: Applies the edit directly to the DocumentModel.
    For legacy sessions: Stores in accepted_revisions dictionary.
    
    HTML is the source of truth for accepted revisions. When a revision is accepted,
    we store the merged HTML (original formatting + user formatting).
    """
    # Import here to avoid circular import
    from src.routes.threads import get_thread_card
    
    print(f"[ACCEPT] Accepting thread {thread_id}", flush=True)
    session = get_session(session_id)
    
    suggestion = session["suggestions"].get(thread_id)
    if not suggestion:
        raise HTTPException(status_code=400, detail="No suggestion to accept")
    
    all_target_para_ids = suggestion.get("all_target_para_ids")
    revised_text = suggestion.get("revised_text", "")
    revised_text_html = suggestion.get("revised_text_html", "")
    
    # Apply edit directly to DOM model
    dom_model = get_model_from_session(session)
    target_para_id = suggestion.get("target_para_id")
    
    # Check if this is a table row revision (multiple cell para_ids)
    is_table_revision = (
        all_target_para_ids and 
        len(all_target_para_ids) > 1 and 
        '|' in revised_text
    )
    
    # Check if this is a multi-paragraph non-table revision
    is_multi_paragraph = (
        all_target_para_ids and 
        len(all_target_para_ids) > 1 and 
        '|' not in revised_text  # Not a table
    )
    
    if is_table_revision:
        # Handle table row revision - split revised text into cells
        print(f"[ACCEPT] Table row revision for thread {thread_id}", flush=True)
        
        # Parse the revised text to extract cells
        # Filter out empty lines and separator lines (|---|)
        row_lines = [
            line.strip() for line in revised_text.split('\n')
            if line.strip() and '|' in line and 
            not line.replace('|', '').replace('-', '').replace(':', '').strip() == ''
        ]
        
        print(f"[ACCEPT] Found {len(row_lines)} row(s) in revised text", flush=True)
        
        # Parse each row to get cells, then flatten into a single list
        all_revised_cells = []
        for row_line in row_lines:
            row_cells = parse_table_row(row_line)
            all_revised_cells.extend(row_cells)
            print(f"[ACCEPT] Row: {len(row_cells)} cells", flush=True)
        
        print(f"[ACCEPT] Total parsed cells: {len(all_revised_cells)}", flush=True)
        print(f"[ACCEPT] Expected cells (para_ids): {len(all_target_para_ids)}", flush=True)
        
        # Apply edit to each cell
        for i, cell_para_id in enumerate(all_target_para_ids):
            para = dom_model.get_paragraph(cell_para_id)
            if para:
                original_text = para.plain_text
                
                # Store original text for thread-aware context generation
                store_thread_original_text(session, thread_id, cell_para_id, original_text)
                
                # Get revised cell text (or keep original if not enough cells)
                if i < len(all_revised_cells):
                    cell_revised_text = all_revised_cells[i].strip()
                else:
                    print(f"[ACCEPT] WARNING: No revised cell for index {i}, keeping original", flush=True)
                    cell_revised_text = original_text
                
                # Create and apply the edit with thread_id for tracking
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=cell_para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=cell_revised_text,
                    author="Stet",
                    track_change=True,
                    thread_id=thread_id
                )
                dom_model.apply_edit(edit)
                print(f"[ACCEPT] Applied DOM edit for table cell para_id={cell_para_id}", flush=True)
    
    elif is_multi_paragraph:
        # Handle multi-paragraph revision (expanded Referenced Text)
        # IMPORTANT: Preserve original paragraph structure - don't allow merging
        print(f"[ACCEPT] Multi-paragraph revision for thread {thread_id} ({len(all_target_para_ids)} paragraphs)", flush=True)

        # Parse revised text by double newline first (LLM is instructed to use blank line between paragraphs)
        revised_paragraphs = [p.strip() for p in revised_text.split('\n\n') if p.strip()]
        n_expected = len(all_target_para_ids)

        # If we got one block (LLM used single newlines), split by single newline and distribute into N paragraphs
        if len(revised_paragraphs) < n_expected and '\n' in revised_text:
            lines = [ln.strip() for ln in revised_text.split('\n') if ln.strip()]
            if len(lines) >= n_expected:
                indices = [(i * len(lines)) // n_expected for i in range(n_expected + 1)]
                revised_paragraphs = [
                    '\n'.join(lines[indices[i] : indices[i + 1]]) for i in range(n_expected)
                ]
                print(f"[ACCEPT] Fallback: split by single newline into {len(revised_paragraphs)} paragraphs", flush=True)

        print(f"[ACCEPT] Parsed {len(revised_paragraphs)} revised paragraphs", flush=True)

        # Apply edit to each paragraph (preserving original structure)
        for i, para_id in enumerate(all_target_para_ids):
            para = dom_model.get_paragraph(para_id)
            if para:
                original_text = para.plain_text
                
                # Store original text for thread-aware context generation
                store_thread_original_text(session, thread_id, para_id, original_text)
                
                # Get revised paragraph text (or keep original if not enough revised paragraphs)
                if i < len(revised_paragraphs):
                    para_revised_text = revised_paragraphs[i].strip()
                else:
                    print(f"[ACCEPT] WARNING: No revised paragraph for index {i}, keeping original", flush=True)
                    para_revised_text = original_text
                
                # Create and apply the edit with thread_id for tracking
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=para_revised_text,
                    author="Stet",
                    track_change=True,
                    thread_id=thread_id
                )
                dom_model.apply_edit(edit)
                print(f"[ACCEPT] Applied DOM edit for para_id={para_id} (para {i+1}/{len(all_target_para_ids)})", flush=True)
    
    elif target_para_id:
        # Regular single paragraph revision
        para = dom_model.get_paragraph(target_para_id)
        if para:
            # Check if this is a re-accept (we have stored original text from a previous accept)
            stored_original = get_text_excluding_thread(session, target_para_id, thread_id)
            is_reaccept = stored_original is not None
            
            if is_reaccept:
                print(f"[ACCEPT] Re-accepting thread {thread_id} - using stored original text", flush=True)
                original_text = stored_original
                
                # Clean up any paragraphs created by the previous accept for this thread
                inserted_para_ids = session.get("thread_inserted_paragraphs", {}).get(thread_id, [])
                if inserted_para_ids:
                    print(f"[ACCEPT] Removing {len(inserted_para_ids)} paragraphs from previous accept", flush=True)
                    for inserted_para_id in inserted_para_ids:
                        # Remove the paragraph from the DOM
                        if dom_model.get_paragraph(inserted_para_id):
                            dom_model.body.remove_element(inserted_para_id)
                            print(f"[ACCEPT] Removed previously-inserted paragraph {inserted_para_id}", flush=True)
                    # Clear the tracking list
                    session["thread_inserted_paragraphs"][thread_id] = []
                
                # Restore original content to the target paragraph
                # This ensures structural edit comparison works correctly
                current_text = para.plain_text
                if current_text != original_text:
                    print(f"[ACCEPT] Restoring paragraph to original state before applying new revision", flush=True)
                    # Clear existing runs and create new one with original text
                    para.runs = [Run(text=original_text)]
            else:
                # First accept - store original text for future re-accepts
                original_text = para.plain_text
                suggestion["original_text"] = original_text
                
                # Store original text for thread-aware context generation
                store_thread_original_text(session, thread_id, target_para_id, original_text)
            
            # Strip HTML to get plain text for the edit (preserves paragraph breaks)
            plain_revised = strip_html_tags(revised_text_html) if revised_text_html else revised_text
            
            # Check if user added paragraph breaks (splitting a single paragraph)
            if '\n\n' in plain_revised:
                # User has added paragraph breaks - use apply_revision_from_plain_text
                # to properly handle structural changes (paragraph splitting)
                print(f"[ACCEPT] Detected paragraph breaks in single paragraph revision - using structural change handler", flush=True)
                
                edits = apply_revision_from_plain_text(
                    model=dom_model,
                    para_ids=[target_para_id],
                    revised_text=plain_revised,
                    author="Stet",
                    track_changes=True,
                    thread_id=thread_id,
                    original_texts=[original_text]  # Use explicit original for correct alignment
                )
                print(f"[ACCEPT] Applied {len(edits)} structural edits for para_id={target_para_id}", flush=True)
                
                # Track any newly inserted paragraphs for potential re-accept cleanup
                if "thread_inserted_paragraphs" not in session:
                    session["thread_inserted_paragraphs"] = {}
                session["thread_inserted_paragraphs"][thread_id] = [
                    edit.new_para_id for edit in edits 
                    if edit.edit_type == EditType.INSERT_PARAGRAPH and edit.new_para_id
                ]
            else:
                # No structural changes - use simple REPLACE (more efficient)
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=target_para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=plain_revised,
                    author="Stet",
                    track_change=True,
                    thread_id=thread_id
                )
                dom_model.apply_edit(edit)
                print(f"[ACCEPT] Applied DOM edit for para_id={target_para_id}", flush=True)
                
                # Clear any previously tracked inserted paragraphs (no longer needed)
                if "thread_inserted_paragraphs" in session and thread_id in session["thread_inserted_paragraphs"]:
                    session["thread_inserted_paragraphs"][thread_id] = []
    
    # Mark thread as accepted
    session["thread_status"][thread_id] = ThreadStatus.ACCEPTED
    suggestion["accepted_at"] = datetime.now().isoformat()
    
    # Clear chat state
    if thread_id in session.get("chat_mode_active", {}):
        session["chat_mode_active"][thread_id] = False
    if thread_id in session.get("chat_history", {}):
        session["chat_history"][thread_id] = []
    if thread_id in session.get("chat_completed", {}):
        session["chat_completed"][thread_id] = True
    
    # Save session state
    save_session(session_id)
    
    # Collect all affected paragraph IDs
    affected_para_ids = set()
    if all_target_para_ids:
        affected_para_ids.update(all_target_para_ids)
    if target_para_id:
        affected_para_ids.add(target_para_id)
    
    # Store revised HTML in accepted_revisions so other threads can display formatting
    # This is the source of truth for formatted revisions that other threads see in context
    revised_html = suggestion.get("revised_text_html", "")
    if revised_html:
        # Ensure accepted_revisions dict exists (defensive - for older sessions)
        if "accepted_revisions" not in session:
            session["accepted_revisions"] = {}
        if all_target_para_ids and len(all_target_para_ids) > 1:
            # Multi-paragraph: split HTML by <br> (paragraph separator) and assign to each para_id
            # Note: paragraphs are separated by single <br> after our diff_utils fix
            html_parts = revised_html.split('<br>')
            for i, para_id in enumerate(all_target_para_ids):
                if i < len(html_parts):
                    session["accepted_revisions"][para_id] = html_parts[i].strip()
                    print(f"[ACCEPT] Stored accepted_revision for para_id={para_id}", flush=True)
        elif target_para_id:
            session["accepted_revisions"][target_para_id] = revised_html
            print(f"[ACCEPT] Stored accepted_revision for para_id={target_para_id}", flush=True)
    
    # Find other threads that share these paragraphs
    # Caches are computed on demand by find_threads_* functions
    
    # Find threads sharing TARGET paragraphs
    threads_sharing_target = find_threads_sharing_paragraphs(session, affected_para_ids, exclude_thread_id=thread_id)
    print(f"[ACCEPT] Threads sharing TARGET paragraphs: {threads_sharing_target}", flush=True)
    
    # Also find threads with affected paragraphs in their CONTEXT (before/after)
    threads_with_context_overlap = find_threads_with_context_overlap(session, affected_para_ids, exclude_thread_id=thread_id)
    print(f"[ACCEPT] Threads with CONTEXT overlap: {threads_with_context_overlap}", flush=True)
    
    # Combine both lists (unique threads)
    affected_threads = list(set(threads_sharing_target + threads_with_context_overlap))
    print(f"[ACCEPT] All affected threads: {affected_threads}", flush=True)
    
    # Get the accepted thread's card HTML (the primary response)
    primary_card_response = await get_thread_card(request, session_id, thread_id)
    primary_html = primary_card_response.body.decode('utf-8')
    
    # If no other threads affected, just return the primary card
    if not affected_threads:
        return primary_card_response
    
    # Generate OOB swap HTML for affected threads
    oob_html_parts = []
    for affected_thread_id in affected_threads:
        # Get the card HTML for the affected thread
        affected_card_response = await get_thread_card(request, session_id, affected_thread_id)
        affected_html = affected_card_response.body.decode('utf-8')
        
        # Wrap with hx-swap-oob attribute
        # The card template has id="card-{thread_id}", we need to add hx-swap-oob="true"
        # Replace the opening div to add the oob attribute
        oob_html = affected_html.replace(
            f'id="card-{affected_thread_id}"',
            f'id="card-{affected_thread_id}" hx-swap-oob="true"',
            1  # Only replace the first occurrence
        )
        oob_html_parts.append(oob_html)
        print(f"[ACCEPT] Adding OOB swap for thread {affected_thread_id}", flush=True)
    
    # Combine primary card + OOB swaps
    combined_html = primary_html + "\n".join(oob_html_parts)
    
    return HTMLResponse(content=combined_html)


@router.post("/skip/{session_id}/{thread_id}")
async def skip_thread(request: Request, session_id: str, thread_id: str):
    """Skip a thread."""
    # Import here to avoid circular import
    from src.routes.threads import get_thread_card
    
    session = get_session(session_id)
    
    # Mark thread as skipped
    session["thread_status"][thread_id] = ThreadStatus.SKIPPED
    
    # Save session for persistence
    save_session(session_id)
    
    # Return updated card
    return await get_thread_card(request, session_id, thread_id)


@router.post("/regenerate/{session_id}/{thread_id}")
async def regenerate_suggestion(
    request: Request, 
    session_id: str, 
    thread_id: str,
    provider: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    ollama_url: Optional[str] = Form(None)
):
    """Regenerate a suggestion for a thread."""
    session = get_session(session_id)
    
    # Get the old suggestion to find the target_para_id(s)
    old_suggestion = session["suggestions"].get(thread_id)
    
    # Clear the revision from accepted_revisions if it was accepted
    # This ensures the LLM gets the ORIGINAL text, not the previously accepted revision
    if old_suggestion:
        # Clear all target para_ids (for multi-paragraph revisions)
        all_target_para_ids = old_suggestion.get("all_target_para_ids")
        if all_target_para_ids:
            for para_id in all_target_para_ids:
                if para_id in session.get("accepted_revisions", {}):
                    del session["accepted_revisions"][para_id]
                    print(f"[REGENERATE] Cleared revision for para_id={para_id}", flush=True)
        else:
            # Fallback to single target_para_id
            target_para_id = old_suggestion.get("target_para_id")
            if target_para_id and target_para_id in session.get("accepted_revisions", {}):
                del session["accepted_revisions"][target_para_id]
    
    # ALSO: Clear any revisions for paragraphs in the CURRENT expanded range
    # (context settings may have changed, so we need to clear based on current range)
    settings = session["context_settings"].get(thread_id, {
        "before_count": 2,
        "after_count": 2,
        "ref_start_offset": 0,
        "ref_end_offset": 0
    })
    # Compute caches on demand from current model
    thread_indices = get_thread_target_indices(session, use_original=False)
    paragraph_cache = get_paragraph_cache(session, use_original=False)
    
    if thread_id in thread_indices and paragraph_cache:
        start_idx, end_idx = thread_indices[thread_id]
        # Calculate the expanded target range based on current settings
        effective_start = max(0, start_idx + settings.get("ref_start_offset", 0))
        effective_end = min(len(paragraph_cache) - 1, end_idx + settings.get("ref_end_offset", 0))
        
        # Clear revisions for ALL paragraphs in the expanded range
        for i in range(effective_start, effective_end + 1):
            if i < len(paragraph_cache):
                para_id = paragraph_cache[i].get("para_id")
                if para_id and para_id in session.get("accepted_revisions", {}):
                    del session["accepted_revisions"][para_id]
                    print(f"[REGENERATE] Cleared revision for expanded range para_id={para_id}", flush=True)
    
    # Clear existing suggestion
    if thread_id in session["suggestions"]:
        del session["suggestions"][thread_id]
    
    # Clear chat state for a fresh start
    session["chat_history"].pop(thread_id, None)
    session["chat_mode_active"].pop(thread_id, None)
    session["chat_snapshots"].pop(thread_id, None)
    session["chat_completed"].pop(thread_id, None)
    
    # Reset status to pending if it was accepted/skipped
    session["thread_status"][thread_id] = ThreadStatus.PENDING
    
    # Save session to persist the cleared revision
    save_session(session_id)
    
    # Generate new suggestion with provider/model and API credentials
    return await generate_suggestion(request, session_id, thread_id, provider, model, api_key, ollama_url)


@router.post("/update_suggestion/{session_id}/{thread_id}")
async def update_suggestion(
    request: Request, 
    session_id: str, 
    thread_id: str,
    revised_text: Optional[str] = Form(None),
    revised_text_html: Optional[str] = Form(None),
    response: Optional[str] = Form(None),
    reset_acceptance: Optional[str] = Form(None)
):
    """Update suggestion text (auto-save from editable fields).
    
    HTML is the source of truth for revised text. When revised_text_html is provided,
    revised_text is derived from it by stripping HTML tags.
    """
    session = get_session(session_id)
    
    suggestion = session["suggestions"].get(thread_id)
    if not suggestion:
        return JSONResponse({"status": "error", "message": "No suggestion found"}, status_code=404)
    
    # HTML is the source of truth for revised text
    # When HTML is provided, derive plain text from it
    if revised_text_html is not None:
        suggestion["revised_text_html"] = revised_text_html
        # Derive plain text from HTML (source of truth)
        suggestion["revised_text"] = strip_html_tags(revised_text_html)
    elif revised_text is not None:
        # Fallback: if only plain text provided (e.g., from older clients)
        suggestion["revised_text"] = revised_text
        # Don't overwrite HTML if only plain text provided
    
    if response is not None:
        suggestion["response"] = response
    
    # If user edits an accepted suggestion, reset to PENDING - they must re-accept
    # BUT keep the accepted_revisions entry so the previously accepted version can still be exported
    acceptance_was_reset = False
    if reset_acceptance == 'true':
        current_status = session["thread_status"].get(thread_id)
        if current_status == ThreadStatus.ACCEPTED:
            session["thread_status"][thread_id] = ThreadStatus.PENDING
            suggestion.pop("accepted_at", None)
            acceptance_was_reset = True
            # NOTE: We intentionally keep accepted_revisions[para_id] intact
            # This allows exporting the previously accepted version even after edits
            # The user can re-accept to update the accepted revision to the new edit
            print(f"[UPDATE] Reset thread {thread_id} to PENDING (user edited after accepting)", flush=True)
            print(f"[UPDATE] Keeping accepted_revisions for export fallback", flush=True)
    
    # Save to disk (both LLM suggestion file and session state)
    save_llm_suggestion(
        session["filepath"],
        thread_id,
        suggestion,
        str(OUTPUT_DIR)
    )
    save_session(session_id)  # Persist to session.json for export
    
    # If acceptance was reset, trigger a card refresh so the UI shows the new status
    if acceptance_was_reset:
        return JSONResponse(
            {"status": "ok", "message": "Saved", "acceptance_reset": True},
            headers={"HX-Trigger": f"acceptanceReset-{thread_id}"}
        )
    
    return JSONResponse({"status": "ok", "message": "Saved"})
