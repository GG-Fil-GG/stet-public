# Building and Testing the Stet Distributable on Windows

This guide walks you through compiling and testing the Windows desktop distributable (`.exe`) for Stet on a Windows machine.

## Prerequisites

- **Python 3.8+** installed and on your PATH
- **Git** (optional; only if you clone the repo)
- Enough disk space for the virtual environment and the built executable (roughly 500 MB–1 GB)

## Step 1: Open a terminal in the project root

Open PowerShell or Command Prompt and go to the project folder:

```powershell
cd C:\Users\tom78\Documents\stet
```

(Use your actual path if different.)

## Step 2: Create and activate a virtual environment

Create a venv (if you don’t already have one):

```powershell
python -m venv .venv
```

Activate it:

- **PowerShell:**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Command Prompt (cmd):**
  ```cmd
  .venv\Scripts\activate.bat
  ```

You should see `(.venv)` in the prompt.

## Step 3: Install dependencies

Install runtime and build dependencies:

```powershell
pip install -r requirements.txt
pip install pyinstaller
```

PyInstaller is not in `requirements.txt` but is required for building the executable.

## Step 4: Build the executable with PyInstaller

From the project root (with `.venv` activated), run:

```powershell
pyinstaller Stet.spec
```

- **Input:** `Stet.spec` (entry point: `desktop_app.py`; bundles `templates`, `static`, `config`, and `src`).
- **Output:** A single executable at `dist\Stet.exe` (no console window; uses the native window via pywebview).

Build time is typically one to several minutes. If you see errors about missing modules, add them to `hiddenimports` in `Stet.spec` and rebuild.

## Step 5: Run and test the distributable

1. **Run the app**
   - In Explorer, go to `dist\` and double‑click `Stet.exe`, or from the project root:
     ```powershell
     .\dist\Stet.exe
     ```
   - A native window should open with the Stet UI (FastAPI served locally inside the app).

2. **API key (OpenAI)**  
   The app loads `.env` from the **current working directory**. For the exe:
   - Either put a `.env` file in the same folder as `Stet.exe` (e.g. `dist\.env`) with:
     ```env
     OPENAI_API_KEY=sk-your-key-here
     ```
   - Or set the key in the in‑app **Settings** (if the UI supports it).
   - Or set the environment variable for your user or system: `OPENAI_API_KEY=sk-...`

3. **Smoke tests**
   - Open the app and confirm the main page loads.
   - Upload a small DOCX with reviewer comments (use `test_data/` if you have sample files).
   - Request an AI suggestion (OpenAI or Ollama) and confirm it runs.
   - Use **Export** and confirm the file downloads (pywebview allows downloads by default in this build).

4. **User data locations (packaged app)**  
   When running from `Stet.exe`:
   - Session/output data: `%APPDATA%\Stet\sessions`
   - Default export location: `Documents\Stet Exports`

## Step 6: Optional – debugging a crashing exe

If the window closes immediately, run `Stet.exe` from a terminal to see if any error is printed. To get a console window attached to the app (so you can see tracebacks), edit `Stet.spec`, set `console=True` in the `EXE(...)` block, rebuild with `pyinstaller Stet.spec`, then run `dist\Stet.exe` again. Set `console=False` and rebuild when you are done debugging.

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| **"Python not found"** | Install Python 3.8+ and ensure it’s on PATH, or use the full path to `python.exe` and `pip`. |
| **Script execution disabled (PowerShell)** | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once, or use Command Prompt for activation. |
| **Import errors when running exe** | Add the missing module name to `hiddenimports` in `Stet.spec`, then run `pyinstaller Stet.spec` again. |
| **Templates or static files not found** | Confirm `templates`, `static`, and `config` exist in the project root and are listed in the `datas` list in `Stet.spec`. |
| **Window opens then closes** | Run from a terminal so you can see any traceback: `.\dist\Stet.exe` (or temporarily set `console=True` in `Stet.spec` and rebuild to see a console). |
| **Beta / license notice** | The desktop build includes a beta date check. If the notice appears, the check may need to be updated or disabled for your build. |

## Summary

1. Open terminal in project root → create/activate `.venv`
2. `pip install -r requirements.txt` and `pip install pyinstaller`
3. `pyinstaller Stet.spec`
4. Run `dist\Stet.exe`, optionally add `dist\.env` for `OPENAI_API_KEY`
5. Test: upload DOCX, generate suggestion, export document

The distributable you can share is `dist\Stet.exe` (and optionally a `dist\.env.example` or instructions for the API key).
