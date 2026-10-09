"""
Shared state and session management for route modules.

This module provides access to the sessions dictionary and
common session-related functions.
"""

from pathlib import Path
from fastapi import HTTPException
from fastapi.templating import Jinja2Templates

from src.session_utils import (
    save_session_to_file,
    get_model_from_session,
    convert_dom_thread_for_llm,
)
from src.paths import get_templates_dir
from src.diff_utils import highlight_text_in_html


# In-memory session storage - this is the single source of truth
# Structure: {session_id: {filename, filepath, threads, paragraph_cache, thread_target_indices, ...}}
sessions: dict = {}


# Setup Jinja2 templates (shared instance)
_templates: Jinja2Templates = None


def get_templates() -> Jinja2Templates:
    """Get the shared Jinja2 templates instance (lazily initialized)."""
    global _templates
    if _templates is None:
        TEMPLATES_DIR = get_templates_dir()
        _templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        _templates.env.filters['highlight_text'] = highlight_text_in_html
    return _templates


def get_session(session_id: str) -> dict:
    """Get session data or raise 404."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]


def get_thread_object(session: dict, thread_id: str):
    """Build a ThreadContext on demand from the live DocumentModel.

    Always reads from the current model state so callers never
    see stale data after DOM edits.  Returns None if the thread
    does not exist.
    """
    dom_model = get_model_from_session(session)
    if dom_model is None:
        return None
    dom_thread = dom_model.comments.threads.get(thread_id)
    if dom_thread is None:
        return None
    return convert_dom_thread_for_llm(dom_thread, dom_model)


def save_session(session_id: str):
    """Save session state to JSON file for persistence."""
    if session_id not in sessions:
        return
    
    session = sessions[session_id]
    output_dir = Path(session["output_dir"])
    save_session_to_file(session, output_dir)
