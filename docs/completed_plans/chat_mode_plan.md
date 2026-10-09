# Chat Mode Implementation Plan

This document outlines the plan for implementing conversational chat mode in the Comment Addresser app, allowing users to iteratively refine LLM suggestions through back-and-forth dialogue.

---

## 1. Overview

### Problem Statement

The current "one-shot" workflow has a limitation: complex comments often require iteration. When the initial suggestion isn't quite right, users must click "Regenerate" which:
- Starts fresh, losing context of what didn't work
- May produce similar or worse results
- Doesn't allow targeted feedback like "keep this part, change that part"

### Solution

Add a **Chat Mode** that allows conversational iteration on suggestions:
- User provides feedback on what to change
- LLM adjusts the revision based on feedback
- Conversation history provides context for better iterations
- User commits the final revision when satisfied

### Workflow Comparison

**Current (One-Shot):**
```
Comment → Generate → [Accept | Regenerate | Skip]
                           ↓
                    (starts fresh, loses context)
```

**With Chat Mode:**
```
Comment → Generate → [Accept | Chat | Regenerate | Skip]
                           ↓
                    Chat Mode (iterate with feedback)
                           ↓
                    [Commit & Accept | Discard]
```

---

## 2. UI Design

### Approach: Expandable Section Below Card (Option C)

The chat interface expands inline below the card, pushing other cards down. This approach was chosen because:

1. **Comments remain visible** - User can reference the reviewer's comments while chatting
2. **Natural vertical flow** - Consistent with existing card-based layout
3. **No overlays or modals** - Keeps everything in the main content flow
4. **Context preserved** - Document text, referenced text, and existing suggestion all visible

### Wireframe

```
┌──────────────────────────────────────────────────────────────────┐
│ Thread #5                                                        │
├──────────────────────────────────────────────────────────────────┤
│ Document (60%)                  │ Comment Thread (40%)           │
│ ─────────────────────────────── │ ────────────────────────────── │
│ Context (Preceding)             │ 💬 Reviewer: "Please reorder   │
│ ...                             │    the authors alphabetically" │
│ Referenced Text                 │                                │
│ [highlighted content]           │                                │
│ Context (Following)             │                                │
│ ...                             │                                │
├──────────────────────────────────────────────────────────────────┤
│ Revised Text                    │ Response to Reviewer           │
│ [diff view / edit view]         │ [editable textarea]            │
│ ✏️ Updated via chat              │                                │
├──────────────────────────────────────────────────────────────────┤
│ [Accept] [💬 Chat] [Regenerate] [Skip]                           │
├──────────────────────────────────────────────────────────────────┤
│ 💬 CHAT MODE                                            [× Exit] │
├──────────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────────────────────┐   │
│ │ 🤖 I've generated an initial suggestion. Let me know if    │   │
│ │    you'd like any adjustments to the revision or reply.    │   │
│ │────────────────────────────────────────────────────────────│   │
│ │ 👤 Keep Maggioni as first author, but otherwise keep your  │   │
│ │    reordering.                                             │   │
│ │────────────────────────────────────────────────────────────│   │
│ │ 🤖 Done. I've moved Maggioni back to first position while  │   │
│ │    keeping the others in alphabetical order.               │   │  ← scrollable
│ │    ✏️ Revision updated                                      │   │    (max-height)
│ │────────────────────────────────────────────────────────────│   │
│ │ 👤 Perfect, but make the reply more concise.               │   │
│ │────────────────────────────────────────────────────────────│   │
│ │ 🤖 I've shortened the reply to one sentence.               │   │
│ │    ✏️ Reply updated                                         │   │
│ └────────────────────────────────────────────────────────────┘   │
│ ┌──────────────────────────────────────────────────┐ [Send]      │
│ │ Type your feedback...                            │             │
│ └──────────────────────────────────────────────────┘             │
│ [🗑️ Clear History] [× Discard]          [✓ Commit & Accept]      │
└──────────────────────────────────────────────────────────────────┘
```

### UI Specifications

