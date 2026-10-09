"""
Attachment routes for the Stet application.

Handles file attachment upload, removal, and page selection for PDFs.
"""

from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Form
from pathlib import Path
import shutil
import uuid

from src.file_parsers import PDFParser
from src.routes.state import get_session, get_thread_object, save_session, get_templates
from src.routes.helpers import render_thread_card


router = APIRouter(tags=["attachments"])


@router.post("/add_attachment/{session_id}/{thread_id}")
async def add_attachment(
    request: Request,
    session_id: str,
    thread_id: str,
    file: UploadFile = File(...)
):
    """Add a file attachment to a thread."""
    print(f"[ATTACHMENT] Received upload request: session={session_id}, thread={thread_id}, file={file.filename}", flush=True)
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    existing_attachments = session.get("attachments", {}).get(thread_id, [])
    for existing in existing_attachments:
        if existing.get("filename", "").lower() == file.filename.lower():
            print(f"[ATTACHMENT] Duplicate detected: {file.filename} already attached to thread {thread_id}", flush=True)
            return await render_thread_card(request, session_id, thread_id, session, thread, templates)
    
    filename = file.filename.lower()
    if filename.endswith('.pdf'):
        file_type = 'pdf'
    elif filename.endswith('.xlsx'):
        file_type = 'xlsx'
    elif filename.endswith('.xls'):
        file_type = 'xls'
    elif filename.endswith('.csv'):
        file_type = 'csv'
    elif filename.endswith('.docx'):
        file_type = 'docx'
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, XLSX, XLS, CSV, or DOCX.")
    
    output_dir = Path(session["output_dir"])
    attachments_dir = output_dir / "attachments" / thread_id
    attachments_dir.mkdir(parents=True, exist_ok=True)
    
    attachment_id = str(uuid.uuid4())[:8]
    
    saved_path = attachments_dir / file.filename
    try:
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    attachment_data = {
        "id": attachment_id,
        "filename": file.filename,
        "file_type": file_type,
        "filepath": str(saved_path),
    }
    
    if file_type == 'pdf':
        try:
            parser = PDFParser()
            total_pages = parser.get_page_count(str(saved_path))
            
            default_pages = min(10, total_pages)
            pages_str = f"1-{default_pages}" if default_pages > 1 else "1"
            
            result = parser.parse(str(saved_path), page_range=(1, default_pages))
            token_estimate = result.get_token_estimate()
            
            attachment_data.update({
                "total_pages": total_pages,
                "pages_str": pages_str,
                "pages_selected": list(range(1, default_pages + 1)),
                "token_estimate": token_estimate,
                "parsed_content": result.to_markdown(),
            })
        except Exception as e:
            attachment_data.update({
                "total_pages": 0,
                "pages_str": "1",
                "pages_selected": [1],
                "token_estimate": 0,
                "error": str(e),
            })
    elif file_type in ['xlsx', 'xls', 'csv']:
        try:
            from src.file_parsers import SpreadsheetParser
            parser = SpreadsheetParser()
            result = parser.parse(str(saved_path))
            
            if result.error:
                attachment_data.update({
                    "sheet_count": 0,
                    "sheet_names": [],
                    "token_estimate": 0,
                    "error": result.error,
                    "parsed_content": f"[Error parsing spreadsheet: {result.error}]",
                })
            else:
                token_estimate = result.get_token_estimate()
                attachment_data.update({
                    "sheet_count": result.sheet_count,
                    "sheet_names": [s.name for s in result.sheets],
                    "total_rows": result.total_rows,
                    "token_estimate": token_estimate,
                    "parsed_content": result.to_markdown(),
                })
        except Exception as e:
            attachment_data.update({
                "sheet_count": 0,
                "sheet_names": [],
                "token_estimate": 0,
                "error": str(e),
                "parsed_content": f"[Error parsing spreadsheet: {str(e)}]",
            })
    elif file_type == 'docx':
        try:
            from src.file_parsers import DocxParser
            parser = DocxParser()
            result = parser.parse(str(saved_path))
            
            if result.error:
                attachment_data.update({
                    "section_count": 0,
                    "paragraph_count": 0,
                    "table_count": 0,
                    "token_estimate": 0,
                    "error": result.error,
                    "parsed_content": f"[Error parsing DOCX: {result.error}]",
                })
            else:
                token_estimate = result.get_token_estimate()
                attachment_data.update({
                    "section_count": result.section_count,
                    "paragraph_count": result.paragraph_count,
                    "table_count": result.table_count,
                    "token_estimate": token_estimate,
                    "parsed_content": result.to_markdown(),
                })
        except Exception as e:
            attachment_data.update({
                "section_count": 0,
                "paragraph_count": 0,
                "table_count": 0,
                "token_estimate": 0,
                "error": str(e),
                "parsed_content": f"[Error parsing DOCX: {str(e)}]",
            })
    else:
        attachment_data.update({
            "token_estimate": 0,
            "parsed_content": f"[{file_type.upper()} file: {file.filename} - parsing not supported]",
        })
    
    if thread_id not in session["attachments"]:
        session["attachments"][thread_id] = []
    session["attachments"][thread_id].append(attachment_data)
    
    print(f"[ATTACHMENT] Added attachment: {attachment_data.get('filename')}, tokens: {attachment_data.get('token_estimate')}", flush=True)
    print(f"[ATTACHMENT] Thread {thread_id} now has {len(session['attachments'][thread_id])} attachments", flush=True)
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)


