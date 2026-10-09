"""
Session management routes for the Stet application.

Handles session deletion and cleanup operations.
"""

import shutil
from pathlib import Path
from typing import List, Dict, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.paths import get_sessions_dir
from src.routes.state import sessions


router = APIRouter(tags=["sessions"])


def get_session_folders() -> List[Dict[str, Any]]:
    """
    Get list of all session folders with metadata.
    
    Returns:
        List of dicts with 'name', 'path', 'size_mb', and 'has_session_file' keys
    """
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return []
    
    result = []
    for folder in sessions_dir.iterdir():
        if folder.is_dir():
            size_bytes = sum(f.stat().st_size for f in folder.rglob('*') if f.is_file())
            result.append({
                'name': folder.name,
                'path': str(folder),
                'size_mb': round(size_bytes / (1024 * 1024), 2),
                'has_session_file': (folder / 'session.json').exists()
            })
    
    return sorted(result, key=lambda x: x['name'])


def delete_session_folder(session_id: str) -> bool:
    """
    Delete a session folder and all its contents.
    
    Args:
        session_id: The session ID (folder name) to delete
        
    Returns:
        True if deleted successfully, False otherwise
    """
    sessions_dir = get_sessions_dir()
    session_folder = sessions_dir / session_id
    
    if not session_folder.exists():
        return False
    
    if not session_folder.is_dir():
        return False
    
    try:
        shutil.rmtree(session_folder)
        
        # Also remove from in-memory sessions dict if present
        if session_id in sessions:
            del sessions[session_id]
        
        return True
    except Exception as e:
        print(f"[SESSION] Error deleting session {session_id}: {e}", flush=True)
        return False


@router.get("/sessions/list")
async def list_sessions():
    """List all session folders."""
    folders = get_session_folders()
    total_size = sum(f['size_mb'] for f in folders)
    
    return JSONResponse({
        "sessions": folders,
        "count": len(folders),
        "total_size_mb": round(total_size, 2)
    })


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a specific session's data.
    
    Args:
        session_id: The session ID to delete
    """
    success = delete_session_folder(session_id)
    
    if success:
        print(f"[SESSION] Deleted session: {session_id}", flush=True)
        return JSONResponse({
            "success": True,
            "message": f"Session '{session_id}' deleted"
        })
    else:
        return JSONResponse({
            "success": False,
            "message": f"Session '{session_id}' not found or could not be deleted"
        }, status_code=404)


@router.delete("/sessions/all")
async def delete_all_sessions():
    """Delete all session data."""
    folders = get_session_folders()
    deleted = 0
    failed = 0
    
    for folder in folders:
        if delete_session_folder(folder['name']):
            deleted += 1
        else:
            failed += 1
    
    print(f"[SESSION] Deleted {deleted} sessions, {failed} failed", flush=True)
    
    return JSONResponse({
        "success": failed == 0,
        "deleted": deleted,
        "failed": failed,
        "message": f"Deleted {deleted} session(s)" + (f", {failed} failed" if failed else "")
    })
