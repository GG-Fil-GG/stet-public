"""
Utility functions for the Document Model.

Includes ID generators with proper constraints and collision checking.
"""

import uuid
import random
from typing import Set


def generate_valid_para_id(existing_ids: Set[str], max_attempts: int = 100) -> str:
    """
    Generate a unique, valid w14:paraId value.
    
    CRITICAL: First character MUST be 0-7. Word interprets paraId as a signed
    32-bit integer and rejects values >= 0x80000000 (first char 8-F).
    
    This constraint applies ONLY to paraId. Other hex IDs (textId, durableId,
    rsidR) can use the full 0-F range.
    
    Args:
        existing_ids: Set of all paraIds already in the document
        max_attempts: Maximum generation attempts before raising error
    
    Returns:
        A unique 8-character uppercase hex string with first char 0-7
    
    Raises:
        RuntimeError: If unable to generate unique ID after max_attempts
    
    Validated 2026-02-16: Tested all 16 first-char values (0-F) across 4 comments.
    """
    for _ in range(max_attempts):
        raw = uuid.uuid4().hex[:8].upper()
        first_char = raw[0]
        if first_char in '89ABCDEF':
            # Map 8-F to 0-7 by taking modulo 8
            new_first = str(int(first_char, 16) % 8)
            raw = new_first + raw[1:]
        if raw not in existing_ids:
            return raw
    raise RuntimeError(f"Failed to generate unique paraId after {max_attempts} attempts")


def generate_hex_id(existing_ids: Set[str], max_attempts: int = 100) -> str:
    """
    Generate a unique random hex ID with no first-char constraint.
    
    Use for: textId, durableId, rsidR
    Do NOT use for: paraId (use generate_valid_para_id instead)
    
    Args:
        existing_ids: Set of existing IDs of this type in the document
        max_attempts: Maximum generation attempts before raising error
    
    Returns:
        A unique 8-character uppercase hex string
    
    Raises:
        RuntimeError: If unable to generate unique ID after max_attempts
    """
    for _ in range(max_attempts):
        new_id = uuid.uuid4().hex[:8].upper()
        if new_id not in existing_ids:
            return new_id
    raise RuntimeError(f"Failed to generate unique hex ID after {max_attempts} attempts")


def generate_comment_id(existing_ids: Set[int], max_attempts: int = 1000) -> str:
    """
    Generate a unique comment ID (integer as string).
    
    Word uses sequential IDs but random IDs work fine for threading.
    We use random to avoid conflicts with existing IDs.
    
    Args:
        existing_ids: Set of existing comment IDs (as integers)
        max_attempts: Maximum generation attempts before raising error
    
    Returns:
        A unique integer as string (e.g., "1234")
    
    Raises:
        RuntimeError: If unable to generate unique ID after max_attempts
    """
    for _ in range(max_attempts):
        new_id = random.randint(100, 9999)
        if new_id not in existing_ids:
            return str(new_id)
    raise RuntimeError(f"Failed to generate unique comment ID after {max_attempts} attempts")


def is_valid_para_id(para_id: str) -> bool:
    """
    Check if a paraId value is valid (first char 0-7).
    
    Args:
        para_id: The paraId to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not para_id or len(para_id) != 8:
        return False
    try:
        # Check it's valid hex
        int(para_id, 16)
        # Check first char constraint
        return para_id[0] in '01234567'
    except ValueError:
        return False


def is_valid_hex_id(hex_id: str) -> bool:
    """
    Check if a hex ID is valid (8 uppercase hex chars).
    
    Args:
        hex_id: The ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not hex_id or len(hex_id) != 8:
        return False
    try:
        int(hex_id, 16)
        return hex_id == hex_id.upper()
    except ValueError:
        return False
