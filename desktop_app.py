"""
Stet Desktop Application Entry Point

This module provides the entry point for running Stet as a native desktop application.
It wraps the FastAPI web application in a native window using pywebview.

Usage:
    Development: python desktop_app.py
    Packaged: Run the generated Stet.exe (Windows) or Stet.app (macOS)
"""

import sys
import socket
import threading
import time
import datetime

# Ensure src module is importable when running as PyInstaller bundle
if hasattr(sys, '_MEIPASS'):
    sys.path.insert(0, sys._MEIPASS)

import webview
import shutil
from pathlib import Path
# Heavy imports (main, uvicorn, pandas, etc.) are deferred to load_and_start_server()
# so the splash screen can show immediately


# =============================================================================
# JavaScript API for native features (file dialogs, etc.)
# =============================================================================

class Api:
    """
    API exposed to JavaScript for native functionality.
    
    Methods here can be called from JavaScript via pywebview.api.method_name()
    """
    
    def __init__(self):
        self._window = None
    
    def set_window(self, window):
        """Set the window reference (called after window creation)."""
        self._window = window
    
    def save_export(self, source_path: str, default_filename: str) -> dict:
        """
        Show a native Save dialog and copy the exported file to user's chosen location.
        
        Args:
            source_path: Path to the source file (in sessions folder)
            default_filename: Suggested filename for the save dialog
            
        Returns:
            dict with 'success' (bool), 'path' (str or None), 'error' (str or None)
        """
        if not self._window:
            return {'success': False, 'path': None, 'error': 'Window not initialized'}
        
        try:
            # Show native save dialog
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=str(Path.home() / 'Documents'),
                save_filename=default_filename
            )
            
            if result:
                # result is a tuple with the chosen path
                dest_path = result if isinstance(result, str) else result[0]
                
                # Ensure .docx extension
                if not dest_path.lower().endswith('.docx'):
                    dest_path += '.docx'
                
                # Copy the file
                shutil.copy2(source_path, dest_path)
                
                return {'success': True, 'path': dest_path, 'error': None}
            else:
                # User cancelled
                return {'success': False, 'path': None, 'error': 'Cancelled'}
                
        except Exception as e:
            return {'success': False, 'path': None, 'error': str(e)}

    def pick_folder(self) -> str | None:
        """
        Show a native folder-picker dialog (workspace shell, Stage 1 M5).

        Returns the chosen absolute folder path, or ``None`` if the dialog was
        cancelled or unavailable. The browser/dev fallback (a path text input)
        lives in the frontend when ``window.pywebview`` is absent.
        """
        if not self._window:
            return None
        try:
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=str(Path.home() / 'Documents'),
            )
            if not result:
                return None
            return result if isinstance(result, str) else result[0]
        except Exception:
            return None


# =============================================================================
# License validation (beta period)
# =============================================================================

