"""HTML/formatting-to-Word-runs conversion."""

import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

from .paragraph import RunFormatting

from .serializer_common import _sanitize_for_xml

class SerializerFormattingMixin:
    """Mixin providing serializer methods."""

    def _extract_runs_with_formatting(self, para_content: str) -> List[Dict]:
        """
        Extract runs from paragraph content with their formatting.
        
        Returns a list of dicts, each containing:
        - 'text': The text content of the run
        - 'rPr': The run properties XML (formatting)
        - 'start_pos': Character position where this run starts
        - 'end_pos': Character position where this run ends
        
        This allows mapping diff operations back to original runs and preserving formatting.
        """
        runs = []
        current_pos = 0
        
        # Remove deletion content (shouldn't be in visible text)
        para_without_del = re.sub(
            r'<w:del[^>]*>.*?</w:del>',
            '',
            para_content,
            flags=re.DOTALL
        )
        
        # Find all runs (including those inside w:ins)
        run_pattern = re.compile(r'<w:r(?:\s[^>]*)?>.*?</w:r>', re.DOTALL)
        
        for run_match in run_pattern.finditer(para_without_del):
            run_xml = run_match.group(0)
            
            # Skip commentReference runs (they don't contain visible text)
            if '<w:commentReference' in run_xml:
                continue
            
            # Skip annotationRef runs
            if '<w:annotationRef' in run_xml:
                continue
            
            # Extract run properties (formatting)
            rPr_match = re.search(r'<w:rPr[^>]*>.*?</w:rPr>', run_xml, re.DOTALL)
            rPr = rPr_match.group(0) if rPr_match else ''
            
            # Extract text from <w:t> elements in this run
            text_parts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', run_xml)
            run_text = ''.join(text_parts)
            
            # Also check for <w:br/> (line breaks)
            if '<w:br' in run_xml:
                run_text = run_text + '\n'
            
            if run_text:  # Only add runs that have text
                # Parse rPr into a formatting set for comparison
                formatting = self._parse_rPr_to_formatting_set(rPr)
                runs.append({
                    'text': run_text,
                    'rPr': rPr,
                    'formatting': formatting,
                    'start_pos': current_pos,
                    'end_pos': current_pos + len(run_text)
                })
                current_pos += len(run_text)
        
        return runs
    
    def _parse_rPr_to_formatting_set(self, rPr_xml: str) -> set:
        """
        Parse Word run properties XML into a set of formatting flags.
        
        Returns a set containing any of: 'bold', 'italic', 'underline', 'superscript', 'subscript'
        """
        formatting = set()
        if not rPr_xml:
            return formatting
        
        # Check for bold
        if '<w:b/>' in rPr_xml or '<w:b ' in rPr_xml:
            formatting.add('bold')
        
        # Check for italic
        if '<w:i/>' in rPr_xml or '<w:i ' in rPr_xml:
            formatting.add('italic')
        
        # Check for underline
        if '<w:u ' in rPr_xml or '<w:u/>' in rPr_xml:
            formatting.add('underline')
        
        # Check for superscript/subscript via vertAlign
        if 'w:val="superscript"' in rPr_xml:
            formatting.add('superscript')
        elif 'w:val="subscript"' in rPr_xml:
            formatting.add('subscript')
        
        return formatting
    
    def _formatting_set_to_rPr_xml(self, formatting: set) -> str:
        """
        Convert a formatting set to Word run properties XML.
        
        Args:
            formatting: Set containing any of: 'bold', 'italic', 'underline', 'superscript', 'subscript'
            
        Returns:
            XML string for <w:rPr> content (without the rPr tags themselves)
        """
        parts = []
        if 'bold' in formatting:
            parts.append('<w:b/>')
        if 'italic' in formatting:
            parts.append('<w:i/>')
        if 'underline' in formatting:
            parts.append('<w:u w:val="single"/>')
        if 'superscript' in formatting:
            parts.append('<w:vertAlign w:val="superscript"/>')
        elif 'subscript' in formatting:
            parts.append('<w:vertAlign w:val="subscript"/>')
        return ''.join(parts)
    
    def _generate_rPrChange_run(
        self,
        text: str,
        old_formatting: set,
        new_formatting: set,
        rev_id: int,
        author: str,
        timestamp: str,
        rsid: str
    ) -> str:
        """
        Generate a Word run with tracked formatting change using <w:rPrChange>.
        
        This is used when text content is identical but formatting differs.
        The run will show the NEW formatting but record the OLD formatting
        inside <w:rPrChange> for tracking.
        
        Args:
            text: The text content
            old_formatting: Set of formatting flags from original text
            new_formatting: Set of formatting flags from revised text
            rev_id: Revision ID for the change
            author: Author name
            timestamp: ISO timestamp
            rsid: Revision Save ID
            
        Returns:
            Word XML string for the run with tracked formatting change
        """
        safe_author = html.escape(author)
        safe_text = html.escape(_sanitize_for_xml(text))

        # Build the new formatting properties
        new_rPr_content = self._formatting_set_to_rPr_xml(new_formatting)
        
        # Build the old formatting properties (stored in rPrChange)
        old_rPr_content = self._formatting_set_to_rPr_xml(old_formatting)
        
        # Construct the rPrChange element
        rPrChange = (
            f'<w:rPrChange w:id="{rev_id}" w:author="{safe_author}" w:date="{timestamp}">'
            f'<w:rPr>{old_rPr_content}</w:rPr>'
            f'</w:rPrChange>'
        )
        
        # Build the complete run
        # The rPr contains: new formatting + rPrChange (which contains old formatting)
        run = (
            f'<w:r w:rsidR="{rsid}">'
            f'<w:rPr>{new_rPr_content}{rPrChange}</w:rPr>'
            f'<w:t xml:space="preserve">{safe_text}</w:t>'
            f'</w:r>'
        )
        
        return run
    
    def _parse_html_formatting_segments(self, html_text: str) -> List[Tuple[str, set]]:
        """
        Parse HTML text into segments with their formatting.
        
        Extracts text and its formatting (bold, italic, etc.) from HTML.
        
        Args:
            html_text: HTML string (e.g., "<b>bold</b> normal <i>italic</i>")
            
        Returns:
            List of (text, formatting_set) tuples
        """
        segments = []
        
        if not html_text:
            return segments
        
        # Use regex to parse HTML tags and text
        # Track current formatting state
        current_formatting = set()
        current_text = []
        
        # Simple state machine to parse HTML
        pos = 0
        while pos < len(html_text):
            # Check for opening tags
            tag_match = re.match(r'<(b|i|u|s|sub|sup|strong|em)(?:\s[^>]*)?>', html_text[pos:], re.IGNORECASE)
            if tag_match:
                # Flush current text if any
                if current_text:
                    text = ''.join(current_text)
                    if text:
                        segments.append((text, current_formatting.copy()))
                    current_text = []
                
                # Add formatting
                tag_name = tag_match.group(1).lower()
                if tag_name in ('b', 'strong'):
                    current_formatting.add('bold')
                elif tag_name in ('i', 'em'):
                    current_formatting.add('italic')
                elif tag_name == 'u':
                    current_formatting.add('underline')
                elif tag_name == 's':
                    current_formatting.add('strike')
                elif tag_name == 'sup':
                    current_formatting.add('superscript')
                elif tag_name == 'sub':
                    current_formatting.add('subscript')
                
                pos += len(tag_match.group(0))
                continue
            
            # Check for closing tags
            close_match = re.match(r'</(b|i|u|s|sub|sup|strong|em)>', html_text[pos:], re.IGNORECASE)
            if close_match:
                # Flush current text if any
                if current_text:
                    text = ''.join(current_text)
                    if text:
                        segments.append((text, current_formatting.copy()))
                    current_text = []
                
                # Remove formatting
                tag_name = close_match.group(1).lower()
                if tag_name in ('b', 'strong'):
                    current_formatting.discard('bold')
                elif tag_name in ('i', 'em'):
                    current_formatting.discard('italic')
                elif tag_name == 'u':
                    current_formatting.discard('underline')
                elif tag_name == 's':
                    current_formatting.discard('strike')
                elif tag_name == 'sup':
                    current_formatting.discard('superscript')
                elif tag_name == 'sub':
                    current_formatting.discard('subscript')
                
                pos += len(close_match.group(0))
                continue
            
            # Check for other tags (skip them, but preserve their text content)
            other_tag_match = re.match(r'<[^>]+>', html_text[pos:])
            if other_tag_match:
                pos += len(other_tag_match.group(0))
                continue
            
            # Check for HTML entities
            entity_match = re.match(r'&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);', html_text[pos:])
            if entity_match:
                entity = entity_match.group(0)
                # Decode common entities
                decoded = html.unescape(entity)
                current_text.append(decoded)
                pos += len(entity)
                continue
            
            # Regular character
            current_text.append(html_text[pos])
            pos += 1
        
        # Flush remaining text
        if current_text:
            text = ''.join(current_text)
            if text:
                segments.append((text, current_formatting.copy()))
        
        return segments
    
    def _get_formatting_at_position(
        self,
        formatting_segments: List[Tuple[str, set]],
        position: int
    ) -> set:
        """
        Get the formatting that applies at a given character position.
        
        Args:
            formatting_segments: List of (text, formatting_set) from _parse_html_formatting_segments
            position: Character position (0-based)
            
        Returns:
            Set of formatting flags at that position
        """
        current_pos = 0
        for text, formatting in formatting_segments:
            seg_end = current_pos + len(text)
            if current_pos <= position < seg_end:
                return formatting
            current_pos = seg_end
        
        # Position beyond text - return empty formatting
        return set()
    
    def _generate_runs_for_text_range(
        self,
        original_runs: List[Dict],
        text: str,
        start_pos: int,
        rsid: str,
        is_delete: bool = False
    ) -> str:
        """
        Generate Word runs for a text range, preserving original formatting.
        
        If is_delete is True, wraps runs in <w:del> elements.
        Returns the XML string for the runs.
        """
        result_parts = []
        text_pos = 0
        orig_pos = start_pos
        
        while text_pos < len(text):
            # Find which original run covers this position
            matching_run = None
            for run in original_runs:
                if run['start_pos'] <= orig_pos < run['end_pos']:
                    matching_run = run
                    break
            
            if matching_run:
                # Calculate how much text we can take from this run
                run_remaining = matching_run['end_pos'] - orig_pos
                text_remaining = len(text) - text_pos
                chunk_len = min(run_remaining, text_remaining)
                
                chunk_text = text[text_pos:text_pos + chunk_len]
                safe_text = html.escape(_sanitize_for_xml(chunk_text))
                rPr = matching_run['rPr']
                
                if is_delete:
                    run_xml = (
                        f'<w:r w:rsidDel="{rsid}">'
                        f'{rPr}'
                        f'<w:delText xml:space="preserve">{safe_text}</w:delText>'
                        f'</w:r>'
                    )
                else:
                    run_xml = (
                        f'<w:r w:rsidR="{rsid}">'
                        f'{rPr}'
                        f'<w:t xml:space="preserve">{safe_text}</w:t>'
                        f'</w:r>'
                    )
                
                result_parts.append(run_xml)
                text_pos += chunk_len
                orig_pos += chunk_len
            else:
                # No matching run found - use plain formatting for remaining text
                remaining_text = text[text_pos:]
                safe_text = html.escape(_sanitize_for_xml(remaining_text))
                
                if is_delete:
                    run_xml = (
                        f'<w:r w:rsidDel="{rsid}">'
                        f'<w:delText xml:space="preserve">{safe_text}</w:delText>'
                        f'</w:r>'
                    )
                else:
                    run_xml = (
                        f'<w:r w:rsidR="{rsid}">'
                        f'<w:t xml:space="preserve">{safe_text}</w:t>'
                        f'</w:r>'
                    )
                
                result_parts.append(run_xml)
                break
        
        return ''.join(result_parts)
    
    def _generate_equal_runs_with_formatting(
        self,
        original_runs: List[Dict],
        text: str,
        original_start_pos: int,
        revised_start_pos: int,
        revised_formatting_segments: List[Tuple[str, set]],
        rsid: str,
        author: str,
        timestamp: str,
        next_rev_id: int
    ) -> str:
        """
        Generate runs for EQUAL text, checking for formatting changes.
        
        For each character position:
        - Get original formatting from original_runs
        - Get revised formatting from revised_formatting_segments
        - If different, generate rPrChange; otherwise preserve original run
        
        Args:
            original_runs: Original runs with formatting
            text: The EQUAL text
            original_start_pos: Position in original text
            revised_start_pos: Position in revised text
            revised_formatting_segments: Parsed HTML formatting
            rsid: Revision save ID
            author: Author name (already escaped)
            timestamp: ISO timestamp string
            next_rev_id: Next available revision ID
            
        Returns:
            XML string for the runs (may contain rPrChange elements)
        """
        result_parts = []
        text_pos = 0
        orig_pos = original_start_pos
        rev_pos = revised_start_pos
        current_rev_id = next_rev_id
        
        while text_pos < len(text):
            # Find which original run covers this position
            matching_run = None
            for run in original_runs:
                if run['start_pos'] <= orig_pos < run['end_pos']:
                    matching_run = run
                    break
            
            if matching_run:
                # Calculate how much text we can take from this run
                run_remaining = matching_run['end_pos'] - orig_pos
                text_remaining = len(text) - text_pos
                
                # Also check formatting boundaries in revised text
                # Find the extent of consistent formatting in revised text
                revised_formatting = self._get_formatting_at_position(
                    revised_formatting_segments, rev_pos
                )
                
                # Find how far this formatting extends
                formatting_extent = 1
                for i in range(1, text_remaining + 1):
                    if self._get_formatting_at_position(revised_formatting_segments, rev_pos + i) != revised_formatting:
                        break
                    formatting_extent = i + 1
                
                chunk_len = min(run_remaining, text_remaining, formatting_extent)
                
                chunk_text = text[text_pos:text_pos + chunk_len]
                safe_text = html.escape(_sanitize_for_xml(chunk_text))
                original_formatting = matching_run.get('formatting', set())
                
                # Compare formatting
                if original_formatting != revised_formatting:
                    # Formatting differs - generate rPrChange
                    run_xml = self._generate_rPrChange_run(
                        chunk_text, original_formatting, revised_formatting,
                        current_rev_id, author, timestamp, rsid
                    )
                    current_rev_id += 1
                else:
                    # Same formatting - preserve original
                    rPr = matching_run['rPr']
                    run_xml = (
                        f'<w:r w:rsidR="{rsid}">'
                        f'{rPr}'
                        f'<w:t xml:space="preserve">{safe_text}</w:t>'
                        f'</w:r>'
                    )
                
                result_parts.append(run_xml)
                text_pos += chunk_len
                orig_pos += chunk_len
                rev_pos += chunk_len
            else:
                # No matching original run - use revised formatting
                remaining_text = text[text_pos:]
                revised_formatting = self._get_formatting_at_position(
                    revised_formatting_segments, rev_pos
                )
                
                if revised_formatting:
                    # Apply revised formatting with rPrChange (original was empty)
                    run_xml = self._generate_rPrChange_run(
                        remaining_text, set(), revised_formatting,
                        current_rev_id, author, timestamp, rsid
                    )
                    current_rev_id += 1
                else:
                    # No formatting - plain run
                    safe_text = html.escape(_sanitize_for_xml(remaining_text))
                    run_xml = (
                        f'<w:r w:rsidR="{rsid}">'
                        f'<w:t xml:space="preserve">{safe_text}</w:t>'
                        f'</w:r>'
                    )
                
                result_parts.append(run_xml)
                break
        
        return ''.join(result_parts)
    
    def _generate_insert_runs_with_formatting(
        self,
        text: str,
        revised_start_pos: int,
        revised_formatting_segments: List[Tuple[str, set]],
        rsid: str,
        author: str,
        timestamp: str,
        next_rev_id: int
    ) -> str:
        """
        Generate runs for INSERT text with user formatting.
        
        The inserted text is wrapped in <w:ins>. If the user applied formatting,
        we add <w:rPr> with the formatting AND <w:rPrChange> to track that the
        formatting was added (original was no formatting).
        
        Args:
            text: The INSERT text
            revised_start_pos: Position in revised text
            revised_formatting_segments: Parsed HTML formatting
            rsid: Revision save ID
            author: Author name (already escaped)
            timestamp: ISO timestamp string
            next_rev_id: Next available revision ID
            
        Returns:
            XML string with <w:ins> elements (may contain rPrChange for formatting)
        """
        result_parts = []
        text_pos = 0
        rev_pos = revised_start_pos
        current_rev_id = next_rev_id
        
        while text_pos < len(text):
            # Get formatting at this position
            formatting = self._get_formatting_at_position(revised_formatting_segments, rev_pos)
            
            # Find how far this formatting extends
            text_remaining = len(text) - text_pos
            formatting_extent = 1
            for i in range(1, text_remaining + 1):
                if self._get_formatting_at_position(revised_formatting_segments, rev_pos + i) != formatting:
                    break
                formatting_extent = i + 1
            
            chunk_text = text[text_pos:text_pos + formatting_extent]
            safe_text = html.escape(_sanitize_for_xml(chunk_text))
            
            if formatting:
                # User applied formatting - include rPrChange to track it
                # The rPrChange shows original was empty (no formatting)
                rPr_content = self._formatting_set_to_rPr_xml(formatting)
                rPrChange = (
                    f'<w:rPrChange w:id="{current_rev_id}" w:author="{author}" w:date="{timestamp}">'
                    f'<w:rPr/>'  # Original formatting was empty
                    f'</w:rPrChange>'
                )
                current_rev_id += 1
                
                run_xml = (
                    f'<w:ins w:id="{current_rev_id}" w:author="{author}" w:date="{timestamp}">'
                    f'<w:r w:rsidR="{rsid}">'
                    f'<w:rPr>{rPr_content}{rPrChange}</w:rPr>'
                    f'<w:t xml:space="preserve">{safe_text}</w:t>'
                    f'</w:r>'
                    f'</w:ins>'
                )
                current_rev_id += 1
            else:
                # No formatting - plain insert
                run_xml = (
                    f'<w:ins w:id="{current_rev_id}" w:author="{author}" w:date="{timestamp}">'
                    f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
                    f'</w:ins>'
                )
                current_rev_id += 1
            
            result_parts.append(run_xml)
            text_pos += formatting_extent
            rev_pos += formatting_extent
        
        return ''.join(result_parts)
    
