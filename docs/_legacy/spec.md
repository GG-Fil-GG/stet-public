# **Comment Addresser App — Specification**

## 1. Purpose and Scope

The **Comment Addresser App** is a local, web-based application designed to streamline the process of addressing reviewer and author comments in Microsoft Word (`.docx`) manuscripts using AI.

The app focuses on **comment-by-comment revision**, preserving:

* existing Word comments and comment threads,
* existing tracked changes,
* document formatting and structure,
* and Word-native workflows.

The goal is **not** to replace Word, but to act as an intelligent, controlled assistant that:

* proposes targeted revisions,
* inserts those revisions as tracked changes,
* generates concise MW-style responses in comment threads,
* and allows the user to accept, regenerate, edit, skip, and resume work reliably.

The app is intentionally **local-first**, simple, and non-monetised in its initial form.

---

## 2. High-Level Workflow

1. User opens the app in a browser (local server).
2. User uploads a `.docx` file (drag-and-drop or file picker).
3. App parses:

   * document text and structure,
   * comments and comment threads,
   * tracked changes,
   * paragraph/run formatting.
4. App builds a **linear sequence of “comment cards”**, ordered by document position, containing only unresolved comments.
5. User processes cards one by one:

   * review AI-suggested revision,
   * optionally edit the revision,
   * accept (apply tracked changes + insert MW response),
   * regenerate,
   * or skip.
6. Progress is saved continuously.
7. At any point (or once all cards are processed), user clicks **Export final `.docx`**.

---

## 3. Supported Input and Output

### Input

* **Supported formats:** `.docx` only (hard requirement for v1).
* Documents may:

  * contain existing comments,
  * contain existing tracked changes,
  * contain complex formatting (headings, styles, tables, images).

### Output

* A `.docx` file that:

  * preserves all original formatting,
  * preserves existing tracked changes,
  * includes AI edits as **new tracked changes**,
  * includes AI-generated MW responses in comment threads.

---

## 4. Comment Cards Model

### Definition

A **comment card** represents:

* one Word comment or a full comment thread,
* the paragraph associated with that comment,
* the proposed revision,
* and the actions applicable to that comment.

### Ordering

* Cards are ordered by **document position**, not by comment ID.
* Only **unresolved** comments are included by default.
* Skipped comments remain in the sequence and are visually marked.

### Navigation

* Strictly linear navigation:

  * `Previous` / `Next` buttons.
  * Status indicator: e.g. `Comment 12 of 37 (skipped)`.

---

## 5. Document View

* The main pane shows the **entire manuscript text** in a stripped-down, read-only format.
* Only the **active paragraph** is displayed with inline diff (tracked-change-style highlighting).
* All other paragraphs are shown as plain text.
* The active paragraph is automatically scrolled into view.
* No in-document interaction (clicking comments, editing outside the active paragraph) in v1.

---

## 6. Revision Granularity and Context

### Target Unit

* The **paragraph containing the commented text** is the primary unit of revision.

### Context Expansion

* If the paragraph is below a configurable size threshold:

  * surrounding context may be included *for the LLM only*.
* The editable unit remains the paragraph.

This ensures:

* predictable scope,
* low reconciliation complexity,
* and minimal unintended changes.

---

## 7. AI Interaction Model

### LLM Abstraction

The app uses an abstract **LLM provider interface**, allowing:

* cloud APIs (e.g. OpenAI),
* local LLM servers (e.g. Ollama),
  to be swapped via configuration.

### Context Modes (configurable, developer-facing)

* **Full-context mode:** entire manuscript + all comments + current comment.
* **Summary mode:** compact global summary + local paragraph + comment.

These modes are **not exposed in the main UI** and are controlled via config.

### Per-Comment AI Output

For each card, the AI returns:

* revised paragraph text,
* concise MW response text (for comment thread),
* optional rationale (used internally or shown in UI).

---

## 8. Editing and Acceptance

### In-App Editing

* User can manually edit the proposed revised paragraph:

  * plain text only,
  * no formatting controls.
* Edited text becomes the final accepted version for that card.

### Accept

On **Accept**:

1. App inserts tracked changes into the `.docx`:

   * original text wrapped in deletion markup,
   * revised text wrapped in insertion markup,
   * formatting inherited from the original paragraph/runs.
2. App inserts an AI-generated reply into the comment thread:

   * prefixed with a clear marker (e.g. `MW response:`).
3. Card status is marked as `done`.

### Regenerate

* Same card remains active.
* A new AI suggestion is requested using current document state.

---

## 9. Skipping and State Tracking

### Skipping

* Skipped cards:

  * remain in the main sequence,
  * are clearly marked as `skipped`,
  * do not insert MW responses or text changes.

### State Persistence

* Progress is stored in a **sidecar JSON file** (per manuscript), tracking:

  * comment IDs,
  * status: `pending`, `done`, `skipped`.
* Word comments are **not** used as the canonical workflow state.
* The `.docx` remains human-facing; the JSON remains app-facing.

---

## 10. Tracked Changes Handling

* Existing tracked changes are preserved.
* AI edits are inserted as **new tracked changes**, attributed to a consistent author name (e.g. “AI MW”).
* No flattening or accepting of existing tracked changes occurs automatically.
* Word remains the final arbiter of accepting/rejecting changes.

---

## 11. Export

* A persistent **“Export final .docx”** button is available.
* Export writes:

  * current document state,
  * all applied tracked changes,
  * all inserted MW responses.
* Export is allowed even if some comments are skipped.

---

## 12. Architecture Overview

### Backend

* Python backend (e.g. FastAPI or Flask).
* Responsibilities:

  * `.docx` parsing and patching (XML-level),
  * comment extraction and mapping,
  * tracked change insertion,
  * LLM orchestration,
  * session/state management.

### Frontend

* Minimal HTML + JS.
* Responsibilities:

  * file upload,
  * card navigation,
  * inline diff display,
  * simple text editing,
  * action buttons.

No heavy frontend framework is required for v1.

---

## 13. Assumptions and Non-Goals (v1)

### Assumptions

* User is comfortable working with tracked changes in Word.
* Manuscripts are edited by one primary user per session.
* `.docx` structure follows standard Word conventions.

### Explicit Non-Goals (v1)

* Multi-user collaboration.
* Real-time Word rendering fidelity.
* Support for `.doc`, `.rtf`, `.pdf`.
* Fully automated “address all comments” mode.
* Advanced analytics or dashboards.

---

## 14. Future Extensions (Out of Scope for v1)

* Comment filtering and jumping.
* Rich diff visualisation modes.
* Section-level or multi-paragraph revisions.
* Integrated prompt editing UI.
* Automatic consistency checks across the manuscript.