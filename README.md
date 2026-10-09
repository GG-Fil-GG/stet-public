# Stet

Stet helps you address reviewer comments in Word manuscripts. It reads a `.docx`, shows the comment threads, and uses a language model to suggest revisions and replies, then writes them back as Word tracked changes.

> **stet** /stɛt/ — Latin for "let it stand" — a proofreader's mark meaning "ignore the correction, keep the original."

## Quick start

Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then set OPENAI_API_KEY
python main.py
```

Open **http://localhost:8000**.

- `/` is the card UI: upload a document and work through comment threads one at a time.
- `/workspace` is the agent workspace: open a folder, read the manuscript, and let the agent edit it.

The settings panel can take an OpenAI API key or an Ollama URL. If that field is empty, the app uses `OPENAI_API_KEY` from `.env`. Ollama must already be running locally if you choose it.

## Features

- Upload `.docx` files that contain reviewer comments
- Suggested revisions and reviewer replies
- Tracked changes written back into the Word file
- EndNote and Zotero field codes kept across edits
- Paragraph split and merge
- An agent workspace that can read the manuscript plus reference PDF, spreadsheet, RTF, and PowerPoint files

## Layout

- `main.py` — application entry point
- `src/` — application code
- `templates/` and `static/` — the UI
- `tests/` — the test suite, using fixtures in `test_data/synthetic/`
- `test_data/local/` — for your own manuscripts; gitignored, so nothing you put there is committed
- [docs/BUILD_WINDOWS.md](docs/BUILD_WINDOWS.md) — building the Windows desktop app

## Tests

```bash
.venv/bin/python -m pytest tests/
```

## License

[MIT](LICENSE)