| Element | Specification |
|---------|---------------|
| Chat message area | Max height: 400px, vertical scroll |
| Input textarea | 2-3 rows, expands on focus |
| Send button | Right of input, keyboard shortcut: Enter (Shift+Enter for newline) |
| Message styling | User messages: right-aligned, blue background; Assistant: left-aligned, gray background |
| Update indicators | "✏️ Revision updated" / "✏️ Reply updated" shown inline in assistant messages |
| Loading state | "🤖 Thinking..." shown while waiting for response |
| Exit button | Top-right of chat section, prompts if unsaved changes |

### Visual Indicators in Revised Text Section

When the chat updates the revision or reply:
- Brief highlight animation (fade from yellow to normal)
- Small badge: "✏️ Updated via chat" that fades after 3 seconds
- The diff view updates to show new changes

---

## 3. Data Structures

### ChatMessage

```python
@dataclass
class ChatMessage:
    """A single message in the chat history."""
    role: str  # "user", "assistant", "system"
    content: str  # The message text displayed in chat
    timestamp: str  # ISO format datetime
    revision_updated: bool = False  # True if this message updated revised_text
    reply_updated: bool = False  # True if this message updated response
```

### Session State Additions

```python
# In sessions[session_id]:
{
    # ... existing fields ...
    
    "chat_history": {
        # thread_id → list of ChatMessage
        "5": [
            ChatMessage(role="system", content="Chat started", timestamp="..."),
            ChatMessage(role="assistant", content="I've generated...", timestamp="..."),
            ChatMessage(role="user", content="Keep Maggioni first", timestamp="..."),
            ChatMessage(role="assistant", content="Done...", timestamp="...", revision_updated=True),
        ],
        "12": [...],
    },
    
    "chat_mode_active": {
        # thread_id → bool (whether chat mode is currently open)
        "5": True,
        "12": False,
    },
    
    "chat_completed": {
        # thread_id → bool (whether chat was committed - for display purposes)
        "5": False,
        "12": True,  # This thread's chat was committed
    }
}
```

### LLM Response Structure (Chat Mode)

```json
{
  "chat_response": "I've moved Maggioni back to first position while keeping the others in alphabetical order.",
  "revised_text": "Maggioni, Muiesan, Pontremoli, Corsini, Volpe",
  "response": "The author order has been updated as requested.",
  "rationale": "Moved Maggioni to first position per user request."
}
```

**Field requirements:**

| Field | Required | When to Include |
|-------|----------|-----------------|
| `chat_response` | Always | Every chat turn - this is what appears in the chat |
| `revised_text` | Optional | Only when the revision is being changed |
| `response` | Optional | Only when the reviewer reply is being changed |
| `rationale` | Optional | When explanation is helpful |

---

## 4. Backend Design

### New Endpoints

#### `POST /enter_chat/{session_id}/{thread_id}`

Enter chat mode for a thread.

**Precondition:** Thread must have an existing suggestion (cannot enter chat without generating first).

**Actions:**
1. Set `chat_mode_active[thread_id] = True`
2. Initialize `chat_history[thread_id]` if empty
3. Add system message introducing chat mode
4. Return updated card HTML with chat section visible

**Response:** HTML (HTMX swap)

---

#### `POST /chat/{session_id}/{thread_id}`

Send a message in chat mode.

**Request body:**
```json
{
  "message": "Keep Maggioni as first author"
}
```

**Actions:**
1. Add user message to `chat_history[thread_id]`
2. Build prompt with chat history and send to LLM
3. Parse LLM response
4. If `revised_text` present: update `suggestions[thread_id]["revised_text"]`
5. If `response` present: update `suggestions[thread_id]["response"]`
6. Add assistant message to `chat_history[thread_id]`
7. Save session
8. Return updated chat messages HTML + updated suggestion sections if changed

**Response:** HTML (HTMX swap for chat area, optionally trigger update for suggestion sections)

---

#### `POST /commit_chat/{session_id}/{thread_id}`

Commit the current revision and exit chat mode.