def _is_frozen():
    """Check if running as packaged app."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def _check_system_requirements():
    """Verify system meets requirements for this build."""
    if not _is_frozen():
        return True  # Development mode - no restrictions
    
    # Build parameters (obfuscated)
    _p = [0x7EA, 0x5, 0x1]  # 2026, 5, 1 in hex
    _t = datetime.date(_p[0], _p[1], _p[2])
    return datetime.date.today() <= _t


def _get_splash_html():
    """Return HTML for the splash/loading screen."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex; 
                justify-content: center; 
                align-items: center; 
                height: 100vh; 
                margin: 0;
                background: linear-gradient(135deg, #059669 0%, #065f46 100%);
                color: white;
            }
            .container { 
                text-align: center; 
                padding: 40px;
            }
            h1 { 
                margin-bottom: 20px; 
                font-size: 48px;
                font-weight: 600;
            }
            .spinner {
                width: 40px;
                height: 40px;
                margin: 30px auto;
                border: 3px solid rgba(255,255,255,0.3);
                border-top-color: white;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            .status {
                font-size: 14px;
                opacity: 0.8;
                margin-top: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Stet</h1>
            <div class="spinner"></div>
            <p class="status">Starting up...</p>
        </div>
    </body>
    </html>
    """


def _get_license_expired_html():
    """Return HTML for expired license notice."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex; 
                justify-content: center; 
                align-items: center; 
                height: 100vh; 
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .container { 
                text-align: center; 
                padding: 40px;
                background: rgba(255,255,255,0.1);
                border-radius: 16px;
                backdrop-filter: blur(10px);
            }
            h1 { margin-bottom: 10px; }
            p { opacity: 0.9; margin: 10px 0; }
            a { color: #ffd700; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Stet Beta</h1>
            <p>This beta version has expired.</p>
            <p>Please contact <a href="mailto:georgii@example.com">Georgii</a> for an updated version.</p>
            <p style="margin-top: 30px; font-size: 12px; opacity: 0.7;">Thank you for testing Stet!</p>
        </div>
    </body>
    </html>
    """


def _show_license_notice():
    """Display notice when system requirements not met."""
    window = webview.create_window("Stet", html=_get_license_expired_html(), width=500, height=350, resizable=False)
    webview.start()
    sys.exit(0)


def find_free_port(start_port: int = 49152, max_attempts: int = 100) -> int:
    """
    Find an available port to avoid conflicts.
    
    Starts searching from start_port (default 49152, beginning of dynamic port range).
    """
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"Could not find free port in range {start_port}-{start_port + max_attempts}")


def start_server(port: int, fastapi_app):
    """
    Start the FastAPI server in the current thread.
    
    This runs Uvicorn with minimal logging to avoid console spam in packaged mode.
    """
    import uvicorn
    log_level = "warning" if _is_frozen() else "info"
    uvicorn.run(
        fastapi_app, 
        host="127.0.0.1", 
        port=port, 
        log_level=log_level,
        access_log=not _is_frozen()  # Disable access log in packaged mode
    )


def wait_for_server(port: int, timeout: float = 10.0) -> bool:
    """
    Wait for the server to be ready and serving HTTP (not just listening).
    Polls GET /health so we don't open the app URL before FastAPI is ready,
    which would cause intermittent "server error" dialogs on startup.
    """
    import urllib.request
    import urllib.error

    start_time = time.time()
    url = f"http://127.0.0.1:{port}/health"

    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(('127.0.0.1', port))
        except OSError:
            time.sleep(0.1)
            continue

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.15)

    return False


def load_and_start_server(window, port: int):
    """
    Background task: Load heavy imports, initialize app, start server, then navigate.
    
    This runs in a separate thread so the splash screen shows immediately.
    """
    try:
        # Import heavy modules (this is what takes time)
        from main import app as fastapi_app
        from src.paths import ensure_dirs
        
        # Ensure required directories exist
        ensure_dirs()
        
        # Start FastAPI server in yet another thread
        server_thread = threading.Thread(
            target=start_server, 
            args=(port, fastapi_app), 
            daemon=True
        )
        server_thread.start()
        
        # Wait for server to be ready
        if wait_for_server(port, timeout=30.0):
            # Navigate to the app
            window.load_url(f"http://127.0.0.1:{port}")
        else:
            # Show error in the window
            window.load_html("""
                <html><body style="font-family: sans-serif; display: flex; justify-content: center; 
                align-items: center; height: 100vh; margin: 0; background: #ff6b6b; color: white;">
                <div style="text-align: center;">
                    <h1>Startup Error</h1>
                    <p>Server failed to start. Please try restarting the application.</p>
                </div></body></html>
            """)
    except Exception as e:
        # Show error in the window
        window.load_html(f"""
            <html><body style="font-family: sans-serif; display: flex; justify-content: center; 
            align-items: center; height: 100vh; margin: 0; background: #ff6b6b; color: white;">
            <div style="text-align: center; padding: 40px;">
                <h1>Startup Error</h1>
                <p>Failed to initialize: {str(e)}</p>
            </div></body></html>
        """)


def main():
    """Main entry point for desktop application."""
    # Verify system requirements (beta license check)
    if not _check_system_requirements():
        _show_license_notice()
        return
    
    # Find an available port early (this is fast)
    try:
        port = find_free_port()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Enable file downloads (fallback, but we prefer native dialog)
    webview.settings['ALLOW_DOWNLOADS'] = True
    
    # Create API instance for native functionality
    api = Api()

    # Create native window with splash screen immediately
    window = webview.create_window(
        title="Stet",
        html=_get_splash_html(),  # Show splash immediately
        width=1400,
        height=900,
        resizable=True,
        min_size=(900, 600),
        text_select=True,
        js_api=api  # Expose API to JavaScript
    )
    
    # Set window reference on API
    api.set_window(window)
    
    # Start heavy loading in background after window is created
    def on_shown():
        loader_thread = threading.Thread(
            target=load_and_start_server,
            args=(window, port),
            daemon=True
        )
        loader_thread.start()
    
    # Start the webview - the splash shows instantly, then loading happens
    webview.start(on_shown)


if __name__ == "__main__":
    main()
