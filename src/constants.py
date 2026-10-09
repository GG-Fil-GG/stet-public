"""
Stet Application Constants

Centralized configuration values and constants used across the application.
This file eliminates magic strings and hardcoded values scattered throughout the codebase.
"""

from enum import Enum
from typing import Final


# =============================================================================
# THREAD STATUS
# =============================================================================

class ThreadStatus(str, Enum):
    """
    Status of a comment thread in the review workflow.
    
    Inherits from str to ensure JSON serialization works seamlessly.
    Usage: ThreadStatus.PENDING.value == "pending"
    """
    PENDING = "pending"    # No suggestion generated yet, or suggestion not reviewed
    ACCEPTED = "accepted"  # User accepted the suggestion
    SKIPPED = "skipped"    # User skipped this thread


# =============================================================================
# DEFAULT LLM INSTRUCTIONS
# =============================================================================

DEFAULT_INSTRUCTIONS: Final[str] = """You are an expert Medical Writer working on a scientific manuscript for a peer-reviewed journal.

Your task is to address a reviewer's comment by:
1. REVISING the target paragraph to address the comment
2. DRAFTING a professional reply to the reviewer

IMPORTANT GUIDELINES:
- Preserve scientific accuracy and formal academic tone
- Keep revisions minimal but sufficient to fully address the concern
- Your reply should be concise, polite, and professional
- If the original comment is in Japanese, still write your reply in English
- Do not change content that is not relevant to the comment"""


# =============================================================================
# COMMENT EXTRACTION THRESHOLDS
# =============================================================================
# These control how much context is shown around referenced text

class ExtractionThresholds:
    """Thresholds for determining how to display referenced text with context."""
    
    # For single character references, show the containing word if under this length
    WORD_CHAR_LIMIT: Final[int] = 25
    
    # Show sentence-level context if word is this long or more
    SENTENCE_CHAR_LIMIT: Final[int] = 120
    
    # Maximum paragraph length to show as full context
    PARAGRAPH_CHAR_LIMIT: Final[int] = 300
    
    # Text is considered "too short" if under these thresholds (needs context expansion)
    MIN_TEXT_CHARS: Final[int] = 15
    MIN_TEXT_WORDS: Final[int] = 3


# =============================================================================
# CONTEXT SETTINGS DEFAULTS
# =============================================================================

class ContextDefaults:
    """Default settings for context expansion around referenced text."""
    
    # Number of paragraphs to show before/after referenced text
    PARAGRAPHS_BEFORE: Final[int] = 2
    PARAGRAPHS_AFTER: Final[int] = 2
    
    # Offset adjustments for reference start/end
    REF_START_OFFSET: Final[int] = 0
    REF_END_OFFSET: Final[int] = 0
    
    # Maximum context expansion limit (prevent runaway expansion)
    MAX_CONTEXT_PARAGRAPHS: Final[int] = 10


# =============================================================================
# CHAT SETTINGS
# =============================================================================

class ChatSettings:
    """Configuration for chat/conversation features."""
    
    # Maximum number of messages to include in chat history for LLM context
    MAX_CHAT_MESSAGES: Final[int] = 20


# =============================================================================
# APPLICATION METADATA
# =============================================================================

APP_NAME: Final[str] = "Stet"
APP_VERSION: Final[str] = "2.0.0"
APP_DESCRIPTION: Final[str] = "AI-powered tool for addressing reviewer comments"