**Actions:**
1. Mark thread as accepted (same as `/accept` endpoint)
2. Store revision in `accepted_revisions`
3. Set `chat_mode_active[thread_id] = False`
4. Optionally clear chat history (or keep for reference)
5. Save session
6. Return updated card HTML (normal view, accepted state)

**Response:** HTML (HTMX swap)

---

#### `POST /discard_chat/{session_id}/{thread_id}`

Discard chat changes and exit chat mode.

**Actions:**
1. Revert `suggestions[thread_id]` to state before chat started (need to store snapshot)
2. Clear `chat_history[thread_id]`
3. Set `chat_mode_active[thread_id] = False`
4. Save session
5. Return updated card HTML (normal view, pending state with original suggestion)

**Response:** HTML (HTMX swap)

---

#### `POST /exit_chat/{session_id}/{thread_id}`

Exit chat mode without committing or discarding (keep changes, close chat panel).

**Actions:**
1. Set `chat_mode_active[thread_id] = False`
2. Keep `chat_history[thread_id]` and current suggestion intact
3. Return updated card HTML (normal view, chat can be re-opened)

**Response:** HTML (HTMX swap)

---

#### `POST /clear_chat_history/{session_id}/{thread_id}`

Clear chat history and start fresh conversation from current state.

**Actions:**
1. Clear `chat_history[thread_id]`
2. Keep current `suggestions[thread_id]` intact (revision and reply preserved)
3. Remove `chat_snapshots[thread_id]` and create new snapshot from current state
4. Add fresh system message introducing chat mode
5. Save session
6. Return updated card HTML with empty chat (ready for new conversation)

**Use case:** User wants to start a new line of discussion about the current revision without the baggage of previous conversation history.

**Response:** HTML (HTMX swap)

---

### LLM Handler Changes

#### New Method: `generate_chat_response()`

```python
def generate_chat_response(
    self,
    thread: CommentThread,
    chat_history: List[ChatMessage],
    user_message: str,
    current_revision: str,
    current_reply: str,
    paragraph_cache: List[dict],
    target_indices: Tuple[int, int],
    context_settings: dict,
    accepted_revisions: dict,
    instructions: str
) -> dict:
    """
    Generate a response in chat mode.
    
    Returns:
        dict with keys: chat_response (required), revised_text (optional), 
        response (optional), rationale (optional)
    """
```

#### Chat Mode System Prompt

The system prompt for chat mode needs to:
1. Explain the conversational context
2. Describe how responses are displayed to the user
3. Clarify when to include revisions vs. just respond

```
You are helping refine a revision to address a reviewer's comment on a scientific manuscript.

IMPORTANT: Your response will be displayed to the user in multiple places:
- "chat_response": Shown in the chat conversation area. Use this for explanations, 
  confirmations, and dialogue with the user.
- "revised_text": If included, this REPLACES the current revision shown in the 
  "Revised Text" section. Only include this if you are making changes to the text.
- "response": If included, this REPLACES the current reply shown in the 
  "Response to Reviewer" section. Only include this if you are changing the reply.

GUIDELINES:
- Always include "chat_response" with a conversational reply
- Only include "revised_text" if you are actually changing the revision
- Only include "response" if you are actually changing the reviewer reply
- If the user asks a question or requests clarification, provide only "chat_response"
- When you do update the revision or reply, briefly mention this in your chat_response 
  (e.g., "I've updated the revision to..." or "Done, I've adjusted the reply.")

CONTEXT:
[Document context, referenced text, etc.]

REVIEWER'S COMMENT:
[Original comment text]

CURRENT REVISION:
[The current revised_text]

CURRENT REPLY:
[The current response to reviewer]

CONVERSATION HISTORY:
[Previous chat messages]

USER'S MESSAGE:
[New user message]

Respond in JSON format:
{
  "chat_response": "Your conversational reply to the user",
  "revised_text": "Updated revision (only if changing)",
  "response": "Updated reply (only if changing)",
  "rationale": "Brief explanation (optional)"
}
```

