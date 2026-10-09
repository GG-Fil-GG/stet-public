# Agentic Stet — Architecture Roadmap

## Vision

Stet evolves from a per-comment suggestion tool into an agentic document workspace — an AI that can read multiple files, make autonomous decisions about what to revise and how, and apply changes to `.docx` files with full track-change and formatting fidelity. Think Cursor, but for medical writing: the "files" are Word documents, style guides, and submission checklists, and the "edits" are tracked changes with XML-level precision.

The user experience mirrors Cursor's agent mode: a unified chat interface where natural-language instructions ("address the comment about methodology", "reformat the references table using the style guide") are translated into concrete document operations. The agent works autonomously, applying changes as tracked edits that the user reviews and accepts or rejects. The user can also edit the document directly.

### Design principles

- **Model-agnostic.** The agent loop must not be coupled to a specific LLM provider. Any model accessible via OpenAI-compatible API or Ollama should work. Tool schemas, prompts, and the dispatch layer must be provider-neutral.
- **Incremental.** Each stage delivers standalone value. No stage depends on completing a later stage.
- **Local-first.** The application runs on the user's machine. Documents never leave the local environment unless the user chooses a cloud LLM.

---

## Stage 1: Agentic Workspace

**Goal:** Transform Stet from a single-document card-based tool into an agentic workspace with a file sidebar, scrollable document view, unified chat, and multi-file support.

**Approach:** Define Stet's capabilities as tools, wrap them in a model-agnostic agent loop, build a new workspace UI as a separate route (`/workspace`) alongside the existing card-based UI, and add support for reading multiple file formats. The existing UI remains functional throughout development; the workspace becomes the default once ready.

### Tool definitions

Expose the following as callable tools:

| Tool | Description |
|------|-------------|
| `list_workspace_files()` | List all files in the project folder with types and sizes |
| `read_document(path)` | Parse a docx and return a summary: paragraph count, comment threads, metadata |
| `list_comments(path, filter)` | List comment threads with IDs, status, referenced text. Filterable by status (open/resolved) |
| `read_paragraph(doc, para_id)` | Return paragraph text, formatting, and any associated comments |
| `edit_paragraph(doc, para_id, new_text, track_changes)` | Apply a revision, optionally with track changes |
| `add_comment(doc, para_id, start, end, text)` | Add a new comment anchored to a text range |
| `add_comment_reply(doc, thread_id, text)` | Thread a reply under an existing comment |
| `remove_comment(doc, comment_id)` | Delete a comment and its range markers |
| `read_file(path)` | Read a reference document (PDF, XLSX, CSV, RTF, PPTX, plain text) for context |
| `export_document(doc, path)` | Serialize and export the modified docx |

These tools are thin wrappers around functions that already exist in `src/document_model/`, `src/file_parsers/`, and `src/routes/`.

### Supported file formats for `read_file`

| Format | Library | What is extracted |
|--------|---------|-------------------|
| PDF | `pdfplumber` or `PyMuPDF` | Text content, tables where detectable |
| CSV | built-in `csv` | Full tabular data |
| XLSX | `openpyxl` | Sheet names, tabular data, cell values |
| RTF | `striprtf` | Plain text content |
| PPTX | `python-pptx` | Slide text, notes |
| Plain text | built-in | Full content |

### Two editing modes

The `edit_paragraph` tool supports two modes via the `track_changes` parameter:

- **Tracked edits** (default): Revisions are wrapped in `w:ins`/`w:del` markup, visible as track changes in Word. Used for comment addressing and manuscript revision.
- **Plain edits**: Text is written directly without revision markup. Used for de novo content, drafting, and situations where track changes are not appropriate.

### Comment operations

Beyond the existing `add_comment_reply`, the agent can:

- **Add new comments** anchored to specific text ranges within a paragraph.
- **Remove comments** by deleting the `w:comment` element and its `w:commentRangeStart`/`w:commentRangeEnd` markers from the paragraph XML.

These require new serializer logic (writing comment XML), building on the existing parser's understanding of comment structure.

### Workspace concept

The workspace is a folder on disk that the user grants Stet access to. It contains:

- The manuscript(s) (`.docx`)
- Supporting files (style guides, submission checklists, reference PDFs, data tables)
- Agent session state (persisted across sessions)

The agent can browse this folder and decide which files to read for context. The user points Stet at a folder; Stet does not copy or duplicate files.