@router.post("/remove_attachment/{session_id}/{thread_id}/{attachment_id}")
async def remove_attachment(
    request: Request,
    session_id: str,
    thread_id: str,
    attachment_id: str
):
    """Remove an attachment from a thread."""
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    attachments = session.get("attachments", {}).get(thread_id, [])
    attachment_to_remove = None
    
    for i, att in enumerate(attachments):
        if att["id"] == attachment_id:
            attachment_to_remove = attachments.pop(i)
            break
    
    if not attachment_to_remove:
        raise HTTPException(status_code=404, detail="Attachment not found")
    
    try:
        filepath = Path(attachment_to_remove["filepath"])
        if filepath.exists():
            filepath.unlink()
    except Exception as e:
        print(f"Warning: Could not delete attachment file: {e}")
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)


@router.post("/update_attachment_pages/{session_id}/{thread_id}/{attachment_id}")
async def update_attachment_pages(
    request: Request,
    session_id: str,
    thread_id: str,
    attachment_id: str,
    pages: str = Form(...)
):
    """Update page selection for a PDF attachment."""
    session = get_session(session_id)
    templates = get_templates()
    
    thread = get_thread_object(session, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    attachments = session.get("attachments", {}).get(thread_id, [])
    attachment = None
    
    for att in attachments:
        if att["id"] == attachment_id:
            attachment = att
            break
    
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    
    if attachment["file_type"] != "pdf":
        raise HTTPException(status_code=400, detail="Page selection only applies to PDFs")
    
    error_message = None
    try:
        parser = PDFParser()
        total_pages = attachment.get("total_pages", 0)
        
        try:
            selected_pages = parser.parse_pages_string(pages, total_pages)
        except ValueError as e:
            error_message = str(e)
            selected_pages = None
        
        if not selected_pages:
            if not error_message:
                error_message = f"No valid pages selected. PDF has {total_pages} pages."
        else:
            invalid_pages = [p for p in selected_pages if p > total_pages]
            if invalid_pages:
                error_message = f"Page(s) {', '.join(map(str, invalid_pages))} exceed PDF length ({total_pages} pages)"
                selected_pages = None
        
        if selected_pages:
            if len(selected_pages) > 10:
                selected_pages = selected_pages[:10]
            
            result = parser.parse_selected_pages(
                attachment["filepath"],
                pages,
                max_pages=10
            )
            
            attachment["pages_str"] = pages
            attachment["pages_selected"] = selected_pages
            attachment["token_estimate"] = result.get_token_estimate()
            attachment["parsed_content"] = result.to_markdown()
            attachment["error"] = None
        else:
            attachment["error"] = error_message
        
    except Exception as e:
        attachment["error"] = f"Error: {str(e)}"
    
    save_session(session_id)
    
    return await render_thread_card(request, session_id, thread_id, session, thread, templates)
