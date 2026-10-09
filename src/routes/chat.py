"""
Chat routes for the Stet application.

Handles chat mode interactions for refining suggestions.
"""

from fastapi import APIRouter, Request, HTTPException, Form
from datetime import datetime
from typing import Optional

from src.llm_handler import LLMHandler
from src.diff_utils import merge_formatting_for_revision, strip_html_tags
from src.chat_types import ChatMessage, ChatSnapshot
from src.document_model import DocumentEdit, EditType
from src.document_model.plain_text import apply_revision_from_plain_text
from src.constants import DEFAULT_INSTRUCTIONS, ThreadStatus
from src.session_utils import (
    get_model_from_session,
    get_paragraph_cache,
    get_thread_target_indices,
    get_text_excluding_thread,
    store_thread_original_text,
    convert_placeholders_to_display,
)
from src.routes.state import get_session, get_thread_object, save_session, get_templates
from src.routes.helpers import get_thread_from_session, render_thread_card


router = APIRouter(tags=["chat"])


@router.post("/enter_chat/{session_id}/{thread_id}")
async def enter_chat(request: Request, session_id: str, thread_id: str):
    """Enter chat mode for a thread."""
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    suggestion = session["suggestions"].get(thread_id)
    if not suggestion:
        raise HTTPException(
            status_code=400, 
            detail="Cannot enter chat mode without a suggestion. Generate a suggestion first."
        )
    
    session["chat_mode_active"][thread_id] = True
    
    if thread_id not in session["chat_snapshots"]:
        session["chat_snapshots"][thread_id] = ChatSnapshot(
            revised_text=suggestion.get("revised_text", ""),
            response=suggestion.get("response", ""),
            rationale=suggestion.get("rationale")
        )
    
    if thread_id not in session["chat_history"]:
        session["chat_history"][thread_id] = [
            ChatMessage.assistant_message(
                "I've generated an initial suggestion based on the reviewer's comment. "
                "Let me know if you'd like any adjustments to the revision or the reply."
            )
        ]
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)