One workspace is active at a time. Switching workspaces means pointing Stet at a different folder.

### File mutation model

The agent works on an in-memory copy of the document (the `DocumentModel`). Changes are not written to disk until the user explicitly clicks **Export**. This prevents accidental overwrites and keeps the original file intact as a reference.

The export button is always visible in the UI. The agent does not export automatically.

### Natural language reference resolution

The agent must be able to resolve natural-language references to document elements:

- "Address comment #5" — resolve by comment/thread ID
- "Address the comment where the authors request a methods clarification" — resolve by searching comment text content
- "Fix the paragraph about inclusion criteria" — resolve by searching paragraph content

This is handled by the agent's reasoning over tool outputs (e.g., calling `list_comments` and matching), not by special infrastructure. It works naturally with any capable LLM.

### Agent autonomy model

The agent applies changes directly as tracked edits. The user reviews changes afterwards using the track-changes review flow: scroll through the document, see insertions and deletions, accept or reject each one. This mirrors how a human collaborator would work — they make edits in track changes, you review.

This is simpler to implement than a "propose then approve" model, and it uses infrastructure that already exists (the tracked-changes serializer).

### Agent error handling

When the agent encounters something it cannot handle (e.g., a comment it doesn't understand, a file format it can't read, an edit that fails), the default behaviour is to report the issue in the chat and skip to the next task. This can be configured to stop and ask the user for guidance before continuing.

### Undo model

Snapshot-based. The agent saves a serialized checkpoint of the `DocumentModel` (via `to_dict()`) before each action or batch of actions. The user can roll back to any checkpoint. The `DocumentModel` already supports full serialization and deserialization, so the infrastructure for this is largely in place.

### UI: workspace layout

The new workspace UI is built as a separate route (`/workspace`) alongside the existing card-based UI. The existing UI remains functional throughout development. Once the workspace is ready, it becomes the default.

```
┌──────────────────────────────────────────────────┐
│                  Stet Workspace                   │
│  ┌──────────┬────────────────────┬─────────────┐ │
│  │  File     │  Document Viewer   │   Agent     │ │
│  │  Sidebar  │  (scrolling docx)  │   Chat      │ │
│  │           │                    │             │ │
│  │  files    │  formatting        │  chat       │ │
│  │  types    │  track changes     │  actions    │ │
│  │  status   │  comments          │  history    │ │
│  └──────────┴────────────────────┴─────────────┘ │
│                        [Export]                    │
└──────────────────────────────────────────────────┘
```

**File sidebar** (left panel):

- Tree view of the workspace folder
- File type icons (docx, pdf, xlsx, csv, etc.)
- Click a docx to open it in the document viewer
- Click a reference file to show a basic preview (text content for PDFs, table for CSV/XLSX) — if effort is significant, defer non-docx previews and show docx files only initially

**Document viewer** (centre panel):

A continuous scrolling view of the active docx. This reuses and extends the existing HTML rendering from the card-based UI — the same paragraph-to-HTML conversion, just rendered sequentially in a scrollable container instead of split across cards.

The document viewer supports both reading and editing:

- **Reading:** Browse the document, see formatting, track changes, and comments.
- **Editing:** The user can click into the document and type directly, using the existing TipTap editor infrastructure (bold, italic, underline, superscript, subscript toolbar). This extends the current per-card editing to a whole-document editing experience.
- **Agent edits:** Changes made by the agent appear as tracked changes (insertions highlighted, deletions with strikethrough).

Supported formatting (all already parsed by the document model):

- Bold, italic, underline, superscript, subscript
- Text alignment (left, centre, right) — via CSS, if paragraph alignment properties are parsed
- Indentation — via CSS margins, if paragraph indent properties are parsed
- Track changes shown inline (insertions highlighted, deletions with strikethrough)
- Comments displayed alongside their anchored text

**Agent chat panel** (right panel):

- Single, unified chat interface for all instructions (comment addressing, formatting, restructuring, general questions)
- Configurable verbosity: summaries by default (e.g., "Addressing comment #3: added clarification about inclusion criteria"), with a "show details" toggle for step-by-step tracing
- The user can interrupt at any point
- Chat history persists across sessions as part of the workspace state

### What this gives us

- A proper workspace with visible file navigation
- Document-centric view instead of card-based fragments
- Both manual editing and agent-driven editing in the same view
- Multi-file context (agent reads style guides, checklists, data tables, etc.)
- Autonomous decision-making (agent decides which comments to address and how)
- Full track-change and formatting fidelity (unchanged — uses existing parser/serializer)
- Model-agnostic execution (any function-calling-capable model works)
- Snapshot-based undo for safe experimentation

