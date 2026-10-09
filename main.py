"""
Stet - FastAPI Application

A tool for medical writers to address reviewer comments in DOCX files
using AI-powered suggestions.

Formerly known as "Comment Addresser".
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from datetime import date

from src.agent.errors import ToolError
from src.logging_config import configure_logging

from src.paths import (
    get_templates_dir, get_static_dir, get_sessions_dir,
    ensure_dirs, is_frozen
)
from src.constants import ThreadStatus, APP_NAME, APP_VERSION
from src.session_utils import (
    load_session_from_file,
    merge_loaded_session,
    create_session_from_model,
)
from src.routes.state import sessions, get_templates
from src.routes import export as export_router
from src.routes import attachments as attachments_router
from src.routes import chat as chat_router
from src.routes import suggestions as suggestions_router
from src.routes import threads as threads_router
from src.routes import config as config_router
from src.routes import upload as upload_router
from src.routes import sessions as sessions_router
from src.routes import workspace as workspace_router

# Enable INFO logging for src.* (agent per-step trace) and mute progress-poll spam
configure_logging()

# Ensure required directories exist
ensure_dirs()


def _verify_session_token() -> bool:
    """Verify session is valid for current build."""
    if not is_frozen():
        return True
    # Validation params
    _v = (2026 - 4, 10 >> 1, 2 - 1)  # Obfuscated: 2022+4=2026, 10/2=5, 2-1=1
    _d = date(_v[0] + 4, _v[1], _v[2])
    return date.today() <= _d


# Setup paths using helpers (works for both dev and packaged modes)
TEMPLATES_DIR = get_templates_dir()
STATIC_DIR = get_static_dir()
OUTPUT_DIR = get_sessions_dir()  # Sessions/output directory


# =============================================================================
# SESSION PERSISTENCE
# =============================================================================

def _load_existing_sessions():
    """
    Load all existing sessions from disk on startup.
    
    Scans the output directory for session.json files and loads them
    into the in-memory sessions dictionary.
    """
    loaded_count = 0
    failed_count = 0
    
    if not OUTPUT_DIR.exists():
        return
    
    for session_dir in OUTPUT_DIR.iterdir():
        if not session_dir.is_dir():
            continue
        
        session_file = session_dir / "session.json"
        if not session_file.exists():
            continue
        
        # Extract session_id from directory name (format: filename_timestamp or similar)
        session_id = session_dir.name
        
        try:
            loaded_data = load_session_from_file(session_dir)
            if loaded_data:
                # Check if source file still exists
                filepath = session_dir / "source.docx"  # Standard name after upload
                if not filepath.exists():
                    # Try to find any .docx file
                    docx_files = list(session_dir.glob("*.docx"))
                    if docx_files:
                        filepath = docx_files[0]
                    else:
                        print(f"[Session] Skipping {session_id}: no source file found")
                        continue
                
                # Reconstruct session from loaded data
                if loaded_data.get("model"):
                    # DOM session - model was already deserialized
                    model = loaded_data["model"]
                    model.source_path = filepath  # Update source path
                    
                    session_data = create_session_from_model(
                        session_id=session_id,
                        filename=loaded_data.get("filename", session_dir.name),
                        filepath=str(filepath),
                        output_dir=session_dir,
                        model=model
                    )
                    
                    # Merge saved state (statuses, suggestions, etc.)
                    valid_thread_ids = set(model.comments.threads.keys())
                    session_data = merge_loaded_session(session_data, loaded_data, valid_thread_ids)
                    
                    sessions[session_id] = session_data
                    loaded_count += 1
                    print(f"[Session] Loaded DOM session: {session_id}")
                else:
                    # Legacy session - skip for now (would need more reconstruction)
                    print(f"[Session] Skipping legacy session: {session_id}")
                    
        except Exception as e:
            failed_count += 1
            print(f"[Session] Failed to load {session_id}: {e}")
    
    print(f"[Session] Startup complete: {loaded_count} loaded, {failed_count} failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load existing sessions on server startup."""
    print(f"[{APP_NAME}] Starting up...")
    _load_existing_sessions()
    yield


# Initialize FastAPI app
app = FastAPI(
    title=APP_NAME,
    description="AI-powered tool for addressing reviewer comments in DOCX files",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include routers
app.include_router(export_router.router)
app.include_router(attachments_router.router)
app.include_router(chat_router.router)
app.include_router(suggestions_router.router)
app.include_router(threads_router.router)
app.include_router(config_router.router)
app.include_router(upload_router.router)
app.include_router(sessions_router.router)
app.include_router(workspace_router.router)


# Map structured agent/workspace ToolErrors to JSON responses.
_TOOLERROR_STATUS = {
    "not_found": 404,
    "outside_workspace": 400,
    "overwrite_requires_confirmation": 409,
    "conflict": 409,
    "invalid_argument": 400,
    "parse_failed": 422,
    "template_missing": 500,
}


@app.exception_handler(ToolError)
async def _tool_error_handler(request: Request, exc: ToolError):
    status = _TOOLERROR_STATUS.get(exc.code, 400)
    return JSONResponse(status_code=status, content={"error": exc.code, "message": exc.message})


# Handle favicon/apple-touch-icon requests to prevent 404 noise in logs
@app.get("/favicon.ico", include_in_schema=False)
@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def favicon():
    """Return empty response for favicon requests (no icon configured)."""
    return Response(status_code=204)


# Get shared templates instance
templates = get_templates()

# DEFAULT_INSTRUCTIONS is now imported from src.constants
# sessions dict is imported from src.routes.state


# get_session and save_session are imported from src.routes.state


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main page with file upload."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "Stet"},
    )


# Upload route is now in src/routes/upload.py
# Config routes (instructions, llm-config) are in src/routes/config.py
# Thread routes (get_thread_card, expand_context, diff_html, token-count) are in src/routes/threads.py
# Chat routes are in src/routes/chat.py
# Export routes are in src/routes/export.py
# Attachment routes are in src/routes/attachments.py
# Suggestions routes are in src/routes/suggestions.py


def _asset_version() -> str:
    """Cache-busting token from the workspace static assets' newest mtime.

    Appended as ``?v=`` to the workspace JS/CSS so the browser refetches them
    whenever they change (no build step / content hashing in this stack).
    """
    mtimes = [0.0]
    for rel in ("js/workspace.js", "css/workspace.css"):
        try:
            mtimes.append((STATIC_DIR / rel).stat().st_mtime)
        except OSError:
            pass
    return str(int(max(mtimes)))


@app.get("/workspace", response_class=HTMLResponse)
async def workspace_page(request: Request):
    """Render the agentic workspace shell (three-panel UI; Stage 1, M5)."""
    return templates.TemplateResponse(
        request,
        "workspace.html",
        {"title": "Stet — Workspace", "asset_version": _asset_version()},
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": APP_VERSION}


@app.get("/sessions")
async def list_sessions():
    """List all active sessions (for debugging)."""
    return {
        session_id: {
            "filename": data["filename"],
            "thread_count": data["model"].comments.thread_count,
            "accepted_count": sum(1 for s in data["thread_status"].values() if s == ThreadStatus.ACCEPTED),
            "skipped_count": sum(1 for s in data["thread_status"].values() if s == ThreadStatus.SKIPPED),
        }
        for session_id, data in sessions.items()
    }


# Development server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
