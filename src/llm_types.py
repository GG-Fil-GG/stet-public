"""Shared types for LLM request/response handling."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class LLMSuggestion:
    """The output from the LLM."""
    revised_text: str
    response: str
    rationale: Optional[str] = None
    target_para_id: Optional[str] = None  # w14:paraId of target paragraph (for virtual state)
    all_target_para_ids: Optional[List[str]] = None  # ALL para_ids when Referenced Text is expanded

    def to_dict(self) -> dict:
        return {
            'revised_text': self.revised_text,
            'response': self.response,
            'rationale': self.rationale,
            'target_para_id': self.target_para_id,
            'all_target_para_ids': self.all_target_para_ids
        }
