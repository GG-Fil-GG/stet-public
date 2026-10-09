"""
ARCHIVED: Streamlit version of Comment Addresser (now called "Stet")

This file was archived on 2026-01-24 as part of codebase cleanup.
The application has migrated to FastAPI + HTMX (see main.py).

This file is kept for reference only. Do not use in production.
To run: pip install streamlit && streamlit run _archive/app_streamlit.py

Original description:
Comment Addresser Workbench - Streamlit App
A tool for addressing reviewer comments in Word manuscripts using AI.
"""

import streamlit as st
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime

# Add project root to path
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.comment_extractor import CommentExtractor
from src.llm_handler import LLMHandler, LLMSuggestion
from src.output_manager import get_output_dir, save_llm_suggestion
from src.docx_writer import DocxWriter, create_modified_docx
from src.diff_utils import compute_diff, diff_to_html

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="Comment Addresser",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =============================================================================
# SESSION STATE INITIALIZATION
# =============================================================================

def init_session_state():
    """Initialize session state variables."""
    if 'threads' not in st.session_state:
        st.session_state.threads = []
    if 'current_index' not in st.session_state:
        st.session_state.current_index = 0
    if 'docx_path' not in st.session_state:
        st.session_state.docx_path = None
    if 'original_filename' not in st.session_state:
        st.session_state.original_filename = None
    if 'thread_statuses' not in st.session_state:
        st.session_state.thread_statuses = {}  # {thread_id: "pending" | "done" | "skipped"}
    if 'suggestions' not in st.session_state:
        st.session_state.suggestions = {}  # {thread_id: {"revised_text": ..., "response": ...}}
    if 'show_resolved' not in st.session_state:
        st.session_state.show_resolved = False
    if 'provider' not in st.session_state:
        st.session_state.provider = "openai"
    if 'reply_author' not in st.session_state:
        st.session_state.reply_author = "Author"
    if 'generation_counter' not in st.session_state:
        st.session_state.generation_counter = {}  # {thread_id: counter} to force widget refresh
    if 'insert_tracked_changes' not in st.session_state:
        st.session_state.insert_tracked_changes = False  # Opt-in for tracked changes insertion
    if 'accepted_revisions' not in st.session_state:
        st.session_state.accepted_revisions = {}  # {para_id: revised_text} for virtual state
    if 'citation_maps' not in st.session_state:
        st.session_state.citation_maps = {}  # {thread_id: {marker: original_text}} for citation restoration
    # Expandable context support
    if 'paragraph_cache' not in st.session_state:
        st.session_state.paragraph_cache = []  # [{idx, para_id, text}, ...]
    if 'thread_target_indices' not in st.session_state:
        st.session_state.thread_target_indices = {}  # {thread_id: (start_idx, end_idx)}
    if 'context_settings' not in st.session_state:
        st.session_state.context_settings = {}  # {thread_id: {before_count, after_count}}


def get_output_path() -> str:
    """Get the path to use for output operations (original filename)."""
    return st.session_state.get('original_filename', st.session_state.get('docx_path', ''))


def get_session_file_path() -> Path:
    """Get the path for the session file."""
    output_path = get_output_path()
    if not output_path:
        return None
    output_dir = get_output_dir(output_path)
    return output_dir / "session.json"


def save_session():
    """Save current session state to JSON file."""
    output_path = get_output_path()
    if not output_path:
        return
    
    session_data = {
        "document": os.path.basename(output_path),
        "saved_at": datetime.now().isoformat(),
        "current_index": st.session_state.current_index,
        "threads": {},
        "accepted_revisions": st.session_state.get("accepted_revisions", {}),  # Virtual state
        "context_settings": st.session_state.get("context_settings", {})  # Per-thread context settings
    }
    
    for thread_id, status in st.session_state.thread_statuses.items():
        thread_data = {"status": status}
        if thread_id in st.session_state.suggestions:
            thread_data.update(st.session_state.suggestions[thread_id])
        session_data["threads"][thread_id] = thread_data
    
    session_file = get_session_file_path()
    if session_file:
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)


def load_session(output_path: str) -> bool:
    """Load session state from JSON file. Returns True if loaded."""
    output_dir = get_output_dir(output_path)
    session_file = output_dir / "session.json"
    
    if not session_file.exists():
        return False
    
    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
        
        st.session_state.current_index = session_data.get("current_index", 0)
        
        # Restore virtual state (accepted_revisions)
        st.session_state.accepted_revisions = session_data.get("accepted_revisions", {})
        
        # Restore per-thread context settings
        st.session_state.context_settings = session_data.get("context_settings", {})
        
        for thread_id, thread_data in session_data.get("threads", {}).items():
            st.session_state.thread_statuses[thread_id] = thread_data.get("status", "pending")
            if "revised_text" in thread_data:
                st.session_state.suggestions[thread_id] = {
                    "revised_text": thread_data.get("revised_text", ""),
                    "response": thread_data.get("response", ""),
                    "rationale": thread_data.get("rationale"),
                    "target_para_id": thread_data.get("target_para_id")  # Also restore para_id
                }
        
        return True
    except Exception as e:
        st.warning(f"Could not load previous session: {e}")
        return False


