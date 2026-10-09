# Development Notes

Technical notes and future improvement ideas for the Comment Addresser project.

---

## Performance Optimization Ideas

### LLM Suggestion Generation Speed

**Current behavior:** Each "Generate Suggestion" click takes 2-5 seconds. This is acceptable for the MVP but could be improved.

**Why it's slow:**
1. **Document re-parsing:** Each generation re-opens the .docx to extract paragraph context
2. **Context extraction:** Building surrounding paragraph context requires XML traversal
3. **API round-trip:** OpenAI API latency is typically 1-3 seconds
4. **Response parsing:** Parsing the structured response (revised text + response + rationale)

### Recommended Optimizations (Future)

#### 1. Cache the Paragraph Map (High Impact, Medium Effort)

Currently, `LLMHandler._get_expanded_context()` re-parses the document every time. Instead:

```python
# In app.py, cache after document load
if 'paragraph_cache' not in st.session_state:
    st.session_state.paragraph_cache = build_paragraph_cache(docx_path)

# Pass cache to LLMHandler
handler = LLMHandler(
    provider=...,
    docx_path=...,
    paragraph_cache=st.session_state.paragraph_cache  # New parameter
)
```

**Estimated improvement:** 0.5-1 second per generation

#### 2. Streaming Responses (High Impact, Medium Effort)

Show the LLM output as it generates, rather than waiting for completion:

```python
# OpenAI supports streaming
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    stream=True  # Enable streaming
)

for chunk in response:
    # Update UI progressively
    yield chunk.choices[0].delta.content
```

**Estimated improvement:** Perceived latency drops significantly (user sees text appearing immediately)

#### 3. Pre-fetch Next Thread (Low Priority)

While user reviews current suggestion, pre-generate the next thread's context in the background. Not critical for linear workflow.

---

## Known Issues & Workarounds

### Word Field Codes (Fixed 2025-01-01)

**Issue:** Some comments contained raw field code instructions like `PAGE \# "'Page: '#'"` instead of rendered values.

**Fix:** Modified `_extract_text_from_element()` to skip `w:instrText` and properly handle `w:fldSimple` elements.

### Sentence Boundary Detection (Fixed 2025-01-01)

**Issue:** Context extraction was including the last word of the *previous* sentence (e.g., "failure. For patients..." instead of "For patients...").

**Fix:** Changed sentence boundary logic to set `sentence_start = j` (first char of new sentence) instead of `word_start` (last word of previous sentence).

---

## Architecture Notes

### File Storage Structure

```
output/
└── {document_slug}/
    ├── comments.json      # Full extraction (from extractor)
    ├── comments.txt       # Human-readable version
    ├── session.json       # UI state (statuses, accepted text)
    └── llm/
        └── thread_{id}.json  # Individual accepted suggestions
```

### Session Persistence

The app saves progress to `session.json` on every Accept/Skip action. This allows:
- Resuming work after crashes
- Reviewing past decisions
- Exporting accepted revisions for manual editing

---

## Future Features (Post-MVP)

- [ ] Batch export of all accepted revisions as a single document
- [ ] Diff view showing original vs revised text
- [ ] Integration with Word's Track Changes (risky XML manipulation)
- [ ] Multi-document session management
- [ ] LLM prompt customization in UI

