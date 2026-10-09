"""
LLMHandler - AI integration for generating revision suggestions and responses.

Supports OpenAI (GPT-5 mini) and Ollama (local LLMs).
"""

import os
import sys
from typing import Optional, Dict, List, Tuple

import requests

from src import llm_config
from src.chat_types import ChatMessage
from src.constants import ChatSettings
from src.llm_types import LLMSuggestion
from src.session_utils import ThreadContext

from .llm_prompts import LLMPromptsMixin
from .llm_transport import LLMTransportMixin

__all__ = ["LLMHandler", "LLMSuggestion", "create_handler"]
class LLMHandler(LLMPromptsMixin, LLMTransportMixin):
    """
    Handle LLM interactions for generating revision suggestions.
    
    Provider and model configuration loaded from config/llm_providers.yaml.
    
    Supports providers:
    - "openai": Uses OpenAI API
    - "ollama": Uses local Ollama server
    """
    
    # XML namespaces for Word documents
    NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    NS_W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
    
    def __init__(
        self,
        provider: str = "openai",
        model: Optional[str] = None,
        docx_path: Optional[str] = None,
        context_paragraphs_before: Optional[int] = None,
        context_paragraphs_after: Optional[int] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        ollama_url: Optional[str] = None
    ):
        """
        Initialize the LLM handler.
        
        Args:
            provider: "openai" or "ollama" (from config/llm_providers.yaml)
            model: Model name (defaults from config)
            docx_path: Path to the .docx file for context extraction
            context_paragraphs_before: Number of paragraphs before the comment to include
            context_paragraphs_after: Number of paragraphs after the comment to include
            temperature: LLM temperature (0.0-1.0, higher = more creative)
            api_key: API key for OpenAI (passed from frontend, falls back to env var)
            ollama_url: Ollama server URL (passed from frontend, falls back to config)
        """
        self.provider = provider.lower()
        self.docx_path = docx_path
        
        # Load defaults from config
        defaults = llm_config.get_defaults()
        self.temperature = temperature if temperature is not None else defaults.get('temperature', 0.3)
        
        # Load context settings from environment, config, or use defaults
        self.context_paragraphs_before = context_paragraphs_before or int(
            os.getenv('CONTEXT_PARAGRAPHS_BEFORE', str(defaults.get('context_paragraphs_before', 2)))
        )
        self.context_paragraphs_after = context_paragraphs_after or int(
            os.getenv('CONTEXT_PARAGRAPHS_AFTER', str(defaults.get('context_paragraphs_after', 2)))
        )
        
        # Validate provider exists in config
        available_providers = llm_config.get_providers()
        if self.provider not in available_providers:
            raise ValueError(f"Unknown provider: {provider}. Available: {', '.join(available_providers)}")
        
        # Set up provider-specific configuration
        if self.provider == "openai":
            # Use model from arg, or default from config
            self.model = model or llm_config.get_default_model('openai')
            
            # API key: prefer passed value, then env var
            self.api_key = api_key or os.getenv('OPENAI_API_KEY')
            if not self.api_key or self.api_key == 'paste-your-key-here':
                raise ValueError("OpenAI API key not provided. Please enter your API key in Settings.")
            
            # Import OpenAI client
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
            
            # Store model config for reference
            self.model_config = llm_config.get_model_config('openai', self.model)
            
        elif self.provider == "ollama":
            # Use model from arg, env, or config default
            self.model = model or os.getenv('OLLAMA_MODEL', llm_config.get_default_model('ollama'))
            # Ollama URL: prefer passed value, then config default
            self.ollama_url = ollama_url or llm_config.get_ollama_default_url()
            
            # Verify Ollama is running
            try:
                response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
                if response.status_code != 200:
                    raise ConnectionError("Ollama server not responding")
            except requests.exceptions.RequestException as e:
                raise ConnectionError(f"Cannot connect to Ollama at {self.ollama_url}: {e}")
            
            self.model_config = None  # Ollama models discovered at runtime
        else:
            raise ValueError(f"Unknown provider: {provider}. Available: {', '.join(available_providers)}")
    
    def generate_suggestion(
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
        attachments: Optional[List[Dict]] = None,
    ) -> LLMSuggestion:
        """
        Generate a revision suggestion and response for a comment thread.
        
        Args:
            thread: The ThreadContext to address
            accepted_revisions: Optional dict mapping para_id -> revised_text.
                               When provided, any paragraph with a pending revision
                               will use the revised text in the prompt context.
            context_before_count: Number of paragraphs before target (default: handler default)
            context_after_count: Number of paragraphs after target (default: handler default)
            ref_start_offset: Negative offset to expand target upward (e.g., -2 includes 2 paragraphs above)
            ref_end_offset: Positive offset to expand target downward (e.g., 2 includes 2 paragraphs below)
            custom_instructions: Optional custom instructions to use instead of defaults
            paragraph_cache: Optional pre-processed paragraph cache (from DocumentModel).
                            If provided, tables are already in markdown format.
            thread_target_indices: Optional dict mapping thread_id -> (start_idx, end_idx).
            attachments: Optional list of attachment dicts with 'filename' and 'parsed_content' keys.
            
        Returns:
            LLMSuggestion with revised_text, response, rationale, and target_para_id
        """
        # Build the prompt with context (citations will be replaced with markers)
        
        prompt, citation_map, target_para_id, all_target_para_ids, masked_text = self._build_prompt_with_citation_protection(
            thread, accepted_revisions, context_before_count, context_after_count,
            ref_start_offset, ref_end_offset, custom_instructions,
            paragraph_cache, thread_target_indices, attachments
        )
        
        # Protect special Unicode characters that LLMs sometimes corrupt
        prompt, had_unicode_protection = self._protect_unicode(prompt)
        
        # Track which citation markers belong to which paragraph (for validation)
        markers_per_para = self._get_markers_per_paragraph(masked_text, citation_map) if citation_map else {}
        
        # Call the appropriate provider
        if self.provider == "openai":
            response_text = self._call_openai(prompt)
        else:
            response_text = self._call_ollama(prompt)
        
        # Parse the response
        suggestion = self._parse_response(response_text)
        
        # Validate and restore any missing citation markers (per-paragraph)
        revised_text = suggestion.revised_text
        if citation_map and markers_per_para:
            revised_text, restored_markers = self._validate_and_restore_markers(
                revised_text, markers_per_para
            )
            if restored_markers:
                print(f"[CITATION] Auto-restored {len(restored_markers)} missing citation(s): {restored_markers}", flush=True)
        
        # Restore protected Unicode characters
        if had_unicode_protection:
            revised_text = self._restore_unicode(revised_text)
            response_text_cleaned = self._restore_unicode(suggestion.response)
        else:
            response_text_cleaned = suggestion.response
        
        # Restore citations in the revised text and include target_para_id
        suggestion = LLMSuggestion(
            revised_text=self._restore_citations(revised_text, citation_map) if citation_map else revised_text,
            response=response_text_cleaned,
            rationale=suggestion.rationale,
            target_para_id=target_para_id,
            all_target_para_ids=all_target_para_ids
        )
        
        return suggestion
    
    # =========================================================================
    # CHAT MODE
    # =========================================================================
    
    # Maximum chat messages to include in prompt (sliding window)
    MAX_CHAT_MESSAGES = ChatSettings.MAX_CHAT_MESSAGES
    
    def generate_chat_response(
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
    ) -> Dict:
        """
        Generate a response in chat mode for iterative refinement of suggestions.
        
        Args:
            thread: The comment thread being addressed
            chat_history: List of ChatMessage objects (previous conversation)
            user_message: The new message from the user
            current_revision: The current revised_text
            current_reply: The current response to reviewer
            paragraph_cache: Pre-processed paragraph cache
            target_indices: Tuple of (start_idx, end_idx) for target in cache
            context_settings: Dict with before_count, after_count, ref_start_offset, ref_end_offset
            accepted_revisions: Dict mapping para_id -> revised_text
            instructions: Custom instructions for the LLM
            attachments: Optional list of attachment dicts with 'filename' and 'parsed_content' keys
            
        Returns:
            Dict with keys:
              - chat_response (str, required): Conversational reply for the chat
              - revised_text (str, optional): Updated revision if changed
              - response (str, optional): Updated reply if changed
              - rationale (str, optional): Brief explanation
        """
        # Build the chat prompt
        prompt = self._build_chat_prompt(
            thread=thread,
            chat_history=chat_history,
            user_message=user_message,
            current_revision=current_revision,
            current_reply=current_reply,
            paragraph_cache=paragraph_cache,
            target_indices=target_indices,
            context_settings=context_settings,
            accepted_revisions=accepted_revisions,
            instructions=instructions,
            attachments=attachments
        )

        # Protect special Unicode characters that LLMs sometimes corrupt
        prompt, had_unicode_protection = self._protect_unicode(prompt)

        # Call the appropriate provider
        if self.provider == "openai":
            response_text = self._call_openai_chat(prompt)
        else:
            response_text = self._call_ollama(prompt)

        # Parse the chat response
        result = self._parse_chat_response(response_text)
        
        # Restore protected Unicode characters in all result fields
        if had_unicode_protection:
            if result.get('revised_text'):
                result['revised_text'] = self._restore_unicode(result['revised_text'])
            if result.get('response'):
                result['response'] = self._restore_unicode(result['response'])
            if result.get('chat_response'):
                result['chat_response'] = self._restore_unicode(result['chat_response'])
        
        return result
    

