"""Field code extract/restore/split helpers."""

import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

from .serializer_common import _sanitize_for_xml

# Matches an XML start/end/self-closing tag. Used to check that a paragraph
# content fragment has balanced runs after field-code restoration (M9e Layer B).
_TAG_RE = re.compile(r"<(/?)([\w:.-]+)([^>]*?)(/?)>")


def _fragment_runs_balanced(xml: str) -> bool:
    """Return True if every element open tag in ``xml`` is properly closed.

    Operates on a paragraph *content* fragment (runs, ins/del, field XML, comment
    markers). Field-code ``fldData`` bodies are base64 text with no ``<``/``>``,
    so tag scanning is safe. This is the structural guard behind the M9e safety
    net: an unbalanced fragment is what makes Word refuse to open the document.
    """
    stack: list[str] = []
    for match in _TAG_RE.finditer(xml):
        closing, name, attrs, self_close = match.groups()
        if self_close == "/" or attrs.endswith("/"):
            continue
        if not closing:
            stack.append(name)
        else:
            if not stack or stack[-1] != name:
                return False
            stack.pop()
    return not stack

class SerializerFieldCodesMixin:
    """Mixin providing serializer methods."""

    def _extract_field_codes(self, para_xml: str) -> Tuple[str, Dict[str, str], str]:
        """
        Extract field codes from paragraph XML and replace with placeholders.
        
        Field codes (like EndNote citations) span multiple XML elements:
          <w:fldChar w:fldCharType="begin"/> ... <w:fldChar w:fldCharType="end"/>
        
        We preserve these exactly as-is by:
        1. Finding all field codes in the XML
        2. Replacing each with a unique placeholder in both XML and extracted text
        3. Returning the mapping so we can restore them later
        
        Returns:
            Tuple of:
            - para_xml with field codes replaced by placeholder runs
            - dict mapping placeholder -> original field code XML
            - visible text with placeholders instead of citation display text
        """
        # Safety check: detect partial/unbalanced field codes
        begin_count = len(re.findall(r'w:fldCharType="begin"', para_xml))
        end_count = len(re.findall(r'w:fldCharType="end"', para_xml))
        
        if begin_count != end_count:
            # Unbalanced field codes - some span multiple paragraphs
            # Skip field code extraction
            visible_text = self._extract_visible_text_from_para_xml(para_xml)
            return para_xml, {}, visible_text
        
        if begin_count == 0:
            # No field codes at all
            visible_text = self._extract_visible_text_from_para_xml(para_xml)
            return para_xml, {}, visible_text
        
        field_codes = {}
        placeholder_idx = 0
        modified_xml = para_xml
        
        while True:
            # Find the next field code begin
            begin_match = re.search(
                r'<w:fldChar[^>]*w:fldCharType="begin"[^>]*/?>',
                modified_xml
            )
            if not begin_match:
                break
            
            begin_pos = begin_match.start()
            
            # Find the run containing this begin marker
            search_end = begin_pos
            run_start = -1
            while search_end > 0:
                candidate = modified_xml.rfind('<w:r', 0, search_end)
                if candidate == -1:
                    break
                # Check if this is actually <w:r followed by space or >
                next_char_pos = candidate + 4
                if next_char_pos < len(modified_xml):
                    next_char = modified_xml[next_char_pos]
                    if next_char == ' ' or next_char == '>':
                        run_start = candidate
                        break
                search_end = candidate
            
            if run_start == -1:
                break
            
            # Find the MATCHING end marker by tracking nesting level
            nesting_level = 1
            search_pos = begin_match.end()
            end_pos = None
            
            while nesting_level > 0 and search_pos < len(modified_xml):
                next_begin = re.search(
                    r'<w:fldChar[^>]*w:fldCharType="begin"[^>]*/?>',
                    modified_xml[search_pos:]
                )
                next_end = re.search(
                    r'<w:fldChar[^>]*w:fldCharType="end"[^>]*/?>',
                    modified_xml[search_pos:]
                )
                
                if next_end is None:
                    break
                
                if next_begin and next_begin.start() < next_end.start():
                    nesting_level += 1
                    search_pos = search_pos + next_begin.end()
                else:
                    nesting_level -= 1
                    if nesting_level == 0:
                        end_pos = search_pos + next_end.end()
                    search_pos = search_pos + next_end.end()
            
            if end_pos is None:
                break
            
            # Find the </w:r> after the end marker
            run_end = modified_xml.find('</w:r>', end_pos)
            if run_end == -1:
                break
            run_end += len('</w:r>')
            
            # Extract the full field code XML
            field_code_xml = modified_xml[run_start:run_end]
            
            # Verify the extraction is balanced
            extracted_begins = len(re.findall(r'w:fldCharType="begin"', field_code_xml))
            extracted_ends = len(re.findall(r'w:fldCharType="end"', field_code_xml))
            
            if extracted_begins != extracted_ends:
                break
            
            # Extract the display text from the field code
            display_text = self._extract_field_display_text(field_code_xml)
            
            # Create placeholder with special Unicode chars to avoid conflicts
            placeholder = f"⟦CITE_{placeholder_idx}⟧"
            placeholder_idx += 1
            
            # Store mapping
            field_codes[placeholder] = field_code_xml
            
            logger.debug("Extracted field code %s displaying '%s'", placeholder, display_text)
            
            # Create a placeholder run to replace the field code in XML
            placeholder_run = f'<w:r><w:t xml:space="preserve">{placeholder}</w:t></w:r>'
            
            # Replace the field code with the placeholder
            modified_xml = modified_xml[:run_start] + placeholder_run + modified_xml[run_end:]
        
        # Final safety check: ensure no orphaned field code elements remain
        remaining_begins = len(re.findall(r'w:fldCharType="begin"', modified_xml))
        remaining_ends = len(re.findall(r'w:fldCharType="end"', modified_xml))
        
        if remaining_begins != remaining_ends:
            # Something went wrong - fall back to no field code extraction
            visible_text = self._extract_visible_text_from_para_xml(para_xml)
            return para_xml, {}, visible_text
        
        # Now extract visible text from the modified XML (which has placeholders)
        visible_text = self._extract_visible_text_from_para_xml(modified_xml)
        
        return modified_xml, field_codes, visible_text
    
    def _extract_visible_text_from_para_xml(self, para_xml: str) -> str:
        """Extract visible text from paragraph XML (excluding deleted text)."""
        # Remove deleted text
        para_without_del = re.sub(r'<w:delText[^>]*>.*?</w:delText>', '', para_xml, flags=re.DOTALL)
        # Extract all text
        text_parts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', para_without_del)
        return ''.join(text_parts)
    
    def _extract_field_display_text(self, field_code_xml: str) -> str:
        """
        Extract the display text from a field code XML fragment.
        
        The display text is the content of <w:t> elements between the
        "separate" marker and the "end" marker.
        """
        # Find the separate marker
        sep_match = re.search(
            r'<w:fldChar[^>]*w:fldCharType="separate"[^>]*/?>',
            field_code_xml
        )
        if not sep_match:
            # No separate marker, try to get any text
            text_parts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', field_code_xml)
            return ''.join(text_parts)
        
        # Extract text between separate and end
        after_sep = field_code_xml[sep_match.end():]
        end_match = re.search(
            r'<w:fldChar[^>]*w:fldCharType="end"[^>]*/?>',
            after_sep
        )
        if end_match:
            display_region = after_sep[:end_match.start()]
        else:
            display_region = after_sep
        
        text_parts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', display_region)
        return ''.join(text_parts)
    
    def _restore_field_codes(self, content_xml: str, field_codes: Dict[str, str]) -> str:
        """Restore field codes, guaranteeing the fragment stays structurally valid.

        M9e Layer B (safety net). ``_restore_field_codes_unsafe`` does the actual
        placeholder → field-XML substitution, but its regex run-matching can
        mis-nest when several EndNote fields in one paragraph interact — producing
        an unbalanced ``</w:r>`` and a document Word refuses to open. Here we
        restore fields **one at a time** and keep a restoration only if the result
        is still balanced. A field whose restoration would unbalance the paragraph
        is *cleanly degraded* to its citation display text (static, no live field)
        rather than emitting broken runs. Worst case is a citation that becomes
        static text — never an unopenable file.
        """
        result = content_xml
        for placeholder, original_xml in field_codes.items():
            if placeholder not in result:
                continue
            candidate = self._restore_field_codes_unsafe(result, {placeholder: original_xml})
            if _fragment_runs_balanced(candidate):
                result = candidate
                continue
            display = self._extract_field_display_text(original_xml)
            safe = html.escape(display) if display else ""
            result = result.replace(placeholder, safe)
            logger.warning(
                "Field code %s would unbalance paragraph runs on restore; kept the "
                "citation as static text %r (M9e safety net)",
                placeholder, display,
            )
        return result

    def _restore_field_codes_unsafe(self, content_xml: str, field_codes: Dict[str, str]) -> str:
        """
        Restore field code placeholders with original XML.
        
        Finds the <w:r> element containing each placeholder and replaces it entirely.
        For inserted text (inside <w:ins>), we need to also remove the <w:ins> wrapper
        to properly insert the field code.
        """
        result = content_xml
        
        for placeholder, original_xml in field_codes.items():
            occurrence = 0
            while placeholder in result:
                occurrence += 1
                # Find the placeholder position
                placeholder_pos = result.find(placeholder)
                
                # Find the <w:r> element that contains this placeholder
                run_start = result.rfind('<w:r', 0, placeholder_pos)
                if run_start == -1:
                    logger.warning("Field code #%d: could not find <w:r> for %s", occurrence, placeholder)
                    result = result.replace(placeholder, '', 1)
                    continue
                
                # Make sure we have the actual start of the tag
                tag_end = result.find('>', run_start)
                if tag_end == -1 or tag_end > placeholder_pos:
                    logger.warning("Field code #%d: tag structure issue for %s", occurrence, placeholder)
                    result = result.replace(placeholder, '', 1)
                    continue
                
                # Find the closing </w:r> after the placeholder
                run_end = result.find('</w:r>', placeholder_pos)
                if run_end == -1:
                    logger.warning("Field code #%d: could not find </w:r> for %s", occurrence, placeholder)
                    result = result.replace(placeholder, '', 1)
                    continue
                run_end += len('</w:r>')
                
                # Check if this run is inside a <w:ins> element (inserted text)
                # Look for <w:ins before the run_start
                ins_start = result.rfind('<w:ins', 0, run_start)
                ins_wrapper = None
                if ins_start != -1:
                    # Check if the </w:ins> is after our run
                    ins_end = result.find('</w:ins>', run_end)
                    if ins_end != -1:
                        # Verify the ins actually wraps this run (no other runs between)
                        between_ins_and_run = result[ins_start:run_start]
                        if '</w:r>' not in between_ins_and_run:
                            # This run is directly inside a <w:ins> - expand to include the wrapper
                            ins_end += len('</w:ins>')
                            ins_wrapper = (ins_start, ins_end)
                
                # Extract the full run XML
                run_xml = result[run_start:run_end]
                
                # Extract text from <w:t> element within this run
                t_match = re.search(r'<w:t[^>]*>([^<]*)</w:t>', run_xml)
                if not t_match:
                    logger.warning("Field code #%d: could not find <w:t> for %s", occurrence, placeholder)
                    result = result.replace(placeholder, '', 1)
                    continue
                
                full_text = t_match.group(1)
                ph_idx = full_text.find(placeholder)
                
                if ph_idx == -1:
                    logger.warning("Field code #%d: placeholder not in extracted text for %s", occurrence, placeholder)
                    result = result.replace(placeholder, '', 1)
                    continue
                
                before_text = full_text[:ph_idx]
                after_text = full_text[ph_idx + len(placeholder):]
                
                # Build replacement: text before (if any) + field code + text after (if any)
                replacement_parts = []
                
                if before_text:
                    replacement_parts.append(
                        f'<w:r><w:t xml:space="preserve">{html.escape(before_text)}</w:t></w:r>'
                    )
                
                replacement_parts.append(original_xml)
                
                if after_text:
                    replacement_parts.append(
                        f'<w:r><w:t xml:space="preserve">{html.escape(after_text)}</w:t></w:r>'
                    )
                
                replacement = ''.join(replacement_parts)
                
                # If inside <w:ins>, replace the entire ins wrapper
                if ins_wrapper:
                    start_pos, end_pos = ins_wrapper
                    logger.debug("Field code #%d: restored %s (was inside <w:ins>)", occurrence, placeholder)
                    result = result[:start_pos] + replacement + result[end_pos:]
                else:
                    logger.debug("Field code #%d: restored %s", occurrence, placeholder)
                    result = result[:run_start] + replacement + result[run_end:]
        
        return result
    
    def _split_text_at_field_code_placeholders(
        self,
        text: str,
        field_codes: Dict[str, str]
    ) -> List[Tuple[str, str, int]]:
        """
        Split text into segments separated by field code placeholders.

        Returns a list of (seg_type, seg_text, orig_advance) tuples where:
        - seg_type is 'text' or 'placeholder'
        - seg_text is the actual text content
        - orig_advance is how far to advance in the ORIGINAL (display) text;
          for regular text this equals len(seg_text), but for placeholders
          it equals the display text length (e.g., 3 for "[9]" even though
          the placeholder "[CITATION_13]" is 14 chars)
        """
        segments: List[Tuple[str, str, int]] = []
        pos = 0
        for m in re.finditer(r'\[CITATION_\d+\]', text):
            if m.start() > pos:
                chunk = text[pos:m.start()]
                segments.append(('text', chunk, len(chunk)))
            placeholder = m.group(0)
            if placeholder in field_codes:
                display = self._extract_field_display_text(field_codes[placeholder])
                display_len = len(display) if display else len(placeholder)
            else:
                display_len = len(placeholder)
            segments.append(('placeholder', placeholder, display_len))
            pos = m.end()
        if pos < len(text):
            chunk = text[pos:]
            segments.append(('text', chunk, len(chunk)))
        return segments

    def _inject_placeholders_into_text(
        self, 
        text: str, 
        field_codes: Dict[str, str]
    ) -> str:
        """
        Inject placeholders into text where citation display text appears.
        
        This is used to make the model's plain_text match the placeholder format
        so that the diff treats citations as unchanged (EQUAL).
        
        Args:
            text: Plain text (may contain citation display text like "[1]")
            field_codes: Dict mapping placeholder -> field code XML
            
        Returns:
            Text with citation display text replaced by placeholders
        """
        result = text
        for placeholder, field_xml in field_codes.items():
            display_text = self._extract_field_display_text(field_xml)
            if display_text and display_text in result:
                result = result.replace(display_text, placeholder)
                logger.debug("Injected %s for '%s'", placeholder, display_text)
        return result
    
    # =========================================================================
    # STRUCTURAL CHANGE HANDLING (Phase 5)
    # =========================================================================
    