# =============================================================================
# SIDEBAR
# =============================================================================

def render_sidebar():
    """Render the sidebar with file upload and settings."""
    with st.sidebar:
        st.header("📂 Document")
        
        # File upload
        uploaded_file = st.file_uploader(
            "Upload a .docx file",
            type=["docx"],
            help="Select a Word document with comments"
        )
        
        if uploaded_file:
            # Save to temp file and process
            # Use the original filename for output organization
            if 'original_filename' not in st.session_state or st.session_state.original_filename != uploaded_file.name:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name
                
                st.session_state.docx_path = tmp_path
                st.session_state.original_filename = uploaded_file.name
                load_document(tmp_path, uploaded_file.name)
        
        st.divider()
        
        # LLM Settings
        st.header("🤖 AI Settings")
        
        provider = st.radio(
            "Provider",
            options=["openai", "ollama"],
            index=0 if st.session_state.provider == "openai" else 1,
            horizontal=True
        )
        st.session_state.provider = provider
        
        model_display = "GPT-5 mini" if provider == "openai" else "Llama 3"
        st.caption(f"Model: {model_display}")
        
        st.divider()
        
        # Filters
        st.header("🔍 Filters")
        
        show_resolved = st.checkbox(
            "Show resolved threads",
            value=st.session_state.show_resolved
        )
        st.session_state.show_resolved = show_resolved
        
        # Stats
        if st.session_state.threads:
            st.divider()
            st.header("📊 Progress")
            
            total = len(get_filtered_threads())
            done = sum(1 for t in get_filtered_threads() 
                      if st.session_state.thread_statuses.get(t.thread_id) == "done")
            skipped = sum(1 for t in get_filtered_threads() 
                         if st.session_state.thread_statuses.get(t.thread_id) == "skipped")
            pending = total - done - skipped
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Done", done)
            col2.metric("Skipped", skipped)
            col3.metric("Pending", pending)
            
            if total > 0:
                progress = (done + skipped) / total
                st.progress(progress, text=f"{int(progress*100)}% processed")
            
            # Export section
            if done > 0:
                st.divider()
                st.header("📤 Export")
                
                # Author name for replies
                author_name = st.text_input(
                    "Reply author name",
                    value=st.session_state.reply_author,
                    help="Name that will appear as author of replies in Word"
                )
                st.session_state.reply_author = author_name
                
                # Track changes toggle (opt-in)
                insert_tracked = st.checkbox(
                    "Insert revisions as tracked changes",
                    value=st.session_state.get('insert_tracked_changes', False),
                    help="⚠️ Experimental: Insert AI-suggested revisions directly into the document as Word track changes"
                )
                st.session_state.insert_tracked_changes = insert_tracked
                
                if insert_tracked:
                    st.caption("⚠️ Track changes insertion is experimental. Some paragraphs may be skipped if they contain tables, existing track changes, or complex formatting.")
                
                # Export button
                if st.button("🚀 Export with Replies", type="primary", use_container_width=True):
                    export_document()


