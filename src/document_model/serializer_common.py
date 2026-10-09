"""Shared utilities for document serialization."""

import html


def _sanitize_for_xml(text: str) -> str:
    """
    Remove characters that are invalid in XML 1.0 so document.xml stays valid.
    Keeps tab (0x09), newline (0x0A), carriage return (0x0D); strips other control chars (0x00-0x0C, 0x0E-0x1F).
    Preserves Unicode like ≥ (U+2265) and all normal printable characters.
    """
    if not text:
        return text
    result = []
    for c in text:
        code = ord(c)
        if code < 0x20 and code not in (0x09, 0x0A, 0x0D):
            continue
        if 0xD800 <= code <= 0xDFFF:
            continue  # Surrogate halves invalid in XML
        result.append(c)
    return ''.join(result)