### Effort estimate

Medium. Much of the rendering, editing, and parsing logic already exists. The main work is:

1. Define tool schemas (~1 day)
2. Implement model-agnostic agent loop with tool dispatch (~2–3 days)
3. Add workspace/project folder support (~1–2 days)
4. File sidebar UI (~2–3 days)
5. Document viewer — adapt existing card HTML rendering to continuous scrolling layout with TipTap editing (~3–5 days)
6. Agent chat panel with configurable verbosity (~2–3 days)
7. File format readers (PDF, XLSX, CSV, RTF, PPTX) (~2–3 days)
8. Comment write/delete serializer logic (~2 days)
9. Snapshot/checkpoint system (~1–2 days)

---

## Stage 2: MCP Server Architecture

**Goal:** Refactor the tool layer into a Model Context Protocol (MCP) server for clean separation of concerns and interoperability.

**Approach:** Package Stet's document-editing tools as an MCP server. The Stet UI becomes an MCP client, and the tools become accessible to any MCP-compatible agent.

### What changes

- The tool definitions from Stage 1 are formalised as MCP tool descriptors
- The Stet backend exposes an MCP-compatible endpoint (stdio or HTTP transport)
- The frontend communicates with tools via MCP rather than direct function calls
- The agent loop can be swapped or upgraded independently of the tool server

### What this enables

- **Interoperability.** Stet tools could be used from other MCP clients (Claude Desktop, other agent frameworks) without code changes.
- **Clean architecture.** The document-manipulation engine is fully decoupled from the UI and the agent orchestration.
- **Composability.** Other MCP tools (web search, database lookup, etc.) can be added to the agent's toolkit alongside Stet's document tools.

### Effort estimate

Medium. Primarily a refactoring exercise — the tool implementations don't change, only their interface layer. MCP server scaffolding (~2 days), tool descriptor migration (~1–2 days), client-side adaptation (~2–3 days).

---

## Stage 3: Polish and Advanced Features

**Goal:** Enhance the workspace UI with features that require genuinely new implementation work beyond what the current codebase provides.

### Tables

Render docx tables as HTML tables in the document viewer. This requires:

- Parsing table structures from the document model (rows, cells, merged cells, column widths)
- Rendering as HTML `<table>` elements with basic styling (borders, cell padding)
- Handling agent edits to table cell content

Tables are common in medical manuscripts (patient demographics, results, adverse events) and are important for the target audience.

### Figures and images

Extract embedded images from the docx zip archive and render them inline in the document viewer. Images are stored as relationships in the docx package — the parser needs to resolve the relationship ID to the binary image data and serve it as a data URI or local file.

### Accept/reject review UI

Per-change accept/reject controls in the document viewer:

- Inline buttons or a review panel next to each tracked change
- "Accept all" / "Reject all" for batch operations
- Visual feedback when a change is accepted or rejected (markup removed, text finalised)

This requires per-change granularity — the current system operates per-thread, so the review model needs to support individual tracked changes within a paragraph.

### Multi-tab document viewing

Open multiple documents simultaneously in tabs. Initially, only the primary docx is editable; reference files (PDFs, other docx) are read-only previews.

### Comment margin display

Move comments from inline display to a margin/sidebar position alongside the document text, similar to Word's comment balloons. Click or hover to expand.

### Headings

Parse heading styles (`w:pStyle` values like `Heading1`, `Heading2`) and render with appropriate HTML heading tags and styling. Enables a document outline / table of contents in the sidebar.

### Reference file previews

Show basic previews for non-docx files in the document viewer when clicked in the sidebar:

- PDF: extracted text content
- CSV/XLSX: rendered as an HTML table
- RTF/plain text: formatted text content

If this proves too complex, it can be deferred — the agent can still read these files via tools regardless of whether the user can preview them.

### Effort estimate

Medium-to-high, depending on scope. Each feature is independently deliverable:

1. Tables (~1–2 weeks)
2. Accept/reject review UI (~1–2 weeks)
3. Figures/images (~3–5 days)
4. Multi-tab (~3–5 days)
5. Comment margin display (~3–5 days)
6. Headings and document outline (~2–3 days)
7. Reference file previews (~3–5 days)

---

## De novo document creation

