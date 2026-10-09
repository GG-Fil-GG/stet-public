"""
Session persistence: creation, JSON serialization, file I/O, and merge.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime

from src.constants import DEFAULT_INSTRUCTIONS, ThreadStatus
from src.chat_types import (
    serialize_chat_history, deserialize_chat_history,
    serialize_chat_snapshots, deserialize_chat_snapshots
)
from src.exceptions import SessionError, SessionCorruptedError

if TYPE_CHECKING:
    from src.document_model import DocumentModel


# =============================================================================
# SESSION SCHEMA
# =============================================================================

def create_empty_session(
    session_id: str,
    filename: str,
    filepath: str,
    output_dir: Path,
    threads: list,
    paragraph_cache: list,
    thread_target_indices: dict
) -> Dict[str, Any]:
    """
    Create a new empty session with default values.
    
    Args:
        session_id: Unique identifier for the session
        filename: Original uploaded filename
        filepath: Path to the saved DOCX file
        output_dir: Directory for session outputs
        threads: List of CommentThread objects
        paragraph_cache: List of document paragraphs
        thread_target_indices: Mapping of thread_id to (start, end) indices
        
    Returns:
        Dictionary with initialized session structure
    """
    return {
        "filename": filename,
        "filepath": filepath,
        "output_dir": str(output_dir),
        "threads": threads,
        "paragraph_cache": paragraph_cache,
        "thread_target_indices": thread_target_indices,
        "suggestions": {},  # thread_id -> suggestion dict
        "thread_status": {t.thread_id: ThreadStatus.PENDING for t in threads},
        "context_settings": {},  # thread_id -> {before_count, after_count, ...}
        "accepted_revisions": {},  # para_id -> revised_text HTML (source of truth for formatting)
        "default_instructions": DEFAULT_INSTRUCTIONS,
        "thread_instructions": {},  # thread_id -> custom instructions
        # Chat mode data
        "chat_history": {},  # thread_id -> list of ChatMessage
        "chat_mode_active": {},  # thread_id -> bool
        "chat_snapshots": {},  # thread_id -> ChatSnapshot
        "chat_completed": {},  # thread_id -> bool
        # Attachments
        "attachments": {},  # thread_id -> list of attachment dicts
    }


def create_session_from_model(
    session_id: str,
    filename: str,
    filepath: str,
    output_dir: Path,
    model: 'DocumentModel'
) -> Dict[str, Any]:
    """
    Create a session with DOM model as the single source of truth.

    This is the Phase 6+ version of session creation that replaces the
    legacy create_empty_session() function.

    Args:
        session_id: Unique identifier for the session
        filename: Original uploaded filename
        filepath: Path to the saved DOCX file
        output_dir: Directory for session outputs
        model: Parsed DocumentModel containing all document data

    Returns:
        Dictionary with initialized session structure
    """
    # Get thread IDs from the model
    thread_ids = list(model.comments.threads.keys())

    # Store a deep copy of the original model for computing diffs and preserving formatting
    # This is the ONLY place we store document state - everything else is computed on demand
    original_model_data = model.to_dict()

    return {
        "filename": filename,
        "filepath": filepath,
        "output_dir": str(output_dir),
        # DOM model is the source of truth for CURRENT document state
        "model": model,
        # Original model data (serialized) for computing diffs against original
        # Use get_original_model() helper to deserialize on demand
        "original_model_data": original_model_data,
        # Thread-specific original text tracking for thread-aware context generation
        # Maps thread_id -> para_id -> original text (before that thread's edit)
        # Used to compute "what the paragraph looked like before this thread modified it"
        "thread_original_text": {},
        # Suggestions still stored separately (LLM responses, rationale)
        "suggestions": {},  # thread_id -> {revised_text, response, rationale}
        "thread_status": {tid: ThreadStatus.PENDING for tid in thread_ids},
        "context_settings": {},  # thread_id -> {before_count, after_count, ...}
        "default_instructions": DEFAULT_INSTRUCTIONS,
        "thread_instructions": {},  # thread_id -> custom instructions
        # Chat mode data
        "chat_history": {},  # thread_id -> list of ChatMessage
        "chat_mode_active": {},  # thread_id -> bool
        "chat_snapshots": {},  # thread_id -> ChatSnapshot
        "chat_completed": {},  # thread_id -> bool
        # Attachments
        "attachments": {},  # thread_id -> list of attachment dicts
        # Empty for backward compatibility (DOM sessions apply edits to model directly)
        "accepted_revisions": {},
    }


# =============================================================================
# SERIALIZATION
# =============================================================================

def serialize_session_for_save(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Serialize session data for JSON persistence.
    
    Converts internal objects (ChatMessage, enums, DocumentModel) to JSON-compatible format.
    
    Args:
        session: Session dictionary with runtime objects
        
    Returns:
        Dictionary suitable for json.dump()
    """
    # Check if this is a DOM-based session (Phase 6+)
    model = session.get("model")
    has_dom_model = model is not None
    
    save_data = {
        "context_settings": session.get("context_settings", {}),
        "default_instructions": session.get("default_instructions", DEFAULT_INSTRUCTIONS),
        "thread_instructions": session.get("thread_instructions", {}),
        "threads": {},
        # Chat mode data (serialize special types)
        "chat_history": serialize_chat_history(session.get("chat_history", {})),
        "chat_mode_active": session.get("chat_mode_active", {}),
        "chat_snapshots": serialize_chat_snapshots(session.get("chat_snapshots", {})),
        "chat_completed": session.get("chat_completed", {}),
        # Attachments
        "attachments": session.get("attachments", {}),
        # Original model data - for computing diffs against original document
        # This replaces original_paragraph_cache and original_thread_target_indices
        "original_model_data": session.get("original_model_data", {}),
        # Thread-specific original text for thread-aware context generation
        "thread_original_text": session.get("thread_original_text", {}),
        # Accepted revisions - para_id -> revised_text HTML for export
        "accepted_revisions": session.get("accepted_revisions", {}),
        # Track paragraphs inserted by each thread (for re-accept cleanup)
        "thread_inserted_paragraphs": session.get("thread_inserted_paragraphs", {}),
        # Metadata
        "saved_at": datetime.now().isoformat(),
        # Version flag for deserialization
        "version": "dom_v2",  # New version for refactored architecture
    }
    
    # Serialize current DOM model
    save_data["model_data"] = model.to_dict()
    
    # Serialize thread statuses and suggestions
    for thread_id, status in session.get("thread_status", {}).items():
        # Convert enum to its value string (e.g., ThreadStatus.ACCEPTED -> "accepted")
        status_str = status.value if hasattr(status, 'value') else str(status)
        thread_data = {"status": status_str}
        
        if thread_id in session.get("suggestions", {}):
            suggestion = session["suggestions"][thread_id]
            thread_data.update({
                "revised_text": suggestion.get("revised_text", ""),
                "revised_text_html": suggestion.get("revised_text_html", ""),  # HTML is source of truth
                "response": suggestion.get("response", ""),
                "rationale": suggestion.get("rationale"),
                "target_para_id": suggestion.get("target_para_id"),
                "all_target_para_ids": suggestion.get("all_target_para_ids"),
                "accepted_at": suggestion.get("accepted_at"),
                # Store original text for undo support (Phase 6+)
                "original_text": suggestion.get("original_text"),
            })
        
        save_data["threads"][thread_id] = thread_data
    
    return save_data


