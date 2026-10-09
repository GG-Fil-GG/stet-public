"""
RTF Parser for extracting plain text from Rich Text Format documents.

Uses striprtf for lightweight, pure-Python text extraction. RTF structure
(tables, styles, embedded objects) is not reconstructed — plain text is
sufficient for reference reading (Stage 1, Milestone 8).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from striprtf.striprtf import rtf_to_text

# Decode order: UTF-8 first matters for non-Latin scripts (e.g. Japanese RTF).
_ENCODINGS = ("utf-8", "latin-1", "cp1252")

# Safety net so a huge file cannot blow the agent's context window.
MAX_CHARS = 200_000

_TRUNCATION_MARKER = "\n\n[... truncated]"


@dataclass
class RtfParseResult:
    """Result of parsing an RTF document."""
    filename: str
    text: str
    error: Optional[str] = None

    def to_markdown(self) -> str:
        """Convert extracted content to an agent-readable string."""
        if self.error:
            return f"[Error parsing RTF: {self.error}]"
        body = self.text.strip()
        return f"=== RTF: {self.filename} ===\n\n{body}"

    def get_token_estimate(self, chars_per_token: float = 4.0) -> int:
        """Estimate token count based on character count."""
        return int(len(self.to_markdown()) / chars_per_token)


class RtfParser:
    """Parser for extracting plain text from RTF documents."""

    def parse(self, file_path: str) -> RtfParseResult:
        """Parse an RTF file and extract its plain text.

        Never raises for malformed input — returns a result with ``error`` set.
        """
        path = Path(file_path)
        filename = path.name

        try:
            raw = path.read_bytes()
        except Exception as e:  # noqa: BLE001 - surface IO failures as error
            return RtfParseResult(filename=filename, text="", error=str(e))

        decoded = None
        last_error: Optional[Exception] = None
        for encoding in _ENCODINGS:
            try:
                decoded = raw.decode(encoding)
                break
            except Exception as e:  # noqa: BLE001 - try the next encoding
                last_error = e
                continue

        if decoded is None:
            return RtfParseResult(
                filename=filename,
                text="",
                error=str(last_error or "Could not decode RTF file"),
            )

        try:
            text = rtf_to_text(decoded)
        except Exception as e:  # noqa: BLE001 - surface parse failures as error
            return RtfParseResult(filename=filename, text="", error=str(e))

        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + _TRUNCATION_MARKER

        return RtfParseResult(filename=filename, text=text)