def export_document():
    """Export document with replies inserted for accepted threads."""
    # Check if tracked changes should be inserted
    insert_tracked_changes = st.session_state.get('insert_tracked_changes', False)
    
    # Collect accepted threads data
    accepted_threads = []
    for thread in st.session_state.threads:
        if st.session_state.thread_statuses.get(thread.thread_id) == "done":
            suggestion = st.session_state.suggestions.get(thread.thread_id)
            if suggestion:
                # Get the LAST comment in thread (so reply appears at end of conversation)
                last_comment = thread.comments[-1]
                accepted_threads.append({
                    'thread': thread,
                    'suggestion': suggestion,
                    'last_comment': last_comment
                })
    
    if not accepted_threads:
        st.warning("No accepted suggestions to export")
        return
    
    # Create output path
    original_name = st.session_state.original_filename or "document.docx"
    base_name = original_name.rsplit('.', 1)[0]
    output_name = f"{base_name}_with_replies.docx"
    
    # Get output directory
    output_dir = get_output_dir(st.session_state.original_filename)
    output_path = os.path.join(output_dir, output_name)
    
    # Create writer
    writer = DocxWriter(st.session_state.docx_path, st.session_state.reply_author)
    
    # Copy document
    writer.copy_docx(output_path)
    
    # Track results
    tracked_changes_success = 0
    tracked_changes_skipped = 0
    tracked_changes_errors = []
    replies_success = 0
    replies_failed = 0
    
    progress_text = "Inserting revisions..." if insert_tracked_changes else "Inserting replies..."
    with st.spinner(progress_text):
        try:
            # Step 1: Insert tracked changes (if enabled)
            if insert_tracked_changes:
                for item in accepted_threads:
                    thread = item['thread']
                    suggestion = item['suggestion']
                    revised_text = suggestion.get('revised_text', '')
                    
                    if revised_text and thread.referenced_text:
                        success, message = writer.insert_tracked_change(
                            docx_path=output_path,
                            thread_id=thread.thread_id,
                            original_text=thread.referenced_text,
                            revised_text=revised_text,
                            author=st.session_state.reply_author
                        )
                        
                        if success:
                            tracked_changes_success += 1
                        else:
                            tracked_changes_skipped += 1
                            tracked_changes_errors.append(f"Thread {thread.thread_id}: {message}")
            
            # Step 2: Insert reply comments (always)
            for item in accepted_threads:
                suggestion = item['suggestion']
                last_comment = item['last_comment']
                reply_text = suggestion.get('response', '')
                
                if reply_text:
                    success, message = writer.add_reply(
                        docx_path=output_path,
                        parent_comment_id=last_comment.id,
                        parent_para_id=last_comment.para_id,
                        reply_text=reply_text,
                        author=st.session_state.reply_author
                    )
                    
                    if success:
                        replies_success += 1
                    else:
                        replies_failed += 1
            
            # Show results
            if insert_tracked_changes:
                if tracked_changes_success > 0:
                    st.success(f"✅ Inserted {tracked_changes_success} tracked changes")
                if tracked_changes_skipped > 0:
                    with st.expander(f"⚠️ {tracked_changes_skipped} tracked changes skipped (click for details)"):
                        for error in tracked_changes_errors:
                            st.caption(error)
            
            if replies_success > 0:
                st.success(f"✅ Added {replies_success} reply comments")
            if replies_failed > 0:
                st.warning(f"⚠️ {replies_failed} replies failed to insert")
            
            # Provide download button
            with open(output_path, 'rb') as f:
                st.download_button(
                    label="⬇️ Download Modified Document",
                    data=f.read(),
                    file_name=output_name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
                
        except Exception as e:
            st.error(f"Export failed: {e}")


def load_document(docx_path: str, original_filename: str = None):
    """Load and extract comments from a document."""
    # Use original filename for output paths if provided
    output_path = original_filename if original_filename else docx_path
    
    with st.spinner("Extracting comments..."):
        try:
            extractor = CommentExtractor(docx_path)
            # Exclude invisible comments:
            # - Orphaned: no anchor in document.xml
            # - On deleted text: attached to track-changes deletions (invisible when deletions hidden)
            all_threads = extractor.extract(
                include_resolved=True, 
                include_orphaned=False,
                include_on_deleted_text=False
            )
            st.session_state.threads = all_threads
            st.session_state.current_index = 0
            st.session_state.thread_statuses = {}
            st.session_state.suggestions = {}
            st.session_state.accepted_revisions = {}  # Reset virtual state for new document
            
            # Cache paragraphs and thread target indices for expandable context
            st.session_state.paragraph_cache = extractor.get_paragraph_cache()
            st.session_state.thread_target_indices = extractor.get_thread_target_indices(all_threads)
            st.session_state.context_settings = {}  # Reset context settings for new document
            
            # Try to load previous session using original filename
            if load_session(output_path):
                st.success("Loaded previous session!")
            
            # Initialize statuses for new threads
            for t in all_threads:
                if t.thread_id not in st.session_state.thread_statuses:
                    st.session_state.thread_statuses[t.thread_id] = "pending"
            
            st.success(f"Loaded {len(all_threads)} comment threads")
        except Exception as e:
            st.error(f"Error loading document: {e}")


def get_filtered_threads():
    """Get threads based on current filter settings."""
    threads = st.session_state.threads
    if not st.session_state.show_resolved:
        threads = [t for t in threads if not t.is_resolved]
    return threads


# =============================================================================
# EXPANDABLE CONTEXT HELPERS
# =============================================================================

DEFAULT_CONTEXT_BEFORE = 2
DEFAULT_CONTEXT_AFTER = 2


def get_context_settings(thread_id: str) -> dict:
    """Get or initialize context settings for a thread."""
    if thread_id not in st.session_state.context_settings:
        st.session_state.context_settings[thread_id] = {
            'before_count': DEFAULT_CONTEXT_BEFORE,
            'after_count': DEFAULT_CONTEXT_AFTER,
            'ref_start_offset': 0,  # Negative = expand up, takes from before
            'ref_end_offset': 0,    # Positive = expand down, takes from after
        }
    # Ensure new fields exist for existing sessions
    settings = st.session_state.context_settings[thread_id]
    if 'ref_start_offset' not in settings:
        settings['ref_start_offset'] = 0
    if 'ref_end_offset' not in settings:
        settings['ref_end_offset'] = 0
    return settings


def update_context_setting(thread_id: str, key: str, delta: int):
    """Update a context setting by delta, with appropriate constraints."""
    settings = get_context_settings(thread_id)
    
    if key in ('before_count', 'after_count'):
        # Context counts must be non-negative
        new_value = max(0, settings[key] + delta)
    elif key == 'ref_start_offset':
        # ref_start_offset: negative = expand up, 0 = default, can't go positive
        new_value = min(0, settings[key] + delta)
    elif key == 'ref_end_offset':
        # ref_end_offset: positive = expand down, 0 = default, can't go negative
        new_value = max(0, settings[key] + delta)
    else:
        new_value = settings[key] + delta
    
    settings[key] = new_value


def get_context_paragraphs(thread_id: str) -> dict:
    """
    Get paragraphs for display based on context settings.
    
    Returns:
        {
            'before': [{'idx': i, 'para_id': p, 'text': t}, ...],
            'target': [{'idx': i, 'para_id': p, 'text': t}, ...],  # Referenced paragraphs (may be expanded)
            'after': [{'idx': i, 'para_id': p, 'text': t}, ...],
            'anchor_start': int,  # Original anchor start index
            'anchor_end': int,    # Original anchor end index
        }
    """
    result = {'before': [], 'target': [], 'after': [], 'anchor_start': 0, 'anchor_end': 0}
    
    para_cache = st.session_state.paragraph_cache
    target_indices = st.session_state.thread_target_indices
    settings = get_context_settings(thread_id)
    accepted_revisions = st.session_state.accepted_revisions
    
    if not para_cache or thread_id not in target_indices:
        return result
    
    # Original anchor span (from comment markers)
    anchor_start, anchor_end = target_indices[thread_id]
    result['anchor_start'] = anchor_start
    result['anchor_end'] = anchor_end
    
    # Expanded target span (with ref offsets)
    # ref_start_offset is negative when expanded up, ref_end_offset is positive when expanded down
    ref_start_offset = settings.get('ref_start_offset', 0)
    ref_end_offset = settings.get('ref_end_offset', 0)
    
    expanded_start = max(0, anchor_start + ref_start_offset)  # ref_start_offset is negative
    expanded_end = min(len(para_cache) - 1, anchor_end + ref_end_offset)
    
    before_count = settings['before_count']
    after_count = settings['after_count']
    
    # Get paragraphs before (applying virtual state)
    # Context before starts from expanded_start
    before_start = max(0, expanded_start - before_count)
    for i in range(before_start, expanded_start):
        para = para_cache[i].copy()
        # Apply virtual state if this paragraph was revised
        if para['para_id'] and para['para_id'] in accepted_revisions:
            para['text'] = accepted_revisions[para['para_id']]
            para['is_revised'] = True
        else:
            para['is_revised'] = False
        result['before'].append(para)
    
    # Get target paragraphs (expanded range, applying virtual state)
    for i in range(expanded_start, expanded_end + 1):
        para = para_cache[i].copy()
        if para['para_id'] and para['para_id'] in accepted_revisions:
            para['text'] = accepted_revisions[para['para_id']]
            para['is_revised'] = True
        else:
            para['is_revised'] = False
        # Mark if this paragraph is part of the original anchor or expanded
        para['is_anchor'] = (anchor_start <= i <= anchor_end)
        result['target'].append(para)
    
    # Get paragraphs after (applying virtual state)
    # Context after starts from expanded_end
    after_end = min(len(para_cache), expanded_end + 1 + after_count)
    for i in range(expanded_end + 1, after_end):
        para = para_cache[i].copy()
        if para['para_id'] and para['para_id'] in accepted_revisions:
            para['text'] = accepted_revisions[para['para_id']]
            para['is_revised'] = True
        else:
            para['is_revised'] = False
        result['after'].append(para)
    
    return result


def can_expand_before(thread_id: str) -> bool:
    """Check if we can expand context before (not at start of document)."""
    target_indices = st.session_state.thread_target_indices
    settings = get_context_settings(thread_id)
    
    if thread_id not in target_indices:
        return False
    
    anchor_start, _ = target_indices[thread_id]
    ref_start_offset = settings.get('ref_start_offset', 0)
    expanded_start = anchor_start + ref_start_offset  # ref_start_offset is negative when expanded
    current_before = settings['before_count']
    return expanded_start - current_before > 0


def can_expand_after(thread_id: str) -> bool:
    """Check if we can expand context after (not at end of document)."""
    para_cache = st.session_state.paragraph_cache
    target_indices = st.session_state.thread_target_indices
    settings = get_context_settings(thread_id)
    
    if thread_id not in target_indices or not para_cache:
        return False
    
    _, anchor_end = target_indices[thread_id]
    ref_end_offset = settings.get('ref_end_offset', 0)
    expanded_end = anchor_end + ref_end_offset
    current_after = settings['after_count']
    return expanded_end + 1 + current_after < len(para_cache)


# --- Referenced Text expansion/contraction helpers ---

def can_expand_ref_up(thread_id: str) -> bool:
    """Check if we can expand Referenced Text upward (take from Context Preceding)."""
    target_indices = st.session_state.thread_target_indices
    settings = get_context_settings(thread_id)
    
    if thread_id not in target_indices:
        return False
    
    anchor_start, _ = target_indices[thread_id]
    ref_start_offset = settings.get('ref_start_offset', 0)
    expanded_start = anchor_start + ref_start_offset
    # Can expand up if there's still room above
    return expanded_start > 0


def can_contract_ref_up(thread_id: str) -> bool:
    """Check if we can contract Referenced Text from above (return to Context Preceding)."""
    settings = get_context_settings(thread_id)
    ref_start_offset = settings.get('ref_start_offset', 0)
    # Can contract if we've expanded (offset is negative)
    return ref_start_offset < 0


def can_expand_ref_down(thread_id: str) -> bool:
    """Check if we can expand Referenced Text downward (take from Context Following)."""
    para_cache = st.session_state.paragraph_cache
    target_indices = st.session_state.thread_target_indices
    settings = get_context_settings(thread_id)
    
    if thread_id not in target_indices or not para_cache:
        return False
    
    _, anchor_end = target_indices[thread_id]
    ref_end_offset = settings.get('ref_end_offset', 0)
    expanded_end = anchor_end + ref_end_offset
    # Can expand down if there's still room below
    return expanded_end < len(para_cache) - 1


def can_contract_ref_down(thread_id: str) -> bool:
    """Check if we can contract Referenced Text from below (return to Context Following)."""
    settings = get_context_settings(thread_id)
    ref_end_offset = settings.get('ref_end_offset', 0)
    # Can contract if we've expanded (offset is positive)
    return ref_end_offset > 0


# =============================================================================
# MAIN CONTENT
# =============================================================================

def render_main():
    """Render the main content area."""
    st.title("📝 Comment Addresser Workbench")
    
    if not st.session_state.threads:
        st.info("👈 Upload a .docx file to get started")
        return
    
    threads = get_filtered_threads()
    
    if not threads:
        st.warning("No threads to display. Try enabling 'Show resolved threads' in the sidebar.")
        return
    
    # Ensure current index is valid
    if st.session_state.current_index >= len(threads):
        st.session_state.current_index = len(threads) - 1
    if st.session_state.current_index < 0:
        st.session_state.current_index = 0
    
    current_thread = threads[st.session_state.current_index]
    
    # Navigation
    render_navigation(threads)
    
    st.divider()
    
    # Thread card
    render_thread_card(current_thread)


def render_navigation(threads):
    """Render the navigation controls."""
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("◀ Previous", use_container_width=True, 
                    disabled=st.session_state.current_index == 0):
            st.session_state.current_index -= 1
            st.rerun()
    
    with col2:
        current = st.session_state.current_index + 1
        total = len(threads)
        thread = threads[st.session_state.current_index]
        status = st.session_state.thread_statuses.get(thread.thread_id, "pending")
        
        status_emoji = {"pending": "⏳", "done": "✅", "skipped": "⏭️"}.get(status, "")
        resolved_tag = " [RESOLVED]" if thread.is_resolved else ""
        
        st.markdown(
            f"<h3 style='text-align: center;'>{status_emoji} Thread {current} of {total}{resolved_tag}</h3>",
            unsafe_allow_html=True
        )
    
    with col3:
        if st.button("Next ▶", use_container_width=True,
                    disabled=st.session_state.current_index >= len(threads) - 1):
            st.session_state.current_index += 1
            st.rerun()


def render_thread_card(thread):
    """Render a single thread card."""
    thread_id = thread.thread_id
    
    # Section
    if thread.section:
        section_parts = thread.section.split(' / ')
        section_display = ' → '.join(section_parts[:3])  # Limit depth
        st.caption(f"📍 {section_display}")
    
    # Expandable context sections
    import html as html_module
    thread_id = thread.thread_id
    context_data = get_context_paragraphs(thread_id)
    settings = get_context_settings(thread_id)
    
    # --- Context (Preceding) Section ---
    # Always show header and buttons (even when context is 0) so user can expand
    with st.container():
        # Header row with title and buttons using fixed-width button columns
        col_title, col_plus, col_minus = st.columns([10, 1, 1], gap="small")
        with col_title:
            st.markdown("**Context (Preceding)**")
        with col_plus:
            if st.button("[+]", key=f"ctx_before_plus_{thread_id}",
                       disabled=not can_expand_before(thread_id),
                       help="Add one paragraph to context",
                       use_container_width=True):
                update_context_setting(thread_id, 'before_count', 1)
                st.rerun()
        with col_minus:
            if st.button("[−]", key=f"ctx_before_minus_{thread_id}", 
                       disabled=settings['before_count'] == 0,
                       help="Remove one paragraph from context",
                       use_container_width=True):
                update_context_setting(thread_id, 'before_count', -1)
                st.rerun()
        
        # Display preceding paragraphs (or message if none)
        if context_data['before']:
            for para in context_data['before']:
                text_escaped = html_module.escape(para['text']).replace('\n', '<br>')
                # Visual indicator if paragraph was revised earlier this session
                revised_indicator = ' <span style="color: #28a745; font-size: 0.8em;">(edited earlier)</span>' if para.get('is_revised') else ''
                st.markdown(
                    f'<div style="padding: 0.5rem 1rem; background-color: #f0f0f0; border-left: 2px solid #9e9e9e; '
                    f'border-radius: 2px; margin-bottom: 4px; font-family: inherit; line-height: 1.5; color: #555;">'
                    f'{text_escaped}{revised_indicator}</div>',
                    unsafe_allow_html=True
                )
        elif settings['before_count'] == 0:
            st.caption("*No context (click ➕ to add)*")
        else:
            st.caption("*Start of document*")
    
    # --- Referenced Text Section ---
    with st.container():
        # Header row with title and 4 directional buttons
        col_title, col_up_plus, col_up_minus, col_down_plus, col_down_minus = st.columns([10, 1, 1, 1, 1], gap="small")
        with col_title:
            st.markdown("**Referenced Text:**")
        with col_up_plus:
            if st.button("[↑+]", key=f"ref_up_plus_{thread_id}",
                       disabled=not can_expand_ref_up(thread_id),
                       help="Add paragraph above",
                       use_container_width=True):
                update_context_setting(thread_id, 'ref_start_offset', -1)
                st.rerun()
        with col_up_minus:
            if st.button("[↑−]", key=f"ref_up_minus_{thread_id}",
                       disabled=not can_contract_ref_up(thread_id),
                       help="Remove paragraph above",
                       use_container_width=True):
                update_context_setting(thread_id, 'ref_start_offset', 1)
                st.rerun()
        with col_down_plus:
            if st.button("[↓+]", key=f"ref_down_plus_{thread_id}",
                       disabled=not can_expand_ref_down(thread_id),
                       help="Add paragraph below",
                       use_container_width=True):
                update_context_setting(thread_id, 'ref_end_offset', 1)
                st.rerun()
        with col_down_minus:
            if st.button("[↓−]", key=f"ref_down_minus_{thread_id}",
                       disabled=not can_contract_ref_down(thread_id),
                       help="Remove paragraph below",
                       use_container_width=True):
                update_context_setting(thread_id, 'ref_end_offset', -1)
                st.rerun()
        
        # Display target paragraph(s) with exact text highlighted
        if context_data['target']:
            for para in context_data['target']:
                para_text = para['text']
                para_escaped = html_module.escape(para_text).replace('\n', '<br>')
                is_anchor = para.get('is_anchor', True)  # Original anchor paragraph?
                
                # Only highlight anchor paragraphs (not expanded ones)
                if is_anchor and thread.exact_text:
                    exact_text = thread.exact_text.strip()
                    para_text_stripped = para_text.strip()
                    exact_escaped = html_module.escape(thread.exact_text)
                    
                    # Normalize for comparison (collapse whitespace)
                    def normalize(s):
                        return ' '.join(s.split())
                    
                    exact_normalized = normalize(exact_text)
                    para_normalized = normalize(para_text_stripped)
                    
                    # Check if entire paragraph is referenced (by length or exact match)
                    if (exact_normalized == para_normalized or 
                        len(exact_normalized) >= len(para_normalized) * 0.9 or
                        para_normalized in exact_normalized):
                        # Entire paragraph referenced - highlight everything
                        para_escaped = f'<mark style="background-color: #fff3cd; padding: 0 2px;">{para_escaped}</mark>'
                    else:
                        # Try to highlight the exact portion
                        if exact_escaped in para_escaped:
                            para_escaped = para_escaped.replace(
                                exact_escaped,
                                f'<mark style="background-color: #fff3cd; padding: 0 2px;">{exact_escaped}</mark>',
                                1  # Only replace first occurrence
                            )
                        else:
                            # Fallback: if exact_text exists but doesn't match, highlight everything
                            para_escaped = f'<mark style="background-color: #fff3cd; padding: 0 2px;">{para_escaped}</mark>'
                
                # Visual indicator if paragraph was revised earlier this session
                revised_indicator = ' <span style="color: #28a745; font-size: 0.8em;">(edited earlier)</span>' if para.get('is_revised') else ''
                
                # Different styling for anchor vs expanded paragraphs
                if is_anchor:
                    # Original anchor - blue border
                    st.markdown(
                        f'<div style="padding: 1rem; background-color: #f8f9fa; border-left: 4px solid #2196F3; '
                        f'border-radius: 4px; margin-bottom: 4px; font-family: inherit; line-height: 1.6;">'
                        f'{para_escaped}{revised_indicator}</div>',
                        unsafe_allow_html=True
                    )
                else:
                    # Expanded paragraph - lighter styling (similar to context)
                    st.markdown(
                        f'<div style="padding: 0.5rem 1rem; background-color: #e8f4fc; border-left: 3px solid #90caf9; '
                        f'border-radius: 2px; margin-bottom: 4px; font-family: inherit; line-height: 1.5;">'
                        f'{para_escaped}{revised_indicator}</div>',
                        unsafe_allow_html=True
                    )
        elif thread.paragraph_text and thread.exact_text:
            # Fallback to old display if context data not available
            para_escaped = html_module.escape(thread.paragraph_text)
            exact_escaped = html_module.escape(thread.exact_text)
            highlighted = para_escaped.replace(
                exact_escaped,
                f'<mark style="background-color: #fff3cd; padding: 0 2px;">{exact_escaped}</mark>',
                1
            ).replace('\n', '<br>')
            st.markdown(
                f'<div style="padding: 1rem; background-color: #f8f9fa; border-left: 4px solid #2196F3; '
                f'border-radius: 4px; font-family: inherit; line-height: 1.6;">'
                f'{highlighted}</div>',
                unsafe_allow_html=True
            )
        elif thread.referenced_text:
            # Fallback to referenced_text if nothing else available
            ref_escaped = html_module.escape(thread.referenced_text).replace('\n', '<br>')
            st.markdown(
                f'<div style="padding: 1rem; background-color: #e7f3fe; border-left: 4px solid #2196F3; '
                f'border-radius: 4px; font-family: inherit; line-height: 1.6;">'
                f'{ref_escaped}</div>',
                unsafe_allow_html=True
            )
    
    # --- Context (Following) Section ---
    # Always show header and buttons (even when context is 0) so user can expand
    with st.container():
        # Header row with title and buttons using fixed-width button columns (same as Preceding)
        col_title, col_plus, col_minus = st.columns([10, 1, 1], gap="small")
        with col_title:
            st.markdown("**Context (Following)**")
        with col_plus:
            if st.button("[+]", key=f"ctx_after_plus_{thread_id}",
                       disabled=not can_expand_after(thread_id),
                       help="Add one paragraph to context",
                       use_container_width=True):
                update_context_setting(thread_id, 'after_count', 1)
                st.rerun()
        with col_minus:
            if st.button("[−]", key=f"ctx_after_minus_{thread_id}",
                       disabled=settings['after_count'] == 0,
                       help="Remove one paragraph from context",
                       use_container_width=True):
                update_context_setting(thread_id, 'after_count', -1)
                st.rerun()
        
        # Display following paragraphs (or message if none)
        if context_data['after']:
            for para in context_data['after']:
                text_escaped = html_module.escape(para['text']).replace('\n', '<br>')
                # Visual indicator if paragraph was revised earlier this session
                revised_indicator = ' <span style="color: #28a745; font-size: 0.8em;">(edited earlier)</span>' if para.get('is_revised') else ''
                st.markdown(
                    f'<div style="padding: 0.5rem 1rem; background-color: #f0f0f0; border-left: 2px solid #9e9e9e; '
                    f'border-radius: 2px; margin-bottom: 4px; font-family: inherit; line-height: 1.5; color: #555;">'
                    f'{text_escaped}{revised_indicator}</div>',
                    unsafe_allow_html=True
                )
        elif settings['after_count'] == 0:
            st.caption("*No context (click ➕ to add)*")
        else:
            st.caption("*End of document*")
    
    # Comment thread
    st.markdown("**Comment Thread:**")
    for i, comment in enumerate(thread.comments):
        date_str = comment.date.split('T')[0] if comment.date and 'T' in comment.date else ""
        with st.container():
            st.markdown(f"**{comment.author}** ({date_str})")
            # Show full comment text (no truncation)
            st.text(comment.text)
            if i < len(thread.comments) - 1:
                st.markdown("---")
    
    st.divider()
    
    # Suggestion section
    render_suggestion_section(thread)


def render_suggestion_section(thread):
    """Render the AI suggestion section."""
    thread_id = thread.thread_id
    
    # Check if we have a suggestion
    has_suggestion = thread_id in st.session_state.suggestions
    suggestion = st.session_state.suggestions.get(thread_id, {})
    
    # Generate button (disabled if suggestion already exists - use Regenerate instead)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("🤖 Generate Suggestion", use_container_width=True, type="primary", 
                     disabled=has_suggestion):
            generate_suggestion(thread)
            st.rerun()
    
    if has_suggestion:
        st.markdown("---")
        
        # Get generation counter for unique widget keys (forces refresh on regenerate)
        gen_count = st.session_state.generation_counter.get(thread_id, 0)
        
        # View mode toggle for revised text
        st.markdown("**Revised Text:**")
        
        # Toggle between Diff View and Edit View
        view_mode = st.radio(
            "View mode",
            options=["📊 Diff View", "✏️ Edit View"],
            horizontal=True,
            label_visibility="collapsed",
            key=f"view_mode_{thread_id}_{gen_count}"
        )
        
        if view_mode == "📊 Diff View":
            # Show diff between original and revised text
            original_text = thread.paragraph_text or thread.referenced_text or ""
            revised_text_value = suggestion.get("revised_text", "")
            
            if original_text and revised_text_value:
                # Compute diff
                diff_result = compute_diff(original_text, revised_text_value)
                
                if diff_result.has_changes:
                    # Generate HTML with styling
                    diff_html = diff_to_html(
                        diff_result,
                        delete_style="text-decoration: line-through; background-color: #ffcdd2; color: #c62828; padding: 0 2px;",
                        insert_style="background-color: #c8e6c9; color: #2e7d32; padding: 0 2px;",
                    )
                    # Wrap in a styled container
                    styled_html = f'''
                    <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; 
                                padding: 12px; font-family: inherit; font-size: 14px; line-height: 1.6;
                                max-height: 200px; overflow-y: auto;">
                        {diff_html}
                    </div>
                    '''
                    st.markdown(styled_html, unsafe_allow_html=True)
                else:
                    st.info("No changes detected between original and revised text.")
            else:
                st.warning("Cannot show diff: original or revised text is missing.")
            
            # Store the current revised text (unchanged in diff view)
            revised_text = suggestion.get("revised_text", "")
        else:
            # Edit View - show editable text area
            revised_text = st.text_area(
                "revised_text",
                value=suggestion.get("revised_text", ""),
                height=150,
                label_visibility="collapsed",
                key=f"revised_{thread_id}_{gen_count}"
            )
        
        # Editable response
        st.markdown("**Response to Reviewer:**")
        response = st.text_area(
            "response",
            value=suggestion.get("response", ""),
            height=100,
            label_visibility="collapsed",
            key=f"response_{thread_id}_{gen_count}"
        )
        
        # Rationale (read-only, collapsible)
        if suggestion.get("rationale"):
            with st.expander("📋 Rationale"):
                st.write(suggestion["rationale"])
        
        # Update suggestion with any edits (preserving target_para_id for virtual state)
        st.session_state.suggestions[thread_id] = {
            "revised_text": revised_text,
            "response": response,
            "rationale": suggestion.get("rationale"),
            "target_para_id": suggestion.get("target_para_id")  # Preserve for virtual state
        }
        
        st.divider()
        
        # Action buttons
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("✅ Accept", use_container_width=True, type="primary"):
                accept_suggestion(thread)
                st.rerun()
        
        with col2:
            if st.button("⏭️ Skip", use_container_width=True):
                skip_thread(thread)
                st.rerun()
        
        with col3:
            if st.button("🔄 Regenerate", use_container_width=True):
                # Increment generation counter to force new widget keys
                current_count = st.session_state.generation_counter.get(thread_id, 0)
                st.session_state.generation_counter[thread_id] = current_count + 1
                generate_suggestion(thread)
                st.rerun()


