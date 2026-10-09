# Stet — Pilot Testing Guide

## Introduction

Thank you for taking the time to evaluate Stet. This pilot build is designed to demonstrate Stet's core capability: parsing complex Word documents with reviewer comments, generating AI-driven revision suggestions and reviewer responses, and exporting the result with full track-change and formatting fidelity.

This guide walks you through setup and a recommended testing workflow. It should take approximately 15–20 minutes to complete.

---

## Installation & Setup (Windows)

**Prerequisites:** Windows 10 or later. No Python or other software installation is required.

1. Extract the provided archive to a folder of your choice (e.g., `C:\Stet`).
2. Locate `Stet.exe` in the extracted folder.
3. Double-click `Stet.exe` to launch. **Note:** Windows Defender SmartScreen may flag this as an unrecognised application. If prompted, click **"More info"** → **"Run anyway"**. This is expected for applications that are not yet code-signed.
4. A splash screen will appear while the application starts up. After a few seconds, the main interface will load.

**Setting your API key:**

Stet uses the OpenAI API to generate suggestions. On first launch:

1. Click **⚙️ Settings** in the top-right corner.
2. Under **LLM Provider**, select **OpenAI**.
3. Enter your OpenAI API key in the **API Key** field.
4. Select a model.
5. Click **Save**.

Your settings are stored locally and persist across sessions.

---

## Recommended Testing Workflow

### Step 1 — Upload a Document

Click **Upload Document** (or drag and drop) to load a `.docx` file. The document should:

- Contain **reviewer comments** (inserted via Word's Review → New Comment).
- Use **standard Word formatting** (bold, italic, superscript, etc.).
- Ideally include a mix of open and resolved comments.

After upload, Stet will parse the document and display all comment threads in a card-based interface.

### Step 2 — Filter for Open Comments

Use the **filter tabs** above the thread list to select **Open** comments. This hides resolved comments and focuses on the threads that need attention.

### Step 3 — Generate Suggestions

You have two options:

- **Per thread:** Click **Generate** on an individual thread card to get a suggestion for that comment only.
- **All at once:** Click **🤖 Generate & Accept All** to process all visible (filtered) threads sequentially. Each suggestion is auto-accepted before the next is generated, so later threads can see prior revisions for context.

For each thread, Stet will produce:
- A **revised text** with changes highlighted (insertions in green, deletions in red strikethrough).
- A **response to reviewer** — a draft reply to the comment.

### Step 4 — Review and Edit (Optional)

Before exporting, you can:

- **Edit the revised text** directly in the rich text editor. Formatting tools (bold, italic, underline, super/subscript) are available in the toolbar above each editor.
- **Accept or regenerate** individual suggestions using the buttons on each card.
- **Chat with the AI** for iterative refinement by expanding the "Chat with AI" section on any thread.

### Step 5 — Export

Click **Export** in the bottom-right corner. The exported `.docx` will include:

- **Stet's reply comments** threaded under the original reviewer comments.
- **Track changes** showing exactly what was revised (if the "Insert tracked changes" option is ticked).
- **All original formatting** preserved — fonts, styles, tables, figures, field codes (e.g., EndNote citations).

Open the exported file in Word and review the track changes to verify fidelity.

---

## Current Limitations

The following are known constraints of this build. They are on the development roadmap and should not be part of your testing focus.

| Area | Detail |
|------|--------|
| **Tables** | Comments on table cells are supported, but complex merged-cell layouts may not render perfectly in the UI. Export fidelity is unaffected. |
| **Images and figures** | Stet preserves images in the exported document but does not display them in the web UI. |
| **Very large documents** | Documents with 100+ comment threads will work but may take longer to process. |
| **Ollama (local AI)** | This build has been tested with the OpenAI API. Local AI via Ollama is available in Settings but has not been validated on Windows for this release. |

---

## Feedback Protocol

We value your feedback and would appreciate it structured as follows.

**Workflow and UI feedback** — general impressions of usability, clarity, and the quality of AI suggestions:

- What worked well?
- What felt unclear or required extra effort?
- How did the AI suggestions compare to what you would write manually?

**Document processing issues** — if a specific comment or paragraph doesn't process correctly:

- If company policy permits, sharing the **input `.docx`** (and the exported output, if relevant) is by far the most helpful thing you can do — it allows us to reproduce and fix the issue directly.
- If the document is confidential, a **screenshot** of the affected area in the Stet UI and/or the exported Word file is the next best thing, along with a brief description of what went wrong.

Please send feedback to Georgii directly. Even brief observations are helpful — a single sentence flagging an issue is better than a detailed report that never gets written.

---

Thank you for testing Stet. Your feedback directly shapes the product.