@router.post("/chat/{session_id}/{thread_id}")
async def send_chat_message(
    request: Request, 
    session_id: str, 
    thread_id: str,
    message: str = Form(...),
    provider: str = Form("openai"),
    model: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    ollama_url: Optional[str] = Form(None)
):
    """Send a message in chat mode and get LLM response."""
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    if thread_id not in session["chat_history"]:
        session["chat_history"][thread_id] = []
    
    user_msg = ChatMessage.user_message(message.strip())
    session["chat_history"][thread_id].append(user_msg)
    
    suggestion = session["suggestions"].get(thread_id, {})
    has_suggestion = bool(suggestion)
    current_revision = suggestion.get("revised_text", "")
    current_reply = suggestion.get("response", "")
    
    settings = session["context_settings"].get(thread_id, {
        "before_count": 2,
        "after_count": 2,
        "ref_start_offset": 0,
        "ref_end_offset": 0
    })
    
    custom_instructions = session["thread_instructions"].get(
        thread_id,
        session.get("default_instructions", DEFAULT_INSTRUCTIONS)
    )
    
    try:
        handler = LLMHandler(
            provider=provider,
            model=model,
            docx_path=session["filepath"],
            api_key=api_key,
            ollama_url=ollama_url
        )
        
        attachments = session.get("attachments", {}).get(thread_id, [])
        
        if not has_suggestion:
            print(f"[CHAT] Pre-generation chat for thread {thread_id}", flush=True)
            
            enhanced_instructions = custom_instructions + f"\n\nAdditional user guidance: {message.strip()}"
            
            paragraph_cache = get_paragraph_cache(session, use_original=False)
            thread_target_indices_val = get_thread_target_indices(session, use_original=False)
            suggestion_result = handler.generate_suggestion(
                thread=thread,
                accepted_revisions=session.get("accepted_revisions", {}),
                context_before_count=settings.get("before_count", 2),
                context_after_count=settings.get("after_count", 2),
                ref_start_offset=settings.get("ref_start_offset", 0),
                ref_end_offset=settings.get("ref_end_offset", 0),
                custom_instructions=enhanced_instructions,
                paragraph_cache=paragraph_cache,
                thread_target_indices=thread_target_indices_val,
                attachments=attachments
            )
            
            session["suggestions"][thread_id] = suggestion_result.to_dict()
            session["suggestions"][thread_id]["generated_at"] = datetime.now().isoformat()
            
            original_cache = get_paragraph_cache(session, use_original=True)
            original_thread_indices = get_thread_target_indices(session, use_original=True)
            
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
                
                revised_text_for_merge = convert_placeholders_to_display(suggestion_result.revised_text, session)
                merged_html = merge_formatting_for_revision(
                    original_text=original_text,
                    original_html=original_html,
                    revised_text=revised_text_for_merge,
                    revised_html=""
                )
                session["suggestions"][thread_id]["revised_text_html"] = merged_html
            
            assistant_msg = ChatMessage.assistant_message(
                content="I've generated an initial suggestion incorporating your guidance. Let me know if you'd like any adjustments.",
                revision_updated=True,
                reply_updated=True
            )
            session["chat_history"][thread_id].append(assistant_msg)
            
        else:
            paragraph_cache = get_paragraph_cache(session, use_original=False)
            thread_indices = get_thread_target_indices(session, use_original=False)
            chat_response = handler.generate_chat_response(
                thread=thread,
                chat_history=session["chat_history"][thread_id],
                user_message=message.strip(),
                current_revision=current_revision,
                current_reply=current_reply,
                paragraph_cache=paragraph_cache,
                target_indices=thread_indices.get(thread_id, (0, 0)),
                context_settings=settings,
                accepted_revisions=session.get("accepted_revisions", {}),
                instructions=custom_instructions,
                attachments=attachments
            )
            
            revision_updated = False
            reply_updated = False
            
            if chat_response.get("revised_text"):
                session["suggestions"][thread_id]["revised_text"] = chat_response["revised_text"]
                revision_updated = True
                
                original_cache = get_paragraph_cache(session, use_original=True)
                original_thread_indices = get_thread_target_indices(session, use_original=True)
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
                    
                    revised_text_for_merge = convert_placeholders_to_display(chat_response["revised_text"], session)
                    merged_html = merge_formatting_for_revision(
                        original_text=original_text,
                        original_html=original_html,
                        revised_text=revised_text_for_merge,
                        revised_html=""
                    )
                    session["suggestions"][thread_id]["revised_text_html"] = merged_html
            
            if chat_response.get("response"):
                session["suggestions"][thread_id]["response"] = chat_response["response"]
                reply_updated = True
            
            assistant_msg = ChatMessage.assistant_message(
                content=chat_response.get("chat_response", "I've processed your request."),
                revision_updated=revision_updated,
                reply_updated=reply_updated
            )
            session["chat_history"][thread_id].append(assistant_msg)
            
            if (revision_updated or reply_updated) and session["thread_status"].get(thread_id) == ThreadStatus.ACCEPTED:
                session["thread_status"][thread_id] = ThreadStatus.PENDING
                if "accepted_at" in session["suggestions"].get(thread_id, {}):
                    del session["suggestions"][thread_id]["accepted_at"]
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = ChatMessage.assistant_message(
            f"Sorry, I encountered an error: {str(e)}. Please try again."
        )
        session["chat_history"][thread_id].append(error_msg)
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)


