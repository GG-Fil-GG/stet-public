"""
Chat types and data structures for the chat mode feature.

This module contains the data structures used for conversational
iteration on LLM suggestions.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class ChatMessage:
    """A single message in the chat history."""
    role: str  # "user", "assistant", "system"
    content: str  # The message text displayed in chat
    timestamp: str  # ISO format datetime
    revision_updated: bool = False  # True if this message updated revised_text
    reply_updated: bool = False  # True if this message updated response
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatMessage':
        """Create ChatMessage from dictionary."""
        return cls(
            role=data.get('role', 'user'),
            content=data.get('content', ''),
            timestamp=data.get('timestamp', ''),
            revision_updated=data.get('revision_updated', False),
            reply_updated=data.get('reply_updated', False)
        )
    
    @classmethod
    def system_message(cls, content: str) -> 'ChatMessage':
        """Create a system message with current timestamp."""
        return cls(
            role='system',
            content=content,
            timestamp=datetime.now().isoformat()
        )
    
    @classmethod
    def user_message(cls, content: str) -> 'ChatMessage':
        """Create a user message with current timestamp."""
        return cls(
            role='user',
            content=content,
            timestamp=datetime.now().isoformat()
        )
    
    @classmethod
    def assistant_message(
        cls, 
        content: str, 
        revision_updated: bool = False,
        reply_updated: bool = False
    ) -> 'ChatMessage':
        """Create an assistant message with current timestamp."""
        return cls(
            role='assistant',
            content=content,
            timestamp=datetime.now().isoformat(),
            revision_updated=revision_updated,
            reply_updated=reply_updated
        )


@dataclass
class ChatSnapshot:
    """
    Snapshot of suggestion state before entering chat mode.
    Used to enable "Discard" functionality that reverts to original state.
    """
    revised_text: str
    response: str
    rationale: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatSnapshot':
        """Create ChatSnapshot from dictionary."""
        return cls(
            revised_text=data.get('revised_text', ''),
            response=data.get('response', ''),
            rationale=data.get('rationale')
        )


def serialize_chat_history(chat_history: Dict[str, List[ChatMessage]]) -> Dict[str, List[Dict]]:
    """Convert chat history to JSON-serializable format."""
    return {
        thread_id: [msg.to_dict() for msg in messages]
        for thread_id, messages in chat_history.items()
    }


def deserialize_chat_history(data: Dict[str, List[Dict]]) -> Dict[str, List[ChatMessage]]:
    """Restore chat history from JSON data."""
    return {
        thread_id: [ChatMessage.from_dict(msg) for msg in messages]
        for thread_id, messages in data.items()
    }


def serialize_chat_snapshots(snapshots: Dict[str, ChatSnapshot]) -> Dict[str, Dict]:
    """Convert chat snapshots to JSON-serializable format."""
    return {
        thread_id: snapshot.to_dict()
        for thread_id, snapshot in snapshots.items()
    }


def deserialize_chat_snapshots(data: Dict[str, Dict]) -> Dict[str, ChatSnapshot]:
    """Restore chat snapshots from JSON data."""
    return {
        thread_id: ChatSnapshot.from_dict(snapshot)
        for thread_id, snapshot in data.items()
    }