def deserialize_session_data(saved_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deserialize saved session data back to runtime format.
    
    Converts JSON data back to internal objects (ChatMessage, DocumentModel, etc.).
    
    Args:
        saved_data: Dictionary loaded from JSON file
        
    Returns:
        Dictionary with deserialized objects ready for use
    """
    result = {
        "context_settings": saved_data.get("context_settings", {}),
        "default_instructions": saved_data.get("default_instructions", DEFAULT_INSTRUCTIONS),
        "thread_instructions": saved_data.get("thread_instructions", {}),
        # Chat mode data (deserialize special types)
        "chat_history": deserialize_chat_history(saved_data.get("chat_history", {})),
        "chat_mode_active": saved_data.get("chat_mode_active", {}),
        "chat_snapshots": deserialize_chat_snapshots(saved_data.get("chat_snapshots", {})),
        "chat_completed": saved_data.get("chat_completed", {}),
        # Attachments
        "attachments": saved_data.get("attachments", {}),
        # Original model data - for computing diffs against original document
        "original_model_data": saved_data.get("original_model_data", {}),
        # Thread-specific original text for thread-aware context generation
        "thread_original_text": saved_data.get("thread_original_text", {}),
        # Accepted revisions - para_id -> revised_text HTML for export
        "accepted_revisions": saved_data.get("accepted_revisions", {}),
        # Track paragraphs inserted by each thread (for re-accept cleanup)
        "thread_inserted_paragraphs": saved_data.get("thread_inserted_paragraphs", {}),
        # Thread data (processed separately during merge)
        "threads": saved_data.get("threads", {}),
        # Version info
        "version": saved_data.get("version", "legacy"),
    }
    
    # Deserialize current DOM model
    if saved_data.get("model_data"):
        from src.document_model import DocumentModel
        result["model"] = DocumentModel.from_dict(saved_data["model_data"])
    # Note: Legacy sessions without model_data are no longer supported
    
    # Handle backward compatibility: if loading older session with original_paragraph_cache,
    # we need to compute original_model_data from the current model (best effort)
    if not result.get("original_model_data") and result.get("model"):
        # Older session - use current model as original (not ideal but maintains compatibility)
        result["original_model_data"] = result["model"].to_dict()
    
    return result


# =============================================================================
# FILE OPERATIONS
# =============================================================================

def save_session_to_file(session: Dict[str, Any], output_dir: Path) -> bool:
    """
    Save session state to JSON file.
    
    Args:
        session: Session dictionary to save
        output_dir: Directory to save session.json in
        
    Returns:
        True if save succeeded, False otherwise
    """
    session_file = output_dir / "session.json"
    save_data = serialize_session_for_save(session)
    
    try:
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Warning: Could not save session: {e}")
        return False


def load_session_from_file(output_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Load session data from JSON file if it exists.
    
    Args:
        output_dir: Directory containing session.json
        
    Returns:
        Deserialized session data dict, or None if file doesn't exist
        
    Raises:
        SessionCorruptedError: If file exists but is invalid JSON
    """
    session_file = output_dir / "session.json"
    
    if not session_file.exists():
        return None
    
    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        return deserialize_session_data(saved_data)
    except json.JSONDecodeError as e:
        raise SessionCorruptedError(
            str(output_dir), 
            f"Invalid JSON: {e}"
        )
    except Exception as e:
        raise SessionCorruptedError(
            str(output_dir),
            f"Failed to load: {e}"
        )


def merge_loaded_session(
    session_data: Dict[str, Any],
    loaded_data: Dict[str, Any],
    valid_thread_ids: set
) -> Dict[str, Any]:
    """
    Merge loaded session data into a fresh session.
    
    Only restores data for threads that still exist in the document.
    This handles cases where the document was modified between sessions.
    
    Args:
        session_data: Fresh session dictionary to update
        loaded_data: Previously saved session data
        valid_thread_ids: Set of thread IDs that exist in current document
        
    Returns:
        Updated session_data dictionary
    """
    # Check if loaded data has a DOM model (Phase 6+)
    if loaded_data.get("model"):
        # DOM model replaces the fresh one
        session_data["model"] = loaded_data["model"]
        # Update valid_thread_ids from the loaded model
        valid_thread_ids = set(loaded_data["model"].comments.threads.keys())
    # Note: Legacy sessions without a model are no longer supported
    
    # Restore simple fields
    session_data["context_settings"] = loaded_data.get("context_settings", {})
    session_data["default_instructions"] = loaded_data.get("default_instructions", DEFAULT_INSTRUCTIONS)
    session_data["thread_instructions"] = loaded_data.get("thread_instructions", {})
    
    # Restore chat mode data
    session_data["chat_history"] = loaded_data.get("chat_history", {})
    session_data["chat_mode_active"] = loaded_data.get("chat_mode_active", {})
    session_data["chat_snapshots"] = loaded_data.get("chat_snapshots", {})
    session_data["chat_completed"] = loaded_data.get("chat_completed", {})
    
    # Restore attachments
    session_data["attachments"] = loaded_data.get("attachments", {})
    
    # Restore original model data (for computing diffs against original document)
    if loaded_data.get("original_model_data"):
        session_data["original_model_data"] = loaded_data["original_model_data"]
    
    # Restore thread-specific original text for thread-aware context generation
    if loaded_data.get("thread_original_text"):
        session_data["thread_original_text"] = loaded_data["thread_original_text"]
    
    # Restore thread-specific data (only for threads that still exist)
    for thread_id, thread_info in loaded_data.get("threads", {}).items():
        if thread_id in valid_thread_ids:
            # Restore status
            status = thread_info.get("status", ThreadStatus.PENDING)
            # Handle string status from JSON (convert to enum if needed)
            if isinstance(status, str):
                try:
                    status = ThreadStatus(status)
                except ValueError:
                    status = ThreadStatus.PENDING
            session_data["thread_status"][thread_id] = status
            
            # Restore suggestion if present
            if "revised_text" in thread_info:
                session_data["suggestions"][thread_id] = {
                    "revised_text": thread_info.get("revised_text", ""),
                    "revised_text_html": thread_info.get("revised_text_html", ""),  # HTML is source of truth
                    "response": thread_info.get("response", ""),
                    "rationale": thread_info.get("rationale"),
                    "target_para_id": thread_info.get("target_para_id"),
                    "all_target_para_ids": thread_info.get("all_target_para_ids"),
                    "accepted_at": thread_info.get("accepted_at"),
                    "original_text": thread_info.get("original_text"),
                }
    
    return session_data


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def count_thread_statuses(session: Dict[str, Any]) -> Dict[str, int]:
    """
    Count threads by status.
    
    Args:
        session: Session dictionary
        
    Returns:
        Dict with 'pending', 'accepted', 'skipped' counts
    """
    statuses = session.get("thread_status", {}).values()
    return {
        "pending": sum(1 for s in statuses if s == ThreadStatus.PENDING),
        "accepted": sum(1 for s in statuses if s == ThreadStatus.ACCEPTED),
        "skipped": sum(1 for s in statuses if s == ThreadStatus.SKIPPED),
    }
