"""
Stet Custom Exceptions

Centralized exception classes for consistent error handling across the application.
These replace scattered print statements, generic exceptions, and tuple returns.

Usage:
    from src.exceptions import CommentExtractionError, DocumentWriteError
    
    try:
        extractor.extract_comments(file)
    except CommentExtractionError as e:
        logger.error(f"Failed to extract comments: {e}")
"""

from typing import Optional


class StetError(Exception):
    """
    Base exception for all Stet application errors.
    
    All custom exceptions inherit from this, allowing catch-all handling:
        try:
            ...
        except StetError as e:
            # Handle any Stet-specific error
    """
    
    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)
    
    def __str__(self):
        if self.details:
            return f"{self.message}\nDetails: {self.details}"
        return self.message


# =============================================================================
# DOCUMENT PROCESSING ERRORS
# =============================================================================

class CommentExtractionError(StetError):
    """
    Raised when comment extraction from a DOCX file fails.
    
    Examples:
        - Invalid DOCX file format
        - Missing required XML files (comments.xml, document.xml)
        - Malformed XML structure
        - Comment-anchor mismatch
    """
    pass


class DocumentWriteError(StetError):
    """
    Raised when writing to a DOCX file fails.
    
    Examples:
        - Failed to insert reply comment
        - Failed to apply tracked changes
        - XML serialization error
        - File system write error
    """
    
    def __init__(
        self, 
        message: str, 
        details: Optional[str] = None,
        thread_id: Optional[str] = None
    ):
        super().__init__(message, details)
        self.thread_id = thread_id


class DocumentParseError(StetError):
    """
    Raised when parsing document structure fails.
    
    Examples:
        - Failed to parse paragraph structure
        - Failed to extract field codes
        - Failed to identify text ranges
    """
    pass


# =============================================================================
# LLM ERRORS
# =============================================================================

class LLMError(StetError):
    """
    Base class for LLM-related errors.
    """
    pass


class LLMConnectionError(LLMError):
    """
    Raised when connection to LLM service fails.
    
    Examples:
        - API key invalid or missing
        - Network timeout
        - Service unavailable
    """
    
    def __init__(
        self, 
        message: str, 
        provider: Optional[str] = None,
        details: Optional[str] = None
    ):
        super().__init__(message, details)
        self.provider = provider


class LLMResponseError(LLMError):
    """
    Raised when LLM response is invalid or unparseable.
    
    Examples:
        - Response not valid JSON
        - Missing required fields in response
        - Unexpected response format
    """
    
    def __init__(
        self, 
        message: str, 
        raw_response: Optional[str] = None,
        details: Optional[str] = None
    ):
        super().__init__(message, details)
        self.raw_response = raw_response


class LLMRateLimitError(LLMError):
    """
    Raised when LLM rate limit is exceeded.
    """
    
    def __init__(
        self, 
        message: str, 
        retry_after: Optional[int] = None,
        details: Optional[str] = None
    ):
        super().__init__(message, details)
        self.retry_after = retry_after  # Seconds until retry is allowed


# =============================================================================
# SESSION ERRORS
# =============================================================================

class SessionError(StetError):
    """
    Base class for session-related errors.
    """
    pass


class SessionNotFoundError(SessionError):
    """
    Raised when requested session does not exist.
    """
    
    def __init__(self, session_id: str):
        super().__init__(f"Session not found: {session_id}")
        self.session_id = session_id


class SessionCorruptedError(SessionError):
    """
    Raised when session data is corrupted or invalid.
    
    Examples:
        - JSON parse error
        - Missing required fields
        - Invalid data types
    """
    
    def __init__(self, session_id: str, details: Optional[str] = None):
        super().__init__(f"Session corrupted: {session_id}", details)
        self.session_id = session_id


# =============================================================================
# ATTACHMENT ERRORS
# =============================================================================

class AttachmentError(StetError):
    """
    Base class for file attachment errors.
    """
    pass


class AttachmentParseError(AttachmentError):
    """
    Raised when parsing an attached file fails.
    
    Examples:
        - Invalid PDF structure
        - Unsupported file format
        - Encrypted or password-protected file
    """
    
    def __init__(
        self, 
        message: str, 
        filename: Optional[str] = None,
        details: Optional[str] = None
    ):
        super().__init__(message, details)
        self.filename = filename


class AttachmentTooLargeError(AttachmentError):
    """
    Raised when attachment exceeds size limits.
    """
    
    def __init__(
        self, 
        filename: str, 
        size_bytes: int, 
        max_bytes: int
    ):
        super().__init__(
            f"Attachment too large: {filename} ({size_bytes} bytes, max {max_bytes})"
        )
        self.filename = filename
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes


# =============================================================================
# VALIDATION ERRORS
# =============================================================================

class ValidationError(StetError):
    """
    Raised when input validation fails.
    
    Examples:
        - Invalid thread ID format
        - Missing required parameters
        - Invalid file type
    """
    
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.field = field