Deferred to post-Stage 3. When needed, the approach is template-based: maintain a small library of blank `.docx` templates (with correct styles, headers, page setup) and use the existing serializer to populate content. The agent creates a document by selecting an appropriate template and writing paragraphs into it.

This avoids having to generate Word XML boilerplate from scratch and ensures consistent formatting.

---

## Technology choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Agent loop (Stage 1) | Function calling (provider-agnostic) | Works with OpenAI, Anthropic, Ollama models; no framework lock-in |
| Lightweight framework (optional) | PydanticAI or smolagents | Zero licensing cost; can be swapped; used only for convenience |
| MCP server (Stage 2) | Python MCP SDK (MIT) | Official SDK; matches existing Python backend |
| Frontend framework | Current stack (FastAPI + HTMX + TipTap) | Already working; TipTap provides editing; HTMX handles dynamic updates |
| Desktop shell | pywebview (current) | Already working; no licensing cost |
| LLM providers | OpenAI, Anthropic, Ollama (local) | Already integrated (OpenAI + Ollama); Anthropic uses same interface pattern |
| File readers | pdfplumber, openpyxl, python-pptx, striprtf | All open-source, well-maintained, no licensing cost |

All choices are open-source or free-to-use. No licensing costs at any stage.

---

## Alternatives considered and rejected

| Path | Why rejected |
|------|-------------|
| **Cursor/VS Code plugin** | Poor fit — IDE paradigm designed for code, not documents. No native docx rendering. Cursor is proprietary. |
| **Fork open-source IDE** (Theia, Code-OSS) | Massive maintenance burden for infrastructure that doesn't serve the use case. Medical writers don't need a code editor. |
| **MS Word add-in** (Office.js) | API too limited — no field code access, no fine-grained XML control, no multi-file workspace. Sandboxed environment blocks agentic functionality. |
| **Build everything from scratch immediately** | Premature — the incremental path (Stages 1 → 2 → 3) delivers value at each step and validates assumptions before committing to the full build. |
| **LibreOffice as required dependency** | Adds ~500MB to the distributable (currently under 80MB). UNO API is complex and poorly documented. However, `libreoffice --headless` remains a potential **optional** enhancement for document rendering (DOCX → HTML conversion) and format conversion fallback — worth revisiting once the core workspace is functional. |
| **Paginated document rendering** | Docx files have no inherent pages — pagination is computed at render time by the application using font metrics, page size, and a layout engine. Reproducing this accurately in a web view is impractical and unnecessary. A continuous scrolling view provides sufficient fidelity. |
| **Auto-save to original file** | Too risky — accidental overwrites of the original manuscript. In-memory editing with explicit export is safer and matches the current workflow. |

---

## Decisions log

Decisions made during the design process, recorded for future reference.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Transition strategy | Parallel route (`/workspace`) | Keeps existing UI working during development; no broken intermediate state |
| File mutation model | In-memory, explicit export | Prevents accidental overwrites; original file is always safe |
| Agent verbosity | Configurable (summaries default, details toggle) | Traceability is important for testing and accuracy-sensitive work |
| Undo model | Snapshot-based (checkpoint before each agent action) | `DocumentModel` already supports full serialization; minimal new infrastructure |
| Project management | One workspace at a time | Simpler; switch by pointing to a different folder |
| Agent autonomy | Apply-then-review via tracked changes | Simpler implementation; uses existing tracked-changes infrastructure |
| Agent error handling | Report and skip (configurable to stop and ask) | Keeps the agent productive; user can tighten control when needed |
| Manual editing | Supported (TipTap in document viewer) | Existing editing infrastructure extends naturally to the document view |

---

## Summary

The path from current Stet to agentic Stet is incremental:

1. **Stage 1** — Build the agentic workspace: model-agnostic agent loop, file sidebar, scrollable document viewer with editing (reusing existing rendering and TipTap), unified agent chat, multi-format file readers, comment write operations, and snapshot-based undo. *Medium effort, delivers the core vision.*
2. **Stage 2** — Refactor tools into an MCP server for clean architecture and interoperability. *Medium effort, architectural payoff.*
3. **Stage 3** — Add tables, figures, per-change accept/reject, multi-tab, comment margins, headings, and reference file previews. *Medium-to-high effort, polish and completeness.*

Each stage is independently valuable and shippable. No stage requires licensing costs or abandoning prior work. The system remains model-agnostic throughout — any LLM with function calling support can drive the agent.
