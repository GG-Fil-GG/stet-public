"""
Path utilities for Stet application.

Handles path resolution for both development mode and PyInstaller packaged mode.
In development, paths are relative to the project root.
When packaged, bundled resources are extracted to sys._MEIPASS.
"""

import sys
import os
from pathlib import Path


def is_frozen() -> bool:
    """Check if running as a PyInstaller bundle."""
    return hasattr(sys, '_MEIPASS')


def get_project_root() -> Path:
    """
    Get the project root directory.
    
    In development: The directory containing main.py
    When packaged: sys._MEIPASS (PyInstaller's temp extraction dir)
    """
    if is_frozen():
        return Path(sys._MEIPASS)
    # Development mode - src/paths.py is in src/, so go up one level
    return Path(__file__).resolve().parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    Get absolute path to a bundled resource (templates, static, config).
    
    Args:
        relative_path: Path relative to project root (e.g., "templates", "config/llm_providers.yaml")
    
    Returns:
        Absolute Path to the resource
    """
    return get_project_root() / relative_path


def get_user_data_dir() -> Path:
    """
    Get platform-appropriate directory for user data (sessions, settings).
    
    This directory persists across app updates and is writable.
    
    Returns:
        - Windows: %APPDATA%/Stet
        - macOS: ~/Library/Application Support/Stet
        - Linux: ~/.config/stet
    """
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        return Path(base) / 'Stet'
    elif sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Stet'
    else:
        # Linux and other Unix-like
        return Path.home() / '.config' / 'stet'


def get_sessions_dir() -> Path:
    """Get directory for session data storage."""
    if is_frozen():
        # Packaged app - use user data directory
        return get_user_data_dir() / 'sessions'
    else:
        # Development mode - use output/ in project directory (existing behavior)
        return get_project_root() / 'output'


def get_exports_dir() -> Path:
    """
    Get default directory for exported files.
    
    Uses the user's Documents folder with a Stet Exports subfolder.
    """
    if sys.platform == 'win32':
        docs = Path.home() / 'Documents'
    else:
        docs = Path.home() / 'Documents'
    return docs / 'Stet Exports'


def ensure_dirs():
    """
    Create necessary directories on startup.
    
    Call this at app initialization to ensure all required directories exist.
    """
    dirs_to_create = [get_sessions_dir()]
    
    if is_frozen():
        # Only create user data dir when packaged
        user_data = get_user_data_dir()
        dirs_to_create.append(user_data)
        
        for d in dirs_to_create:
            d.mkdir(parents=True, exist_ok=True)
        
        # Copy .env.example to user data dir on first run (if not exists)
        env_example_src = get_project_root() / '.env.example'
        env_example_dst = user_data / '.env.example'
        readme_path = user_data / 'README.txt'
        
        if env_example_src.exists() and not env_example_dst.exists():
            import shutil
            shutil.copy(env_example_src, env_example_dst)
        
        # Create a README explaining configuration
        if not readme_path.exists():
            readme_path.write_text(
                "Stet Configuration\n"
                "==================\n\n"
                "To use OpenAI models, create a .env file in this folder with:\n"
                "  OPENAI_API_KEY=your-api-key-here\n\n"
                "For Ollama (local LLM), just make sure Ollama is running.\n\n"
                "See .env.example for all available settings.\n"
            )
    else:
        for d in dirs_to_create:
            d.mkdir(parents=True, exist_ok=True)


# Convenience accessors for common paths
def get_templates_dir() -> Path:
    """Get the templates directory."""
    return get_resource_path('templates')


def get_static_dir() -> Path:
    """Get the static files directory."""
    return get_resource_path('static')


def get_config_dir() -> Path:
    """Get the config directory."""
    return get_resource_path('config')


def get_test_data_dir() -> Path:
    """Get the test data directory (development only)."""
    return get_resource_path('test_data')
