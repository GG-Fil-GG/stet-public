"""
Upload router - handles file upload.

Endpoints:
- POST /upload - Upload a DOCX file
"""

from fastapi import APIRouter, Request, UploadFile, File
from pathlib import Path
import shutil

from src.routes.state import sessions, get_templates
from src.output_manager import get_output_dir, sanitize_filename
from src.document_model import parse_docx
from src.session_utils import (
    create_session_from_model,
    load_session_from_file,
    merge_loaded_session,
    count_thread_statuses,
)
from src.paths import get_sessions_dir

OUTPUT_DIR = get_sessions_dir()

router = APIRouter()


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """Handle DOCX file upload and extract comments."""
    templates = get_templates()
    
    # Validate file type
    if not file.filename.endswith('.docx'):
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"error": "Invalid file type. Please upload a .docx file."},
            status_code=400,
        )
    
    # Create session ID from sanitized filename
    session_id = sanitize_filename(file.filename)
    
    # Get output directory for this document (uses OUTPUT_DIR for dev vs packaged)
    output_dir = get_output_dir(f"uploads/{file.filename}", str(OUTPUT_DIR))
    
    # Save uploaded file to output directory
    saved_filepath = output_dir / file.filename
    
    try:
        # Check if file already exists and count comments before overwriting
        if saved_filepath.exists():
            import zipfile as zf_upload
            try:
                with zf_upload.ZipFile(str(saved_filepath), 'r') as check_zip:
                    check_comments = check_zip.read('word/comments.xml').decode('utf-8')
                    existing_count = check_comments.count('<w:comment ')
                    print(f"[UPLOAD] EXISTING file {saved_filepath} has {existing_count} comments BEFORE overwrite", flush=True)
            except Exception as e:
                print(f"[UPLOAD] Could not check existing file: {e}", flush=True)
        else:
            print(f"[UPLOAD] No existing file at {saved_filepath}", flush=True)
        
        # Save the uploaded file
        with open(saved_filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Verify the newly saved file
        import zipfile as zf_upload2
        with zf_upload2.ZipFile(str(saved_filepath), 'r') as check_zip:
            check_comments = check_zip.read('word/comments.xml').decode('utf-8')
            new_count = check_comments.count('<w:comment ')
            print(f"[UPLOAD] AFTER upload, file {saved_filepath} has {new_count} comments", flush=True)
        
        # Parse document using DOM model (Phase 6: single source of truth)
        model = parse_docx(saved_filepath)
        print(f"[UPLOAD] DOM model created: {model.paragraph_count} paragraphs, {model.comment_count} comments, {model.thread_count} threads", flush=True)
        
        # Initialize session with DOM model as source of truth
        session_data = create_session_from_model(
            session_id=session_id,
            filename=file.filename,
            filepath=str(saved_filepath),
            output_dir=output_dir,
            model=model
        )
        
        # Get threads from model for template rendering
        threads = list(model.comments.threads.values())
        
        # Try to load and merge existing session data
        try:
            loaded_data = load_session_from_file(output_dir)
            if loaded_data:
                valid_thread_ids = set(session_data["thread_status"].keys())
                merge_loaded_session(session_data, loaded_data, valid_thread_ids)
        except Exception as e:
            print(f"Warning: Could not load previous session: {e}")
        
        # Store session
        sessions[session_id] = session_data
        
        # Calculate counts using utility function
        counts = count_thread_statuses(session_data)
        pending_count = counts["pending"]
        accepted_count = counts["accepted"]
        skipped_count = counts["skipped"]
        
        # Return the thread list
        return templates.TemplateResponse(
            request,
            "partials/thread_list.html",
            {
                "session_id": session_id,
                "filename": file.filename,
                "threads": threads,
                "thread_count": len(threads),
                "pending_count": pending_count,
                "accepted_count": accepted_count,
                "skipped_count": skipped_count,
            },
        )
        
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"error": f"Error processing file: {str(e)}"},
            status_code=500,
        )