@router.post("/commit_chat/{session_id}/{thread_id}")
async def commit_chat(request: Request, session_id: str, thread_id: str):
    """Commit the current revision from chat and exit chat mode."""
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_from_session(session, thread_id)
    
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    suggestion = session["suggestions"].get(thread_id)
    if not suggestion:
        raise HTTPException(status_code=400, detail="No suggestion to commit")
    
    session["thread_status"][thread_id] = ThreadStatus.ACCEPTED
    suggestion["accepted_at"] = datetime.now().isoformat()
    
    all_target_para_ids = suggestion.get("all_target_para_ids", [])
    target_para_id = suggestion.get("target_para_id")
    revised_text = suggestion.get("revised_text", "")
    revised_text_html = suggestion.get("revised_text_html", "")
    
    dom_model = get_model_from_session(session)
    if target_para_id:
        para = dom_model.get_paragraph(target_para_id)
        if para:
            # Check if this is a re-commit (we have stored original text from a previous accept)
            stored_original = get_text_excluding_thread(session, target_para_id, thread_id)
            is_reaccept = stored_original is not None
            
            if is_reaccept:
                print(f"[COMMIT_CHAT] Re-committing thread {thread_id} - using stored original text", flush=True)
                original_text = stored_original
                
                # Clean up any paragraphs created by the previous accept for this thread
                inserted_para_ids = session.get("thread_inserted_paragraphs", {}).get(thread_id, [])
                if inserted_para_ids:
                    print(f"[COMMIT_CHAT] Removing {len(inserted_para_ids)} paragraphs from previous accept", flush=True)
                    for inserted_para_id in inserted_para_ids:
                        if dom_model.get_paragraph(inserted_para_id):
                            dom_model.body.remove_element(inserted_para_id)
                            print(f"[COMMIT_CHAT] Removed previously-inserted paragraph {inserted_para_id}", flush=True)
                    session["thread_inserted_paragraphs"][thread_id] = []
                
                # Restore original content to the target paragraph
                from src.document_model import Run
                current_text = para.plain_text
                if current_text != original_text:
                    print(f"[COMMIT_CHAT] Restoring paragraph to original state before applying new revision", flush=True)
                    para.runs = [Run(text=original_text)]
            else:
                # First accept - store original text for future re-accepts
                original_text = para.plain_text
                store_thread_original_text(session, thread_id, target_para_id, original_text)
            
            suggestion["original_text"] = original_text
            
            plain_revised = strip_html_tags(revised_text_html) if revised_text_html else revised_text
            
            if '\n\n' in plain_revised:
                print(f"[COMMIT_CHAT] Detected paragraph breaks - using structural change handler", flush=True)
                
                edits = apply_revision_from_plain_text(
                    model=dom_model,
                    para_ids=[target_para_id],
                    revised_text=plain_revised,
                    author="Stet",
                    track_changes=True,
                    thread_id=thread_id,
                    original_texts=[original_text]  # Critical: pass original for correct alignment
                )
                print(f"[COMMIT_CHAT] Applied {len(edits)} structural edits for para_id={target_para_id}", flush=True)
                
                # Track any newly inserted paragraphs for potential re-accept cleanup
                if "thread_inserted_paragraphs" not in session:
                    session["thread_inserted_paragraphs"] = {}
                session["thread_inserted_paragraphs"][thread_id] = [
                    edit.new_para_id for edit in edits 
                    if edit.edit_type == EditType.INSERT_PARAGRAPH and edit.new_para_id
                ]
            else:
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
                print(f"[COMMIT_CHAT] Applied DOM edit for para_id={target_para_id}", flush=True)
                
                # Clear any previously tracked inserted paragraphs
                if "thread_inserted_paragraphs" in session and thread_id in session["thread_inserted_paragraphs"]:
                    session["thread_inserted_paragraphs"][thread_id] = []
    
    session["chat_mode_active"][thread_id] = False
    session["chat_completed"][thread_id] = True
    
    if thread_id in session["chat_snapshots"]:
        del session["chat_snapshots"][thread_id]
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)


@router.post("/discard_chat/{session_id}/{thread_id}")
async def discard_chat(request: Request, session_id: str, thread_id: str):
    """Discard chat changes and revert to the original suggestion."""
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    snapshot = session["chat_snapshots"].get(thread_id)
    if snapshot and thread_id in session["suggestions"]:
        session["suggestions"][thread_id]["revised_text"] = snapshot.revised_text
        session["suggestions"][thread_id]["response"] = snapshot.response
        if snapshot.rationale:
            session["suggestions"][thread_id]["rationale"] = snapshot.rationale
    
    session["chat_mode_active"][thread_id] = False
    session["chat_history"].pop(thread_id, None)
    session["chat_snapshots"].pop(thread_id, None)
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)


@router.post("/exit_chat/{session_id}/{thread_id}")
async def exit_chat(request: Request, session_id: str, thread_id: str):
    """Exit chat mode without committing or discarding."""
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    session["chat_mode_active"][thread_id] = False
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)


@router.post("/clear_chat_history/{session_id}/{thread_id}")
async def clear_chat_history(request: Request, session_id: str, thread_id: str):
    """Clear chat history and start fresh from current state."""
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    suggestion = session["suggestions"].get(thread_id, {})
    
    session["chat_history"][thread_id] = [
        ChatMessage.assistant_message(
            "Chat history cleared. The current revision has been preserved as your starting point. "
            "How would you like me to adjust it?"
        )
    ]
    
    session["chat_snapshots"][thread_id] = ChatSnapshot(
        revised_text=suggestion.get("revised_text", ""),
        response=suggestion.get("response", ""),
        rationale=suggestion.get("rationale")
    )
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)
