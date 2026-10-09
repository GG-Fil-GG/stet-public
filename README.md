# Stet

A FastAPI + HTMX web application to help address reviewer comments in Word manuscripts using AI.

> **stet** /stɛt/ — *Latin: "let it stand"* — A proofreader's term meaning "ignore the correction, keep the original." Ironically, this app helps you *address* corrections, but with the wisdom to know when the original was right all along.

## Quick Start

See [LAUNCH_GUIDE.md](LAUNCH_GUIDE.md) for detailed instructions.

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Launch the application
python main.py
```

Then open your browser to: **http://localhost:8000**

## Project Structure

- `main.py` - FastAPI application entry point
- `src/` - Main application code
- `templates/` - Jinja2 HTML templates (HTMX partials)
- `static/` - Static files (CSS, JS, images)
- `docs/` - Specification and planning notes
- `tests/` - Test files
- `_archive/` - Old experimental code for reference
- `test_data/synthetic/` - Synthetic fixtures (committed). `test_data/local/` - real manuscripts (gitignored)
- `output/` - Generated outputs (gitignored)

## Technology Stack

- **Backend:** FastAPI (Python)
- **Frontend:** HTMX + Tailwind CSS
- **Templates:** Jinja2
- **LLM Integration:** OpenAI, Ollama (configurable)

## Features

- Upload DOCX files with reviewer comments
- AI-powered suggestions for addressing comments
- Context expansion for better understanding
- Track changes and reply insertion
- Paragraph split/merge support (LLM or manual editing can restructure paragraphs)
- Field code preservation (EndNote/Zotero citations maintained across edits)
- Session persistence
- Custom LLM instructions per thread or session