---

## 5. Frontend Implementation

### New Template: `templates/partials/chat_section.html`

This template renders the expandable chat section below the card.

```html
<!-- Chat Mode Section -->
{% if chat_mode_active %}
<div id="chat-section-{{ thread.thread_id }}" class="border-t-2 border-blue-300 bg-blue-50/30">
    
    <!-- Chat Header -->
    <div class="flex items-center justify-between px-4 py-2 bg-blue-100/50 border-b border-blue-200">
        <span class="text-sm font-medium text-blue-800">💬 Chat Mode</span>
        <button hx-post="/exit_chat/{{ session_id }}/{{ thread.thread_id }}"
                hx-target="#card-{{ thread.thread_id }}"
                hx-swap="outerHTML"
                class="text-blue-600 hover:text-blue-800 text-sm">
            × Exit
        </button>
    </div>
    
    <!-- Chat Messages (scrollable) -->
    <div id="chat-messages-{{ thread.thread_id }}" 
         class="max-h-96 overflow-y-auto p-4 space-y-3">
        {% for msg in chat_history %}
        <div class="flex {% if msg.role == 'user' %}justify-end{% else %}justify-start{% endif %}">
            <div class="max-w-[80%] rounded-lg px-3 py-2 text-sm
                        {% if msg.role == 'user' %}bg-blue-600 text-white{% else %}bg-white border border-gray-200 text-gray-700{% endif %}">
                {{ msg.content }}
                {% if msg.revision_updated %}
                <div class="text-xs mt-1 {% if msg.role == 'user' %}text-blue-200{% else %}text-green-600{% endif %}">
                    ✏️ Revision updated
                </div>
                {% endif %}
                {% if msg.reply_updated %}
                <div class="text-xs mt-1 {% if msg.role == 'user' %}text-blue-200{% else %}text-green-600{% endif %}">
                    ✏️ Reply updated
                </div>
                {% endif %}
            </div>
        </div>
        {% endfor %}
        
        <!-- Loading indicator (hidden by default) -->
        <div id="chat-loading-{{ thread.thread_id }}" class="hidden justify-start">
            <div class="bg-gray-100 rounded-lg px-3 py-2 text-sm text-gray-500">
                🤖 Thinking...
            </div>
        </div>
    </div>
    
    <!-- Chat Input -->
    <div class="p-4 border-t border-blue-200 bg-white">
        <form hx-post="/chat/{{ session_id }}/{{ thread.thread_id }}"
              hx-target="#card-{{ thread.thread_id }}"
              hx-swap="outerHTML"
              hx-indicator="#chat-loading-{{ thread.thread_id }}"
              class="flex space-x-2">
            <textarea id="chat-input-{{ thread.thread_id }}"
                      name="message"
                      rows="2"
                      placeholder="Describe how you'd like the revision changed..."
                      class="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm 
                             focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-none"
                      onkeydown="handleChatKeydown(event, '{{ session_id }}', '{{ thread.thread_id }}')"></textarea>
            <button type="submit"
                    class="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg 
                           hover:bg-blue-700 transition self-end">
                Send
            </button>
        </form>
    </div>
    
    <!-- Chat Actions -->
    <div class="flex justify-between items-center px-4 py-3 bg-gray-50 border-t border-gray-200">
        <div class="flex space-x-2">
            <button hx-post="/clear_chat_history/{{ session_id }}/{{ thread.thread_id }}"
                    hx-target="#card-{{ thread.thread_id }}"
                    hx-swap="outerHTML"
                    hx-confirm="Clear chat history and start fresh? Current revision will be preserved."
                    class="px-3 py-1.5 bg-gray-100 text-gray-600 text-sm rounded hover:bg-gray-200 transition"
                    title="Clear history and start a new conversation from current state">
                🗑️ Clear History
            </button>
            <button hx-post="/discard_chat/{{ session_id }}/{{ thread.thread_id }}"
                    hx-target="#card-{{ thread.thread_id }}"
                    hx-swap="outerHTML"
                    hx-confirm="Discard all chat changes and revert to the original suggestion?"
                    class="px-3 py-1.5 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300 transition">
                × Discard Changes
            </button>
        </div>
        <button hx-post="/commit_chat/{{ session_id }}/{{ thread.thread_id }}"
                hx-target="#card-{{ thread.thread_id }}"
                hx-swap="outerHTML"
                class="px-4 py-1.5 bg-green-600 text-white text-sm font-medium rounded hover:bg-green-700 transition">
            ✓ Commit & Accept
        </button>
    </div>
</div>
{% endif %}
```