def create_handler(
    provider: str = "openai",
    docx_path: Optional[str] = None,
    **kwargs
) -> LLMHandler:
    """
    Convenience function to create an LLMHandler.
    
    Args:
        provider: "openai" or "ollama"
        docx_path: Path to .docx file for context extraction
        **kwargs: Additional arguments passed to LLMHandler
        
    Returns:
        Configured LLMHandler instance
    """
    return LLMHandler(provider=provider, docx_path=docx_path, **kwargs)


# =============================================================================
# CLI FOR TESTING
# =============================================================================

if __name__ == "__main__":
    from src.document_model import parse_docx
    from src.session_utils import convert_dom_thread_for_llm
    
    # Default test file
    docx_path = "test_data/synthetic/test.docx"
    
    print("=" * 60)
    print("LLM Handler Test")
    print("=" * 60)
    
    # Extract comments using DOM
    print("\n1. Extracting comments...")
    model = parse_docx(docx_path)
    dom_threads = [t for t in model.comments.threads.values() if not t.is_resolved]
    threads = [convert_dom_thread_for_llm(t, model) for t in dom_threads]
    print(f"   Found {len(threads)} open threads")
    
    # Pick a thread to test
    if not threads:
        print("   No open threads found!")
        sys.exit(1)
    
    # Find a good test thread (one with clear revision request)
    test_thread = threads[0]
    for t in threads:
        # Prefer threads with "revise", "please", or "change" in the comment
        if any(word in t.comments[0].text.lower() for word in ['revise', 'please', 'change', 'clarify']):
            test_thread = t
            break
    
    print(f"\n2. Testing with Thread {test_thread.thread_id}")
    print(f"   Section: {test_thread.section[:50] if test_thread.section else 'N/A'}...")
    print(f"   Comment: {test_thread.comments[0].text[:80]}...")
    
    # Test with Ollama first (no API key needed)
    print("\n3. Testing Ollama provider...")
    try:
        handler = LLMHandler(provider="ollama", docx_path=docx_path)
        print(f"   Model: {handler.model}")
        print("   Generating suggestion (this may take a minute)...")
        suggestion = handler.generate_suggestion(test_thread)
        print("\n   === OLLAMA RESULT ===")
        print(f"   Revised text: {suggestion.revised_text[:200]}...")
        print(f"   Response: {suggestion.response[:200]}...")
    except Exception as e:
        print(f"   Ollama test failed: {e}")
    
    # Test with OpenAI if API key is set
    print("\n4. Testing OpenAI provider...")
    try:
        handler = LLMHandler(provider="openai", docx_path=docx_path)
        print(f"   Model: {handler.model}")
        print("   Generating suggestion...")
        suggestion = handler.generate_suggestion(test_thread)
        print("\n   === OPENAI RESULT ===")
        print(f"   Revised text: {suggestion.revised_text[:200]}...")
        print(f"   Response: {suggestion.response[:200]}...")
    except ValueError as e:
        print(f"   OpenAI test skipped: {e}")
    except Exception as e:
        print(f"   OpenAI test failed: {e}")
    
    print("\n" + "=" * 60)
    print("Test complete!")

