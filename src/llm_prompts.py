"""Prompt building, citation protection, and context formatting for LLM calls."""

import json
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from src.session_utils import ThreadContext
from src.diff_utils import strip_html_tags

class LLMPromptsMixin:
    """Mixin for LLM prompt assembly."""

    def _build_chat_prompt(
        self,
        thread: ThreadContext,
        chat_history: List['ChatMessage'],
        user_message: str,
        current_revision: str,
        current_reply: str,
        paragraph_cache: Optional[List[Dict]] = None,
        target_indices: Optional[Tuple[int, int]] = None,
        context_settings: Optional[Dict] = None,
        accepted_revisions: Optional[Dict[str, str]] = None,
        instructions: Optional[str] = None,
        attachments: Optional[List[Dict]] = None
    ) -> str:
        """Build the prompt for chat mode interaction."""
        
        # Get context if available
        context_before = ""
        context_after = ""
        referenced_text = thread.paragraph_text or thread.referenced_text or ""
        
        if paragraph_cache and target_indices:
            settings = context_settings or {
                "before_count": 2, "after_count": 2,
                "ref_start_offset": 0, "ref_end_offset": 0
            }
            
            # Use the same context extraction as generate_suggestion
            try:
                ctx_before, ctx_para, ctx_after, _, _ = self._get_context_from_cache(
                    thread, paragraph_cache, 
                    {thread.thread_id: target_indices},
                    accepted_revisions,
                    settings.get('before_count', 2),
                    settings.get('after_count', 2),
                    settings.get('ref_start_offset', 0),
                    settings.get('ref_end_offset', 0)
                )
                context_before = ctx_before
                context_after = ctx_after
                referenced_text = ctx_para
            except Exception as e:
                print(f"[CHAT] Warning: Could not get context from cache: {e}", flush=True)
        
        # Build comment text from thread
        comment_text = " | ".join(c.text for c in thread.comments)
        comment_author = thread.comments[0].author if thread.comments else "Unknown"
        
        # Apply sliding window to chat history
        recent_history = chat_history[-self.MAX_CHAT_MESSAGES:] if len(chat_history) > self.MAX_CHAT_MESSAGES else chat_history
        truncation_note = ""
        if len(chat_history) > self.MAX_CHAT_MESSAGES:
            truncation_note = f"[{len(chat_history) - self.MAX_CHAT_MESSAGES} earlier messages not shown]\n\n"
        
        # Format chat history
        history_text = truncation_note
        for msg in recent_history:
            if msg.role == "user":
                history_text += f"USER: {msg.content}\n\n"
            elif msg.role == "assistant":
                history_text += f"ASSISTANT: {msg.content}\n\n"
            # Skip system messages in history display
        
        # Use provided instructions or default
        system_instructions = instructions or """You are an expert Medical Writer helping refine a revision to address a reviewer's comment on a scientific manuscript."""
        
        # Build the full prompt
        prompt = f"""{system_instructions}

IMPORTANT: Your response will be displayed to the user in multiple places:
- "chat_response": Shown in the chat conversation area. Use this for explanations, 
  confirmations, and dialogue with the user. This field is REQUIRED.
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
- PARAGRAPH STRUCTURE: By default, preserve the original paragraph structure. Only split a paragraph into multiple paragraphs (separate with a blank line) or merge paragraphs if the user EXPLICITLY requests it (e.g., "split this into two paragraphs", "merge these paragraphs")

=== DOCUMENT CONTEXT ===
"""
        
        if context_before:
            prompt += f"PRECEDING TEXT:\n{context_before}\n\n"
        
        prompt += f"REFERENCED TEXT (what the comment refers to):\n{referenced_text}\n\n"
        
        if context_after:
            prompt += f"FOLLOWING TEXT:\n{context_after}\n\n"
        
        # Add attachments if available
        if attachments:
            prompt += self._format_attachments(attachments)
            prompt += "\n\n"
        
        exact_ref = self._format_exact_reference(thread, referenced_text)
        prompt += f"""=== REVIEWER'S COMMENT ===
Author: {comment_author}
Comment: {comment_text}
{exact_ref}
=== CURRENT STATE ===
CURRENT REVISION:
{current_revision}

CURRENT REPLY TO REVIEWER:
{current_reply}

=== CONVERSATION HISTORY ===
{history_text}
=== USER'S NEW MESSAGE ===
{user_message}

Please respond in JSON format:
{{
  "chat_response": "Your conversational reply to the user (REQUIRED)",
  "revised_text": "Updated revision (only if you are changing it)",
  "response": "Updated reply to reviewer (only if you are changing it)",
  "rationale": "Brief explanation of changes (optional)"
}}

Respond with valid JSON only. Include "revised_text" and/or "response" ONLY if you are making changes to them."""
        
        return prompt
    
    def _protect_unicode(self, text: str) -> Tuple[str, bool]:
        """
        Replace special Unicode characters with placeholders before sending to LLM.
        
        Some LLMs occasionally corrupt special Unicode characters (like ≥, ≤, ±).
        This protects them by replacing with ASCII placeholders that are restored later.
        
        Returns:
            Tuple of (protected text, whether any replacements were made)
        """
        if not text:
            return text, False
        
        result = text
        had_replacements = False
        for char, placeholder in self.UNICODE_PROTECTION_MAP.items():
            if char in result:
                result = result.replace(char, placeholder)
                had_replacements = True
        
        if had_replacements:
            print(f"[LLM UNICODE] Protected special Unicode characters in input", flush=True)
        
        return result, had_replacements
    
    def _restore_unicode(self, text: str) -> str:
        """
        Restore special Unicode characters from placeholders after LLM response.
        """
        if not text:
            return text
        
        result = text
        restored_count = 0
        for placeholder, char in self.UNICODE_RESTORATION_MAP.items():
            if placeholder in result:
                result = result.replace(placeholder, char)
                restored_count += 1
        
        if restored_count > 0:
            print(f"[LLM UNICODE] Restored {restored_count} protected Unicode character type(s)", flush=True)
        
        return result
    
    def _extract_citations(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Extract citations from text and replace with markers.
        
        NOTE: This method is now a NO-OP. Citation/field code handling has been
        moved to the Document Model layer:
        - Field codes (EndNote, Zotero) are detected at parse time by DocumentParser
        - Paragraph.plain_text already contains [CITATION_X] placeholders
        - DocumentSerializer restores field code XML during export
        
        This approach is superior because:
        1. It preserves the actual Word field code XML structure
        2. It handles complex field codes that span multiple runs
        3. Placeholders are consistent throughout the entire pipeline
        
        The old regex-based approach (below, commented out) is preserved for reference
        in case we need to handle manual text citations differently in the future.
        
        Returns:
            Tuple of (text unchanged, empty dict)
        """
        # Field codes are now handled at the DOM level (parser/serializer)
        # Return text unchanged with empty citation_map
        return text, {}
        
        # === OLD IMPLEMENTATION (preserved for reference) ===
        # Pattern 1: Parenthetical author-year citations
        # Matches: (Author(s) Year) possibly with multiple citations separated by ;
        # author_year_pattern = r'\([A-Z][a-zA-Z\-\']+(?:,?\s+(?:and\s+)?[A-Z][a-zA-Z\-\']+)*(?:\s+et\s+al\.?)?,?\s+\d{4}(?:\s*[;,]\s*[A-Z][a-zA-Z\-\']+(?:,?\s+(?:and\s+)?[A-Z][a-zA-Z\-\']+)*(?:\s+et\s+al\.?)?,?\s+\d{4})*\)'
        
        # Pattern 2: Numeric citations in brackets
        # Matches: [1], [2], [1-5], [1, 2, 3], [1, 3-5, 7], etc.
        # Must start with a digit (to avoid [Table 1], [Figure 2], etc.)
        # numeric_pattern = r'\[\d+(?:\s*[-–—]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–—]\s*\d+)?)*\]'
    
    def _restore_citations(self, text: str, citation_map: Dict[str, str]) -> str:
        """
        Restore citation markers with original citation text.
        """
        result = text
        for marker, citation in citation_map.items():
            result = result.replace(marker, citation)
        return result
    
    def _get_markers_per_paragraph(self, masked_text: str, citation_map: Dict[str, str]) -> Dict[int, List[str]]:
        """
        Track which citation markers belong to which paragraph.
        
        Args:
            masked_text: Text with citation markers (paragraphs separated by \n\n)
            citation_map: Dict mapping marker -> original citation
            
        Returns:
            Dict mapping paragraph index -> list of markers in that paragraph
        """
        paragraphs = masked_text.split("\n\n")
        markers_per_para = {}
        
        for para_idx, para in enumerate(paragraphs):
            markers_in_para = []
            for marker in citation_map.keys():
                if marker in para:
                    markers_in_para.append(marker)
            if markers_in_para:
                markers_per_para[para_idx] = markers_in_para
        
        return markers_per_para
    
    def _validate_and_restore_markers(
        self, 
        revised_text: str, 
        markers_per_para: Dict[int, List[str]]
    ) -> Tuple[str, List[str]]:
        """
        Validate that all citation markers are present in the revised text.
        If any are missing from their original paragraph, append them to the end.
        
        Args:
            revised_text: The LLM's revised text (paragraphs separated by \n\n)
            markers_per_para: Dict mapping paragraph index -> list of expected markers
            
        Returns:
            Tuple of (corrected text, list of restored markers)
        """
        if not markers_per_para:
            return revised_text, []
        
        paragraphs = revised_text.split("\n\n")
        restored_markers = []
        
        # Check each paragraph for its expected markers
        for para_idx, expected_markers in markers_per_para.items():
            if para_idx >= len(paragraphs):
                # Paragraph count changed - append all missing markers to last paragraph
                print(f"[CITATION] WARNING: Paragraph {para_idx} no longer exists, appending markers to last paragraph", flush=True)
                for marker in expected_markers:
                    if marker not in revised_text:
                        paragraphs[-1] = paragraphs[-1].rstrip('.') + f" {marker}."
                        restored_markers.append(marker)
                        print(f"[CITATION] Restored {marker} to end of last paragraph", flush=True)
                continue
            
            para = paragraphs[para_idx]
            
            for marker in expected_markers:
                if marker not in para:
                    # Marker is missing from this paragraph
                    # Check if it's elsewhere in the text (LLM might have moved it)
                    if marker in revised_text:
                        print(f"[CITATION] {marker} moved to different location - keeping as-is", flush=True)
                    else:
                        # Marker completely missing - restore it at end of paragraph
                        # Remove trailing period if present, add marker, add period back
                        para_stripped = para.rstrip()
                        if para_stripped.endswith('.'):
                            para_stripped = para_stripped[:-1]
                        paragraphs[para_idx] = para_stripped + f" {marker}."
                        restored_markers.append(marker)
                        print(f"[CITATION] Restored missing {marker} to end of paragraph {para_idx}", flush=True)
        
        corrected_text = "\n\n".join(paragraphs)
        return corrected_text, restored_markers
    
    def _build_prompt_with_citation_protection(
        self, 
        thread: ThreadContext,
        accepted_revisions: Optional[Dict[str, str]] = None,
        context_before_count: Optional[int] = None,
        context_after_count: Optional[int] = None,
        ref_start_offset: int = 0,
        ref_end_offset: int = 0,
        custom_instructions: Optional[str] = None,
        paragraph_cache: Optional[List[Dict]] = None,
        thread_target_indices: Optional[Dict[str, Tuple[int, int]]] = None,
        attachments: Optional[List[Dict]] = None
    ) -> Tuple[str, Dict[str, str], Optional[str], Optional[List[str]], str]:
        """
        Build prompt with citations protected by markers.
        
        Args:
            thread: The comment thread
            accepted_revisions: Optional dict mapping para_id -> revised_text
            context_before_count: Number of paragraphs before target (default: self.context_paragraphs_before)
            context_after_count: Number of paragraphs after target (default: self.context_paragraphs_after)
            ref_start_offset: Negative offset to expand target upward
            ref_end_offset: Positive offset to expand target downward
            custom_instructions: Optional custom instructions to use instead of defaults
            paragraph_cache: Optional pre-processed paragraph cache with tables in markdown
            thread_target_indices: Optional dict mapping thread_id -> (start_idx, end_idx)
            attachments: Optional list of attachment dicts with 'filename' and 'parsed_content' keys
        
        Returns:
            Tuple of (prompt, citation_map, target_para_id, all_target_para_ids, masked_paragraph_text)
        """
        # Get expanded context if docx_path is available
        context_before = ""
        context_after = ""
        target_para_id = None
        all_target_para_ids = None
        
        # Use paragraph_text if available
        paragraph_to_revise = thread.paragraph_text or thread.referenced_text or "[Referenced text not available]"
        
        # If paragraph_cache is provided, use it (handles tables as markdown)
        if paragraph_cache and thread_target_indices and thread.thread_id in thread_target_indices:
            ctx_before, ctx_para, ctx_after, target_para_id, all_target_para_ids = self._get_context_from_cache(
                thread, paragraph_cache, thread_target_indices, accepted_revisions,
                context_before_count, context_after_count, ref_start_offset, ref_end_offset
            )
            context_before = ctx_before
            context_after = ctx_after
            paragraph_to_revise = ctx_para
        elif self.docx_path:
            ctx_before, ctx_para, ctx_after, target_para_id, all_target_para_ids = self._get_expanded_context(
                thread, accepted_revisions, context_before_count, context_after_count,
                ref_start_offset, ref_end_offset
            )
            context_before = ctx_before
            context_after = ctx_after
            # Use the expanded target paragraph(s) from context extraction
            paragraph_to_revise = ctx_para
        
        # Extract citations from the paragraph(s) to revise
        paragraph_with_markers, citation_map = self._extract_citations(paragraph_to_revise)
        
        # Determine if we have multiple paragraphs to revise (indicated by double newlines)
        has_multiple_paragraphs = "\n\n" in paragraph_to_revise
        target_label = "TARGET TEXT (revise ALL paragraphs below)" if has_multiple_paragraphs else "TARGET PARAGRAPH (this is what you should revise)"
        
        # Build revised_text instruction with paragraph structure guidance
        if has_multiple_paragraphs:
            revised_text_instruction = "Your revised version of ALL the target paragraphs above. Preserve paragraph breaks (separate paragraphs with a blank line). You may split or merge paragraphs ONLY if the reviewer explicitly requests it or if it is clearly necessary to address their concern"
        else:
            revised_text_instruction = "Your revised version of the target paragraph. You may split it into multiple paragraphs ONLY if the reviewer explicitly requests it (e.g., 'break this into two paragraphs') - separate paragraphs with a blank line. Otherwise, keep it as a single paragraph"
        
        # Debug logging for target text
        print(f"[LLM PROMPT] Target text length: {len(paragraph_to_revise)}", flush=True)
        print(f"[LLM PROMPT] Target text preview: {paragraph_to_revise[:200] if paragraph_to_revise else '(empty)'}...", flush=True)
        
        # Build JSON response instructions (same format for all content types)
        # Table cells are now treated as regular paragraphs
        json_instructions = f"""Respond with a JSON object containing exactly these three fields:
{{
  "revised_text": "{revised_text_instruction}. If no text changes are needed, copy the original text exactly.",
  "response": "Your professional reply to the reviewer",
  "rationale": "Brief explanation of the changes you made, or why no changes were needed"
}}

IMPORTANT: If the comment has already been addressed (e.g., the requested change is already in place), 
explain this in your response and copy the original text unchanged to revised_text."""
        
        # Context doesn't need citation extraction (placeholders already in text from DOM)
        context_before_with_markers = context_before
        context_after_with_markers = context_after
        
        # Format the comment thread
        comments_text = self._format_comment_thread(thread)
        
        # Build citation instruction
        # Check if text contains [CITATION_X] placeholders (from DOM-level field code handling)
        has_citation_placeholders = '[CITATION_' in paragraph_with_markers
        
        if has_citation_placeholders:
            citation_instruction = """
CITATION RULES (critical):
- Existing citations appear as [CITATION_0], [CITATION_1], etc. These are internal placeholders - preserve them EXACTLY as written in the revised_text
- DO NOT create new placeholders like [CITATION_2], [CITATION_X], [REF_X], etc. - this format is reserved for existing citations only
- If you need to ADD a new citation (e.g., for Lee et al.), write it in author-year format: (Lee 2023) or (Lee et al. 2023)
- Example of CORRECT usage in revised_text: "...consistent with previous reports [CITATION_1] and recent findings (Lee 2023)."
- Example of WRONG usage: "...consistent with previous reports [CITATION_1] [CITATION_2]." (DO NOT invent new bracketed placeholders)

IMPORTANT - In your "response" to the reviewer:
- NEVER mention [CITATION_X] placeholders - the reviewer cannot see these internal markers
- If you need to refer to a citation, describe it naturally (e.g., "the original citation" or "the existing reference")
- Example of WRONG response: "...while retaining the original safety citation [CITATION_1]."
- Example of CORRECT response: "...while retaining the original safety citation."
"""
        else:
            # Even without existing citations, prevent LLM from using marker format
            citation_instruction = """
CITATION RULES:
- Do NOT use placeholder syntax like [CITATION_X], [REF_X], or [1] in your revision or response
- If you want to add a citation, write it in author-year format: (Author Year) or (Author et al. Year)
- Example: "These findings are consistent with prior work (Lee 2023)."
"""
        
        # Use custom instructions if provided, otherwise use defaults
        if custom_instructions:
            instructions_block = custom_instructions
        else:
            instructions_block = """You are an expert Medical Writer working on a scientific manuscript for a peer-reviewed journal.

Your task is to address a reviewer's comment by:
1. REVISING the target paragraph to address the comment (if changes are needed)
2. DRAFTING a professional reply to the reviewer

IMPORTANT GUIDELINES:
- Preserve scientific accuracy and formal academic tone
- Keep revisions minimal but sufficient to fully address the concern
- If no text changes are needed (e.g., the requested change is already in place), copy the original text unchanged and explain this in your reply
- Your reply should be concise, polite, and professional
- If the original comment is in Japanese, still write your reply in English
- Do not change content that is not relevant to the comment
- PARAGRAPH STRUCTURE: By default, preserve the original paragraph structure. Only split a paragraph into multiple paragraphs (separate with a blank line) or merge paragraphs if the reviewer EXPLICITLY requests it. Do not restructure paragraphs on your own initiative."""
        
        # Build the prompt
        prompt = f"""{instructions_block}
{citation_instruction}
═══════════════════════════════════════════════════════════════════════════════
DOCUMENT LOCATION
═══════════════════════════════════════════════════════════════════════════════
Section: {thread.section or "Not specified"}

═══════════════════════════════════════════════════════════════════════════════
CONTEXT (preceding paragraphs - for reference only, do NOT revise)
═══════════════════════════════════════════════════════════════════════════════
{context_before_with_markers if context_before_with_markers else "[No preceding context available]"}

═══════════════════════════════════════════════════════════════════════════════
{target_label}
═══════════════════════════════════════════════════════════════════════════════
{paragraph_with_markers}

═══════════════════════════════════════════════════════════════════════════════
CONTEXT (following paragraphs - for reference only, do NOT revise)
═══════════════════════════════════════════════════════════════════════════════
{context_after_with_markers if context_after_with_markers else "[No following context available]"}
{self._format_attachments(attachments)}
═══════════════════════════════════════════════════════════════════════════════
REVIEWER COMMENT(S)
═══════════════════════════════════════════════════════════════════════════════
{comments_text}
{self._format_exact_reference(thread, paragraph_with_markers)}
═══════════════════════════════════════════════════════════════════════════════
YOUR RESPONSE
═══════════════════════════════════════════════════════════════════════════════
{json_instructions}

IMPORTANT: Output ONLY the JSON object, no additional text before or after.
"""
        return prompt, citation_map, target_para_id, all_target_para_ids, paragraph_with_markers
    
    def _format_comment_thread(self, thread: ThreadContext) -> str:
        """Format the comment thread for the prompt."""
        lines = []
        for i, comment in enumerate(thread.comments):
            prefix = "Original comment" if i == 0 else f"Reply {i}"
            date_str = comment.date.split('T')[0] if comment.date and 'T' in comment.date else comment.date
            lines.append(f"{prefix} by {comment.author} ({date_str}):")
            lines.append(f"  {comment.text}")
            lines.append("")
        return "\n".join(lines)
    
    def _format_exact_reference(self, thread: ThreadContext, target_text: str) -> str:
        """
        Format the exact text fragment the comment references, if available.
        
        Returns an empty string when the comment covers the entire target or
        when no anchor information is available.
        """
        exact = getattr(thread, 'exact_text', None)
        if not exact or not exact.strip():
            return ""
        # Skip if the referenced fragment is essentially the whole target
        target_plain = target_text.replace('\n', ' ').strip()
        if len(exact) >= len(target_plain) * 0.9:
            return ""
        return f"Note: The comment specifically references this portion of the target text: \"{exact}\"\n"

    def _format_attachments(self, attachments: Optional[List[Dict]]) -> str:
        """Format attachments for inclusion in the prompt."""
        if not attachments:
            return ""
        
        sections = []
        sections.append("")
        sections.append("═══════════════════════════════════════════════════════════════════════════════")
        sections.append("REFERENCE DOCUMENTS (attached for context - use information as needed)")
        sections.append("═══════════════════════════════════════════════════════════════════════════════")
        
        for attachment in attachments:
            filename = attachment.get('filename', 'Unknown file')
            content = attachment.get('parsed_content', '')
            
            if content:
                sections.append(f"\n--- {filename} ---")
                sections.append(content)
        
        return "\n".join(sections)
    
    def _get_para_id(self, para) -> Optional[str]:
        """Extract w14:paraId from a paragraph element."""
        for key, value in para.attrib.items():
            if 'paraId' in key:
                return value
        return None
    
    def _format_cache_item_text(self, item: Dict, accepted_revisions: Optional[Dict[str, str]] = None) -> str:
        """Format a paragraph cache item for the LLM prompt.
        
        Handles:
        - paragraph: Regular text
        - table_row: Pipe-separated row (applying per-cell revisions if any)
        
        Note: accepted_revisions may contain HTML (it's the source of truth for formatting).
        We strip HTML here since LLM needs plain text for context.
        """
        para_id = item.get('para_id')
        item_type = item.get('type', 'paragraph')
        
        # Handle table rows - format as pipe-separated text
        if item_type == 'table_row':
            cells = item.get('cells', [])
            cell_texts = []
            for cell in cells:
                cell_para_id = cell.get('para_id')
                cell_text = cell.get('text', '')
                # Apply accepted revision for this cell if available
                # Strip HTML since LLM needs plain text
                if cell_para_id and accepted_revisions and cell_para_id in accepted_revisions:
                    cell_text = strip_html_tags(accepted_revisions[cell_para_id])
                cell_texts.append(cell_text)
            # Format as markdown table row: | col1 | col2 | col3 |
            return '| ' + ' | '.join(cell_texts) + ' |'
        
        # For regular paragraphs, check for accepted revision first
        # Strip HTML since LLM needs plain text
        if para_id and accepted_revisions and para_id in accepted_revisions:
            return strip_html_tags(accepted_revisions[para_id])
        
        # Regular paragraph (original text is plain, no need to strip)
        return item.get('text', '')
    
    def _get_context_from_cache(
        self,
        thread: ThreadContext,
        paragraph_cache: List[Dict],
        thread_target_indices: Dict[str, Tuple[int, int]],
        accepted_revisions: Optional[Dict[str, str]] = None,
        context_before_count: Optional[int] = None,
        context_after_count: Optional[int] = None,
        ref_start_offset: int = 0,
        ref_end_offset: int = 0
    ) -> Tuple[str, str, str, Optional[str], Optional[List[str]]]:
        """
        Extract context using the pre-processed paragraph cache.
        
        This uses the same paragraph cache as the UI, ensuring tables are
        formatted consistently.
        
        Args:
            thread: The comment thread to get context for
            paragraph_cache: Pre-processed paragraph cache from DocumentModel
            thread_target_indices: Dict mapping thread_id -> (start_idx, end_idx)
            accepted_revisions: Optional dict mapping para_id -> revised_text
            context_before_count: Number of paragraphs before target
            context_after_count: Number of paragraphs after target
            ref_start_offset: Negative offset to expand target upward
            ref_end_offset: Positive offset to expand target downward
            
        Returns:
            Tuple of (context_before, target_paragraphs, context_after, target_para_id, all_target_para_ids)
        """
        accepted_revisions = accepted_revisions or {}
        
        # Use provided counts or fall back to defaults
        before_count = context_before_count if context_before_count is not None else self.context_paragraphs_before
        after_count = context_after_count if context_after_count is not None else self.context_paragraphs_after
        
        # Get target indices
        start_idx, end_idx = thread_target_indices.get(thread.thread_id, (0, 0))
        
        # Apply ref offsets to expand/contract target range
        effective_start = max(0, start_idx + ref_start_offset)
        effective_end = min(len(paragraph_cache) - 1, end_idx + ref_end_offset)
        
        # Get the original target paragraph's para_id
        target_para_id = paragraph_cache[start_idx].get('para_id') if start_idx < len(paragraph_cache) else None
        
        print(f"[CACHE CONTEXT] Thread {thread.thread_id}: target [{effective_start}, {effective_end}], before={before_count}, after={after_count}", flush=True)
        
        # Build context before
        before_start = max(0, effective_start - before_count)
        paragraphs_before = []
        for i in range(before_start, effective_start):
            item = paragraph_cache[i]
            text = self._format_cache_item_text(item, accepted_revisions)
            if text.strip():
                paragraphs_before.append(text)
                if item.get('para_id') in accepted_revisions:
                    print(f"[CACHE CONTEXT] ✅ Using revision for BEFORE idx={i}, para_id={item.get('para_id')}", flush=True)
        
        # Build target paragraphs
        target_paragraphs = []
        all_target_para_ids = []
        table_row_context = None  # For table row comments, add row info
        
        for i in range(effective_start, effective_end + 1):
            item = paragraph_cache[i]
            para_id = item.get('para_id')
            item_type = item.get('type', 'paragraph')
            print(f"[CACHE CONTEXT] Target idx={i}, para_id={para_id}, type={item_type}", flush=True)
            
            # Handle table_row: send the whole row as target, track all cell para_ids
            if item_type == 'table_row':
                cells = item.get('cells', [])
                row_num = item.get('row_number', 0)
                total_rows = item.get('total_rows', 0)
                col_count = item.get('col_count', len(cells))
                
                # Format the row with cell revisions applied
                row_text = self._format_cache_item_text(item, accepted_revisions)
                target_paragraphs.append(row_text)
                
                # Track ALL cell para_ids from this row
                for cell in cells:
                    cell_para_id = cell.get('para_id')
                    if cell_para_id:
                        all_target_para_ids.append(cell_para_id)
                        if cell_para_id in (accepted_revisions or {}):
                            print(f"[CACHE CONTEXT] ✅ Using revision for cell para_id={cell_para_id}", flush=True)
                
                # The first cell's para_id becomes the "main" target for backwards compatibility
                if cells and cells[0].get('para_id'):
                    target_para_id = cells[0]['para_id']
                
                # Add context about this being a table row
                table_row_context = f"[TABLE ROW {row_num}/{total_rows}, {col_count} columns - cells separated by pipes | ]"
                print(f"[CACHE CONTEXT] Table row {row_num}/{total_rows}: {len(cells)} cells, para_ids={[c.get('para_id') for c in cells]}", flush=True)
            else:
                text = self._format_cache_item_text(item, accepted_revisions)
                if text.strip():
                    target_paragraphs.append(text)
                    if para_id:
                        all_target_para_ids.append(para_id)
                    if para_id in (accepted_revisions or {}):
                        print(f"[CACHE CONTEXT] ✅ Using revision for TARGET idx={i}, para_id={para_id}", flush=True)
        
        # Build context after
        after_end = min(len(paragraph_cache), effective_end + 1 + after_count)
        paragraphs_after = []
        for i in range(effective_end + 1, after_end):
            item = paragraph_cache[i]
            text = self._format_cache_item_text(item, accepted_revisions)
            if text.strip():
                paragraphs_after.append(text)
                if item.get('para_id') in accepted_revisions:
                    print(f"[CACHE CONTEXT] ✅ Using revision for AFTER idx={i}, para_id={item.get('para_id')}", flush=True)
        
        context_before = "\n\n".join(paragraphs_before)
        context_after = "\n\n".join(paragraphs_after)
        target_text = "\n\n".join(target_paragraphs) if target_paragraphs else (thread.referenced_text or "")
        
        # If there's table row context, prepend it to context_before so LLM understands format
        if table_row_context:
            if context_before:
                context_before = context_before + "\n\n" + table_row_context
            else:
                context_before = table_row_context
        
        print(f"[CACHE CONTEXT] All target para_ids: {all_target_para_ids}", flush=True)
        
        return (
            context_before,
            target_text,
            context_after,
            target_para_id,
            all_target_para_ids if all_target_para_ids else None
        )
    
    def _get_expanded_context(
        self, 
        thread: ThreadContext,
        accepted_revisions: Optional[Dict[str, str]] = None,
        context_before_count: Optional[int] = None,
        context_after_count: Optional[int] = None,
        ref_start_offset: int = 0,
        ref_end_offset: int = 0
    ) -> Tuple[str, str, str, Optional[str], Optional[List[str]]]:
        """
        Extract surrounding paragraphs for context, applying any accepted revisions.
        
        This method is designed to be easily modified for context tuning.
        
        Args:
            thread: The comment thread to get context for
            accepted_revisions: Optional dict mapping para_id -> revised_text
                               If provided, any paragraph with a pending revision
                               will use the revised text instead of the original.
            context_before_count: Number of paragraphs before target (default: self.context_paragraphs_before)
            context_after_count: Number of paragraphs after target (default: self.context_paragraphs_after)
            ref_start_offset: Negative offset to expand target upward (e.g., -2 means include 2 paragraphs above)
            ref_end_offset: Positive offset to expand target downward (e.g., 2 means include 2 paragraphs below)
        
        Returns:
            Tuple of (context_before, target_paragraphs, context_after, target_para_id, all_target_para_ids)
            - target_paragraphs may include multiple paragraphs if expanded
            - target_para_id is the w14:paraId of the original target paragraph (for backwards compatibility)
            - all_target_para_ids is a list of ALL para_ids in the expanded target range (for multi-paragraph revisions)
        """
        if not self.docx_path:
            return "", thread.referenced_text or "", "", None, None
        
        accepted_revisions = accepted_revisions or {}
        
        # Use provided counts or fall back to defaults
        before_count = context_before_count if context_before_count is not None else self.context_paragraphs_before
        after_count = context_after_count if context_after_count is not None else self.context_paragraphs_after
        
        try:
            with zipfile.ZipFile(self.docx_path, 'r') as docx:
                doc_xml = docx.read('word/document.xml')
                doc_root = ET.fromstring(doc_xml)
                
                # Find all paragraphs
                all_paragraphs = doc_root.findall('.//w:p', self.NS)
                
                # Find the paragraph containing the comment
                target_para_idx = None
                comment_id = thread.thread_id
                
                for idx, para in enumerate(all_paragraphs):
                    # Look for comment range start with matching ID
                    for elem in para.iter():
                        if elem.tag.endswith('}commentRangeStart'):
                            for key, value in elem.attrib.items():
                                if (key.endswith('id') or key == 'id') and str(value) == str(comment_id):
                                    target_para_idx = idx
                                    break
                    if target_para_idx is not None:
                        break
                
                if target_para_idx is None:
                    # Fallback: return just the referenced text
                    return "", thread.referenced_text or "", "", None
                
                # Get target paragraph's para_id (the original one, for storing revision)
                target_para = all_paragraphs[target_para_idx]
                target_para_id = self._get_para_id(target_para)
                
                # Calculate expanded target range
                # ref_start_offset is negative (e.g., -2 means start 2 paragraphs earlier)
                # ref_end_offset is positive (e.g., 2 means end 2 paragraphs later)
                expanded_target_start = max(0, target_para_idx + ref_start_offset)
                expanded_target_end = min(len(all_paragraphs) - 1, target_para_idx + ref_end_offset)
                
                # Debug: Log context extraction start
                print(f"[VIRTUAL STATE] Extracting context for thread {thread.thread_id}", flush=True)
                print(f"[VIRTUAL STATE] Target paragraph: idx={target_para_idx}, para_id={target_para_id}", flush=True)
                print(f"[VIRTUAL STATE] Expanded target range: [{expanded_target_start}, {expanded_target_end}]", flush=True)
                print(f"[VIRTUAL STATE] Context counts: before={before_count}, after={after_count}", flush=True)
                print(f"[VIRTUAL STATE] Accepted revisions available: {list(accepted_revisions.keys())}", flush=True)
                
                # Extract paragraphs BEFORE the expanded target (applying revisions if any)
                context_start_idx = max(0, expanded_target_start - before_count)
                paragraphs_before = []
                for i in range(context_start_idx, expanded_target_start):
                    para = all_paragraphs[i]
                    para_id = self._get_para_id(para)
                    
                    # Check if this paragraph has an accepted revision
                    if para_id and para_id in accepted_revisions:
                        print(f"[VIRTUAL STATE] ✅ Applying revision to BEFORE context: para_id={para_id} (idx={i})", flush=True)
                        text = accepted_revisions[para_id]
                    else:
                        text = self._extract_paragraph_text(para)
                    
                    if text.strip():
                        paragraphs_before.append(text)
                
                # Extract expanded target paragraphs (all paragraphs in the expanded range)
                target_paragraphs = []
                all_target_para_ids = []  # Track ALL para_ids in the expanded range
                for i in range(expanded_target_start, expanded_target_end + 1):
                    para = all_paragraphs[i]
                    para_id = self._get_para_id(para)
                    
                    # Check if this paragraph has an accepted revision
                    if para_id and para_id in accepted_revisions:
                        print(f"[VIRTUAL STATE] ✅ Applying revision to TARGET paragraph: para_id={para_id} (idx={i})", flush=True)
                        text = accepted_revisions[para_id]
                    else:
                        text = self._extract_paragraph_text(para)
                    
                    if text.strip():
                        target_paragraphs.append(text)
                        if para_id:
                            all_target_para_ids.append(para_id)
                
                # Extract paragraphs AFTER the expanded target (applying revisions if any)
                context_end_idx = min(len(all_paragraphs), expanded_target_end + 1 + after_count)
                paragraphs_after = []
                for i in range(expanded_target_end + 1, context_end_idx):
                    para = all_paragraphs[i]
                    para_id = self._get_para_id(para)
                    
                    # Check if this paragraph has an accepted revision
                    if para_id and para_id in accepted_revisions:
                        print(f"[VIRTUAL STATE] ✅ Applying revision to AFTER context: para_id={para_id} (idx={i})", flush=True)
                        text = accepted_revisions[para_id]
                    else:
                        text = self._extract_paragraph_text(para)
                    
                    if text.strip():
                        paragraphs_after.append(text)
                
                context_before = "\n\n".join(paragraphs_before)
                context_after = "\n\n".join(paragraphs_after)
                target_text = "\n\n".join(target_paragraphs) if target_paragraphs else (thread.referenced_text or "")
                
                print(f"[VIRTUAL STATE] All target para_ids: {all_target_para_ids}", flush=True)
                
                return (
                    context_before, 
                    target_text, 
                    context_after,
                    target_para_id,
                    all_target_para_ids if all_target_para_ids else None
                )
                
        except Exception as e:
            print(f"Warning: Could not extract context: {e}")
            return "", thread.referenced_text or "", "", None, None
    
    def _extract_paragraph_text(self, para) -> str:
        """Extract all text from a paragraph element."""
        text_parts = []
        for run in para.findall('.//w:r', self.NS):
            for t_elem in run.findall('.//w:t', self.NS):
                if t_elem.text:
                    text_parts.append(t_elem.text)
        return ''.join(text_parts)
    