def generate_suggestion(thread):
    """Generate an AI suggestion for a thread."""
    with st.spinner("Generating suggestion..."):
        try:
            handler = LLMHandler(
                provider=st.session_state.provider,
                docx_path=st.session_state.docx_path
            )
            
            # Get context settings for this thread
            settings = get_context_settings(thread.thread_id)
            
            # Pass accepted_revisions and context settings so LLM sees up-to-date context
            suggestion = handler.generate_suggestion(
                thread,
                accepted_revisions=st.session_state.accepted_revisions,
                context_before_count=settings['before_count'],
                context_after_count=settings['after_count']
            )
            
            st.session_state.suggestions[thread.thread_id] = {
                "revised_text": suggestion.revised_text,
                "response": suggestion.response,
                "rationale": suggestion.rationale,
                "target_para_id": suggestion.target_para_id  # Store for later use
            }
            
            st.success("Suggestion generated!")
        except Exception as e:
            st.error(f"Error generating suggestion: {e}")


def accept_suggestion(thread):
    """Accept the current suggestion and move to next thread."""
    thread_id = thread.thread_id
    st.session_state.thread_statuses[thread_id] = "done"
    
    # Get the suggestion data
    suggestion = st.session_state.suggestions.get(thread_id, {})
    
    # Update virtual state: store the accepted revision by para_id
    # This allows subsequent LLM calls to see the updated text
    target_para_id = suggestion.get("target_para_id")
    revised_text = suggestion.get("revised_text", "")
    if target_para_id and revised_text:
        st.session_state.accepted_revisions[target_para_id] = revised_text
    
    # Save suggestion to file using original filename for output path
    output_path = get_output_path()
    if output_path:
        save_llm_suggestion(
            output_path,
            thread_id,
            {
                "thread_id": thread_id,
                "section": thread.section,
                "status": "done",
                "accepted_revision": revised_text,
                "accepted_response": suggestion.get("response", ""),
                "rationale": suggestion.get("rationale"),
                "target_para_id": target_para_id  # Also save para_id for debugging
            }
        )
        save_session()
    
    # Move to next
    threads = get_filtered_threads()
    if st.session_state.current_index < len(threads) - 1:
        st.session_state.current_index += 1
    
    st.success("Accepted!")


def skip_thread(thread):
    """Skip the current thread and move to next."""
    thread_id = thread.thread_id
    st.session_state.thread_statuses[thread_id] = "skipped"
    
    # Save session
    save_session()
    
    # Move to next
    threads = get_filtered_threads()
    if st.session_state.current_index < len(threads) - 1:
        st.session_state.current_index += 1
    
    st.info("Skipped")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point."""
    init_session_state()
    render_sidebar()
    render_main()


if __name__ == "__main__":
    main()