### JavaScript Additions

```javascript
// Handle Enter to send, Shift+Enter for newline
function handleChatKeydown(event, sessionId, threadId) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        // Trigger HTMX form submission
        const form = event.target.closest('form');
        if (form) {
            htmx.trigger(form, 'submit');
        }
    }
}

// Auto-scroll chat to bottom when new messages arrive
document.body.addEventListener('htmx:afterSwap', function(event) {
    const chatMessages = event.target.querySelector('[id^="chat-messages-"]');
    if (chatMessages) {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
});
```

### Modifications to `card.html`

Add "Chat" button to the action bar when a suggestion exists:

```html
<!-- In Action Bar section -->
{% if thread_status == 'pending' and suggestion %}
<!-- Has suggestion, not yet accepted -->
<button hx-post="/enter_chat/{{ session_id }}/{{ thread.thread_id }}"
        hx-target="#card-{{ thread.thread_id }}"
        hx-swap="outerHTML"
        class="px-4 py-1.5 bg-purple-600 text-white text-sm font-medium rounded hover:bg-purple-700 transition">
    💬 Chat
</button>
<!-- ... existing Accept, Regenerate, Skip buttons ... -->
{% endif %}
```

---

## 6. Token Management

### Challenge

Chat history grows with each turn, potentially exceeding context window limits.

### Strategy: Sliding Window

Keep the most recent N messages while always preserving:
- System context (document, referenced text)
- Original reviewer comment
- Current revision and reply

**Implementation:**

```python
MAX_CHAT_MESSAGES = 20  # Configurable

def build_chat_prompt(chat_history: List[ChatMessage], ...) -> str:
    # Always include recent messages
    recent_messages = chat_history[-MAX_CHAT_MESSAGES:]
    
    # If truncated, add note
    if len(chat_history) > MAX_CHAT_MESSAGES:
        truncation_note = f"[{len(chat_history) - MAX_CHAT_MESSAGES} earlier messages not shown]"
    
    # Build prompt with recent history
    ...
```

### Token Budget (GPT-5 Mini: 1M context)

| Component | Estimated Tokens |
|-----------|-----------------|
| System prompt | ~500 |
| Document context | ~2,000 |
| Current revision + reply | ~500 |
| Chat history (20 messages) | ~4,000 |
| Reserved for response | ~2,000 |
| **Total** | ~9,000 |

This leaves substantial headroom, so token limits are unlikely to be an issue for typical use.

---

## 7. Persistence

### Session File Updates

Chat history saved to `session.json`:

```json
{
  "accepted_revisions": {...},
  "context_settings": {...},
  "threads": {...},
  "chat_history": {
    "5": [
      {"role": "system", "content": "...", "timestamp": "...", "revision_updated": false, "reply_updated": false},
      {"role": "assistant", "content": "...", "timestamp": "...", "revision_updated": false, "reply_updated": false},
      {"role": "user", "content": "...", "timestamp": "...", "revision_updated": false, "reply_updated": false}
    ]
  },
  "chat_mode_active": {
    "5": true
  },
  "chat_snapshots": {
    "5": {
      "revised_text": "original revision before chat",
      "response": "original reply before chat"
    }
  }
}
```

The `chat_snapshots` field stores the state before entering chat mode, enabling "Discard" to revert properly.

---

## 8. Edge Cases

