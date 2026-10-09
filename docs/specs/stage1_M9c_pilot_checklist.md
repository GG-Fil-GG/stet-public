# Stage 1 — M9c Pilot Checklist

**Purpose:** End-to-end manual test of all Stage 1 functionality on a real manuscript, ahead of the M9c closeout (default-route flip, audit update, mark Stage 1 complete).
**Related:** [M9 spec §6](stage1_M9_spec.md) (pilot flow outline) · consolidates the manual-QA sections of M5–M9b.
**How to run:** Launch the desktop app (`python desktop_app.py`) and open `/workspace`, or open `http://127.0.0.1:8000/workspace` in a browser (path text-input fallback for "Open folder"). Use a real docx from `test_data/local/` (and the synthetic `test_data/synthetic/test.docx`).

---

## A. Workspace & files (M5)

- [x] Open a folder — native dialog in the desktop app; path text-input fallback in a plain browser
- [x] File tree renders; nested folders expand/collapse
- [x] Click a `.docx` → opens in the viewer (formatted, read-only)
- [ ] Settings → pick provider/model (+ OpenAI key or Ollama URL/model) → Save

## B. Viewer — read fidelity (M6a)

- [x] Paragraphs are separated (no run-on lines); tables show as distinct rows
- [x] Existing tracked changes show: insertions green, deletions red strike-through
- [x] Anchored comments highlighted in text + listed in the right rail; resolved threads look muted
- [x] Click a comment card → scrolls/flashes its anchor; click a highlighted span → flashes its card

## C. Viewer — manual edit (M6b)

- [ ] Hover a paragraph → **Edit** appears (no Edit on table rows)
- [ ] Edit + Save → block updates, **● unsaved** appears; change shows as word-level tracked change
- [ ] Cancel an edit → block unchanged, no unsaved bump
- [ ] Header **Save** persists to disk → re-open the file confirms it stuck
- [ ] Checkpoint restore undoes a manual edit

## D. Agent chat (M7)

- [ ] Multi-turn: second message sees context from the first
- [ ] Reload history: refresh / re-open the folder → chat bubbles return
- [ ] Chat persists across open/close/switch of documents
- [ ] Details toggle → step trace for current and reloaded turns
- [ ] **Stop** a multi-step run → "Run cancelled" banner; only pre-cancel edits applied
- [ ] **Clear chat** → panel clears and the next turn starts fresh context
- [ ] Step links: `edit_paragraph` step → scrolls/flashes the paragraph; comment tools → thread
- [ ] Status banners seen as appropriate: completed / stopped / max steps / cancelled / awaiting confirmation

## E. Agent tools / reference reading (M3, M8)

- [x] `list_workspace_files`, `read_document`, `read_paragraph`, `find_in_document`, `list_comments`
- [ ] `read_file` across every format: **pdf, xlsx, xls, csv, docx, rtf, pptx, txt, md**
- [ ] Unsupported type (e.g. `.jpeg`) → clear "unsupported file type" error, not a crash
- [ ] `add_comment_reply` adds a reply to a thread
- [ ] Overwrite confirmation: export onto an existing file → **awaiting confirmation** banner → confirm writes / decline doesn't

## F. Unicode protection (M9a)

- [ ] Ask the agent to lightly edit a paragraph containing `≥`/`≤`/`±`/`°` → the symbol survives in the tracked change (not garbled, not a `__UNICODE_*_`_ placeholder)

## G. Config UI (M9b)

- [ ] No folder open → workspace controls greyed with the note; folder open → they populate and are editable
- [ ] Set `tool_error_policy` → **Stop and ask**, trigger a tool error → **stopped** banner
- [ ] Change `checkpoint_policy` / `max_agent_steps` / `max_checkpoints` → respected next run; persists in `.stet/config.json`

## H. Export & Word round-trip (the real payoff)

- [ ] Export the edited document → open in **Word** → agent/manual edits appear as **real Word tracked changes** (Accept/Reject works)
- [ ] Comments survive; special symbols (`≥` etc.) intact
- [ ] `create_document` produces a valid blank docx at a path

---

## Known limitations — do NOT re-report these as bugs

- **Agent edits strip run formatting** (e.g. bold "Methods:") — logged Stage 2 backlog
- **Images** (`.jpeg`/`.png`) unsupported — Stage 2 backlog
- **Non-docx files** have no in-viewer preview (sidebar only; the agent reads them via tools)
- **Soft line breaks** (`<w:br/>`) aren't preserved by the parser
- **Token retention** during heavy paraphrasing is a strong nudge, not a hard guarantee

---

## Pilot outcome

- **Date / tester:** 2026-06-10 / project owner (first real-manuscript attempt)
- **Document(s) used:** `test_data/local/stage1_M9c/` (gitignored) — a local manuscript (653 paragraphs, 41 open comment threads) plus about 12 reference files. Task: address all comments using the reference materials.
- **Result:** **blocked** — the run made real edits (5 `edit_paragraph`, 3 `add_comment`, 2 `add_comment_reply`, all reported applied), but **none survived to the saved file** (data loss). Slowness during the run had already been triaged into M9c-prep, which was implemented and confirmed working (progress visible, stop responsive, budget UI) — points 1–3 of the M9c-prep manual QA passed.
- **New findings (not in known-limitations) — all diagnosed 2026-06-22:**
  1. **Edit-durability defect (critical / data loss).** Agent (and manual) edits live only in the in-memory `DocumentModel`; `workspace.json` persists the conversation, chat log, and open-document pointer but **not the working model**. Any re-open of the document (file-tree click, folder re-open, browser reload) re-parses the pristine file and silently discards unsaved edits — so "Save" then writes an edit-free document. Confirmed: the saved copy's `word/document.xml` was byte-identical to the pristine original, and the serializer round-trips byte-identical only for an unedited model. Edits were recoverable from the session log but that is not a workflow. → **M9d**.
  2. **Sidebar filename truncation.** Long filenames are clipped by the file-panel edge with no tooltip and no way to widen the panel, so the tester could not tell which document was open (the agent had the *first draft* open while the task named the identical *second draft*). This confusion plausibly triggered the re-open behind finding #1. → **M9d**.
  3. **En/em-dash corruption.** During heavy paraphrasing the model returned control characters where dashes belonged (`2013–2017` stored as `2013␓2017`, i.e. U+2013 → U+0013; another as U+001A). En-dash and em-dash are **not** in the M9a Unicode-protection map, so they travel unprotected. → **M9d**.
- **Deferred (already logged as backlog — not re-reported):** agent edits strip run formatting (Stage 2); deeper agent-run performance beyond M9c-prep (streaming / prompt caching / focused context / parallel tool calls — see M9d §"Out of scope").
- **Decision on default-route flip (`/` → `/workspace`, card UI → `/legacy`):** **HOLD.** Closeout is blocked until the M9d fixes land and a clean re-pilot passes. Flipping the default to a UI that silently loses edits would be a regression.

See [stage1_M9d_spec.md](stage1_M9d_spec.md) for the fixes.

