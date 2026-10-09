"""
Export routes for the Stet application.

Handles document export with replies and tracked changes.
"""

from fastapi import APIRouter, Request, Form
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.document_model import DocumentSerializer
from src.session_utils import get_model_from_session
from src.constants import ThreadStatus
from src.routes.state import get_session


router = APIRouter(tags=["export"])


@router.get("/export/{session_id}")
async def export_get_redirect(session_id: str):
    """Redirect GET requests to export back to home (happens if user refreshes after error)."""
    return RedirectResponse(url="/", status_code=303)


@router.post("/export/{session_id}")
async def export_document(
    request: Request, 
    session_id: str,
    insert_tracked_changes: Optional[str] = Form(None),
    author: str = Form("Stet"),
    native_dialog: Optional[str] = Form(None)
):
    """Export document with replies and optionally tracked changes."""
    do_tracked_changes = insert_tracked_changes == "true"
    use_native_dialog = native_dialog == "true"
    session = get_session(session_id)
    
    dom_model = get_model_from_session(session)
    print(f"[EXPORT] Starting export for session {session_id}", flush=True)
    print(f"[EXPORT] Model has {dom_model.thread_count} threads, {dom_model.revision_count} revisions", flush=True)
    
    accepted_thread_ids = [
        tid for tid, status in session["thread_status"].items()
        if status == ThreadStatus.ACCEPTED
    ]
    
    if not accepted_thread_ids:
        return RedirectResponse(url="/", status_code=303)
    
    print(f"[EXPORT] Accepted threads: {len(accepted_thread_ids)}", flush=True)
    
    formatting_info = {}
    # Track which thread's formatting we're using for each para_id (for conflict resolution)
    formatting_thread_info = {}  # para_id -> (thread_id, accepted_at)
    
    for thread_id in accepted_thread_ids:
        suggestion = session["suggestions"].get(thread_id)
        if not suggestion:
            continue
        
        revised_html = suggestion.get("revised_text_html", "")
        target_para_id = suggestion.get("target_para_id")
        all_target_para_ids = suggestion.get("all_target_para_ids", [])
        accepted_at = suggestion.get("accepted_at", "")
        
        if revised_html:
            if all_target_para_ids and len(all_target_para_ids) > 1:
                pass
            elif target_para_id:
                # Check if another thread already claimed this para_id
                existing = formatting_thread_info.get(target_para_id)
                if existing:
                    existing_thread_id, existing_accepted_at = existing
                    # Use the one that was accepted most recently (latest timestamp wins)
                    if accepted_at > existing_accepted_at:
                        print(f"[EXPORT] Thread {thread_id} (accepted {accepted_at}) overwrites thread {existing_thread_id} (accepted {existing_accepted_at}) for para_id={target_para_id}", flush=True)
                        formatting_info[target_para_id] = revised_html
                        formatting_thread_info[target_para_id] = (thread_id, accepted_at)
                    else:
                        print(f"[EXPORT] Thread {thread_id} (accepted {accepted_at}) SKIPPED - thread {existing_thread_id} (accepted {existing_accepted_at}) is newer for para_id={target_para_id}", flush=True)
                else:
                    formatting_info[target_para_id] = revised_html
                    formatting_thread_info[target_para_id] = (thread_id, accepted_at)
                    print(f"[EXPORT] Added formatting_info for para_id={target_para_id} from thread {thread_id}", flush=True)
                
        response_text = suggestion.get("response", "")
        if response_text:
            thread = dom_model.comments.get_thread(thread_id)
            reply_exists = False
            if thread:
                for existing_reply in thread.replies:
                    if existing_reply.author == author:
                        reply_exists = True
                        print(f"[EXPORT] Reply from '{author}' already exists in thread {thread_id}, skipping", flush=True)
                        break
            
            if not reply_exists:
                reply = dom_model.add_reply(
                    parent_comment_id=thread_id,
                    text=response_text,
                    author=author,
                    timestamp=datetime.now()
                )
                if reply:
                    print(f"[EXPORT] Added reply to thread {thread_id}", flush=True)
    
    print(f"[EXPORT] Collected formatting info for {len(formatting_info)} paragraphs", flush=True)
    
    original_name = session["filename"]
    base_name = original_name.rsplit('.', 1)[0]
    output_name = f"{base_name}_with_replies.docx"
    output_dir = Path(session["output_dir"])
    output_path = output_dir / output_name
    
    serializer = DocumentSerializer()
    serializer.serialize(
        model=dom_model,
        output_path=output_path,
        include_track_changes=do_tracked_changes,
        preserve_original=True,
        formatting_info=formatting_info
    )
    
    print(f"[EXPORT] Saved to {output_path}", flush=True)
    
    if use_native_dialog:
        return JSONResponse({
            "success": True,
            "source_path": str(output_path),
            "filename": output_name
        })
    
    return FileResponse(
        path=str(output_path),
        filename=output_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