| Scenario | Behavior |
|----------|----------|
| No suggestion yet | "Chat" button disabled/hidden |
| Thread already accepted | "Chat" available - reopens existing history for continued conversation |
| Page refresh during chat | Chat history loaded from session.json, chat mode re-opened |
| Very long chat history | Apply sliding window, show count of hidden messages |
| LLM fails mid-chat | Show error message in chat, allow retry |
| Empty user message | Block submission, show validation hint |
| Commit with no changes | Allowed (commits current state) |
| Network timeout | Show error, preserve user's message for retry |
| User exits without commit | Changes preserved, can re-enter chat later |
| Clear history clicked | Preserves current revision/reply, clears messages, creates new snapshot |
| Re-enter after commit | Opens with existing history, user can continue conversation |
| Multiple threads in chat | Allowed - each operates independently |

---

## 9. Future Enhancements (Out of Scope for Initial Implementation)

| Enhancement | Description |
|-------------|-------------|
| Quick action buttons | Pre-defined prompts: "Make it shorter", "More formal", "Add citation" |
| Suggested follow-ups | LLM suggests next actions based on context |
| Voice input | Speech-to-text for chat input |
| Streaming responses | Show response as it's generated (SSE) |
| Chat export | Download chat history as markdown |
| Multiple revision tracks | Compare different revision approaches side-by-side |

---

## 10. Implementation Checklist

### Phase 1: Core Infrastructure ✅

- [x] **1.1** Add `ChatMessage` dataclass to `src/chat_types.py`
- [x] **1.2** Add chat-related fields to session state (`chat_history`, `chat_mode_active`, `chat_snapshots`, `chat_completed`)
- [x] **1.3** Update `save_session()` to persist chat data to `session.json`
- [x] **1.4** Update session loading to restore chat state

### Phase 2: Backend Endpoints ✅

- [x] **2.1** Implement `POST /enter_chat/{session_id}/{thread_id}` endpoint
- [x] **2.2** Implement `POST /chat/{session_id}/{thread_id}` endpoint
- [x] **2.3** Implement `POST /commit_chat/{session_id}/{thread_id}` endpoint
- [x] **2.4** Implement `POST /discard_chat/{session_id}/{thread_id}` endpoint
- [x] **2.5** Implement `POST /exit_chat/{session_id}/{thread_id}` endpoint
- [x] **2.6** Implement `POST /clear_chat_history/{session_id}/{thread_id}` endpoint

### Phase 3: LLM Integration ✅

- [x] **3.1** Add `generate_chat_response()` method to `LLMHandler`
- [x] **3.2** Design and implement chat mode system prompt
- [x] **3.3** Implement JSON response parsing for chat (with optional fields)
- [x] **3.4** Add sliding window logic for long chat histories (MAX_CHAT_MESSAGES = 20)

### Phase 4: Frontend ✅

- [x] **4.1** Create `templates/partials/chat_section.html` template
- [x] **4.2** Add "💬 Chat" button to card action bar in `card.html`
- [x] **4.3** Integrate chat section into card rendering (conditional on `chat_mode_active`)
- [x] **4.4** Add JavaScript for keyboard shortcuts (Enter to send, Shift+Enter for newline)
- [x] **4.5** Add JavaScript for auto-scroll on new messages
- [x] **4.6** Style chat messages (user blue, assistant white/gray, update indicators)
- [x] **4.7** Add loading indicator during LLM response (spinner + "Thinking...")
- [x] **4.8** Add visual indicator when revision/reply updated via chat

### Phase 5: Testing & Polish ✅ (Basic testing complete)

- [x] **5.1** Test basic chat flow (enter → message → commit)
- [x] **5.2** Test discard functionality (reverts to snapshot)
- [x] **5.3** Test exit and re-enter (history preserved)
- [x] **5.4** Test persistence across page refresh
- [ ] **5.5** Test with long conversations (sliding window) - pending extensive testing
- [ ] **5.6** Test error handling (LLM failure, network issues) - pending extensive testing
- [x] **5.7** Test keyboard shortcuts
- [x] **5.8** Visual polish and responsive behavior

### Phase 6: Documentation

- [ ] **6.1** Update `docs/future_improvements.md` with implementation status
- [ ] **6.2** Add chat mode section to user guide (if exists)
- [ ] **6.3** Document any new configuration options

---

## 11. Design Decisions

The following questions were resolved during planning:

### 11.1 Chat History Retention After Commit

**Decision:** Keep chat history and mark as "completed"

**Rationale:** Useful for audit trail and reference. User may want to review the conversation that led to a particular revision.

**Implementation:** Add `chat_completed` flag to session state. Completed chats are displayed in a collapsed/read-only state if user re-enters chat mode.

### 11.2 Re-entering Chat After Accept

**Decision:** Continue from where the last conversation ended

**Rationale:** User may change their mind about something and want to continue iterating without re-explaining everything.

**Additional feature:** Add a "🗑️ Clear History" button that starts fresh while preserving context (document text, referenced text, current revision/reply). This creates a new conversation from the current state.

**Implementation:**
- Re-entering chat opens with existing history intact
- "Clear History" button clears messages but keeps current revision/reply as starting point
- New endpoint: `POST /clear_chat_history/{session_id}/{thread_id}`

### 11.3 Multiple Threads in Chat Mode

**Decision:** Allow multiple threads in chat mode simultaneously

**Rationale:** No technical reason to restrict this. User may want to work on several threads in parallel.

---

## 12. Dependencies

No new external dependencies required. Uses existing:
- FastAPI + HTMX for endpoints
- Jinja2 for templating
- Existing LLM integration (OpenAI/Ollama)
- TailwindCSS for styling

---

## 13. Implementation Notes & Minor Considerations

These are minor points that may arise during implementation but don't require upfront decisions:

| Consideration | Notes |
|---------------|-------|
| **Completed chat display** | When re-entering chat on a completed thread, should history be read-only or editable? *Suggestion:* Editable - user can continue the conversation. |
| **Chat button label after commit** | Currently shows "Chat" for pending threads. For accepted threads, could show "💬 Continue Chat" or similar to indicate history exists. |
| **Empty chat history display** | After "Clear History", show a welcoming message like "Chat history cleared. The current revision has been preserved as your starting point." |
| **Scroll behavior** | On entering chat mode, auto-scroll to the chat section so it's visible. |
| **Mobile responsiveness** | Chat section should work well on smaller screens - may need to adjust max-height or layout. |

**Status:** All major design decisions have been made. The plan is ready for implementation.

---

## Changelog

### January 27, 2026 (Basic Testing Complete)
- Basic testing completed successfully
- Verified: chat flow, discard, exit/re-enter, persistence, keyboard shortcuts, visual behavior
- Remaining for extensive testing: long conversations (sliding window), error handling

### January 27, 2026 (Implementation Complete)
- Implemented Phases 1-4 (all code complete)
- Phase 5 (Testing) ready for user validation
- Files created/modified:
  - `src/chat_types.py` (new) - ChatMessage, ChatSnapshot dataclasses
  - `src/llm_handler.py` - Added generate_chat_response(), _build_chat_prompt(), _parse_chat_response()
  - `main.py` - Added 6 chat endpoints, session state management, _render_thread_card helper
  - `templates/partials/chat_section.html` (new) - Chat UI template
  - `templates/partials/card.html` - Added Chat button, included chat section

### January 27, 2026 (Update 2)
- Resolved all open questions with user decisions:
  - Chat history retained after commit, marked as "completed"
  - Re-entering chat continues from last conversation (not fresh start)
  - Multiple threads allowed in chat mode simultaneously
- Added "Clear History" feature to start fresh conversation while preserving current revision
- Added new endpoint: `POST /clear_chat_history/{session_id}/{thread_id}`
- Updated wireframe and template to include Clear History button
- Added `chat_completed` flag to session state

### January 27, 2026 (Initial)
- Initial plan created
- UI approach: Expandable section below card (Option C)
- Data structure: Optional `revised_text`/`response` fields with required `chat_response`
