"""LLM API transport: env loading, provider calls, response parsing."""

import json
import os
import re
from typing import Dict

import requests
from dotenv import load_dotenv

from src import llm_config
from src.llm_types import LLMSuggestion
from src.paths import is_frozen, get_user_data_dir, get_project_root

def _load_env_file():
    """Load .env file from the appropriate location."""
    if is_frozen():
        # Packaged app - look in user data directory
        env_path = get_user_data_dir() / '.env'
        if env_path.exists():
            load_dotenv(env_path)
        # Also check if there's one in the bundle (fallback)
        bundle_env = get_project_root() / '.env'
        if bundle_env.exists():
            load_dotenv(bundle_env, override=False)
    else:
        # Development mode - standard behavior
        load_dotenv()

_load_env_file()


class LLMTransportMixin:
    """Mixin for LLM API calls and response parsing."""

    def _call_openai_chat(self, prompt: str) -> str:
        """Call OpenAI API for chat mode with JSON response format."""
        params = {
            "model": self.model,
            "messages": [
                {
                    "role": "system", 
                    "content": "You are an expert Medical Writer helping refine manuscript revisions. Always respond with valid JSON containing at minimum a 'chat_response' field."
                },
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        
        # GPT-5 mini doesn't support custom temperature
        if "gpt-5" not in self.model.lower():
            params["temperature"] = self.temperature
        
        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content
    
    def _parse_chat_response(self, response_text: str) -> Dict:
        """
        Parse the chat mode LLM response into structured output.
        
        Expected JSON format:
        {
            "chat_response": "...",      (required)
            "revised_text": "...",       (optional)
            "response": "...",           (optional)
            "rationale": "..."           (optional)
        }
        """
        try:
            # Clean up response
            cleaned = response_text.strip()
            if cleaned.startswith('```json'):
                cleaned = cleaned[7:]
            if cleaned.startswith('```'):
                cleaned = cleaned[3:]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            
            # Extract fields
            result = {
                "chat_response": data.get("chat_response") or data.get("message") or "I've processed your request."
            }
            
            # Only include optional fields if they have content
            if data.get("revised_text"):
                result["revised_text"] = data["revised_text"]
            if data.get("response"):
                result["response"] = data["response"]
            if data.get("rationale"):
                result["rationale"] = data["rationale"]
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"[CHAT] JSON parse error: {e}", flush=True)
            print(f"[CHAT] Raw response: {response_text[:500]}...", flush=True)
            
            # Fallback: treat entire response as chat_response
            return {
                "chat_response": response_text.strip() or "I encountered an error processing your request. Please try again."
            }
    
    # Special Unicode characters that LLMs sometimes corrupt
    # Maps character to a unique placeholder
    UNICODE_PROTECTION_MAP = {
        '≥': '__UNICODE_GTE__',
        '≤': '__UNICODE_LTE__',
        '±': '__UNICODE_PM__',
        '≠': '__UNICODE_NEQ__',
        '≈': '__UNICODE_APPROX__',
        '°': '__UNICODE_DEG__',
        '×': '__UNICODE_TIMES__',
        '÷': '__UNICODE_DIV__',
        'µ': '__UNICODE_MU__',
        'α': '__UNICODE_ALPHA__',
        'β': '__UNICODE_BETA__',
        'γ': '__UNICODE_GAMMA__',
        'δ': '__UNICODE_DELTA__',
        'Δ': '__UNICODE_DELTA_CAP__',
        '→': '__UNICODE_RARROW__',
        '←': '__UNICODE_LARROW__',
        '↑': '__UNICODE_UARROW__',
        '↓': '__UNICODE_DARROW__',
        '∞': '__UNICODE_INF__',
        '∑': '__UNICODE_SUM__',
        '∏': '__UNICODE_PROD__',
        '√': '__UNICODE_SQRT__',
        '∫': '__UNICODE_INT__',
        '∂': '__UNICODE_PARTIAL__',
        '∈': '__UNICODE_IN__',
        '∉': '__UNICODE_NOTIN__',
        '⊂': '__UNICODE_SUBSET__',
        '⊃': '__UNICODE_SUPERSET__',
        '∪': '__UNICODE_UNION__',
        '∩': '__UNICODE_INTERSECT__',
        '∧': '__UNICODE_AND__',
        '∨': '__UNICODE_OR__',
        '¬': '__UNICODE_NOT__',
        '∀': '__UNICODE_FORALL__',
        '∃': '__UNICODE_EXISTS__',
    }
    
    # Reverse map for restoration
    UNICODE_RESTORATION_MAP = {v: k for k, v in UNICODE_PROTECTION_MAP.items()}
    
    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API with JSON response format."""
        # Build request parameters
        params = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert Medical Writer. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}  # Ensures valid JSON output
        }
        
        # GPT-5 mini doesn't support custom temperature
        if "gpt-5" not in self.model.lower():
            params["temperature"] = self.temperature
        
        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content
    
    def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API with JSON format request."""
        response = requests.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",  # Request JSON output (supported by many Ollama models)
                "options": {
                    "temperature": self.temperature
                }
            },
            timeout=300  # 5 minute timeout for local LLMs
        )
        
        if response.status_code != 200:
            raise RuntimeError(f"Ollama error: {response.text}")
        
        return response.json().get('response', '')
    
    def _sanitize_llm_response(self, text: str) -> str:
        """
        Remove invalid control characters from LLM response.
        
        Some LLMs occasionally output control characters (0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F)
        which are invalid in XML and cause DOCX corruption. This removes them.
        
        Tab (0x09), newline (0x0A), and carriage return (0x0D) are preserved as they're
        valid in XML.
        """
        if not text:
            return text
        
        # Build list of chars, removing invalid control characters
        result = []
        removed_count = 0
        for char in text:
            code = ord(char)
            # Valid: 0x09 (tab), 0x0A (LF), 0x0D (CR), 0x20+ (space and above)
            # Invalid: 0x00-0x08, 0x0B-0x0C, 0x0E-0x1F
            if code >= 0x20 or code in (0x09, 0x0A, 0x0D):
                result.append(char)
            else:
                removed_count += 1
        
        if removed_count > 0:
            print(f"[LLM SANITIZE] Removed {removed_count} invalid control character(s)", flush=True)
        
        return ''.join(result)
    
    def _parse_response(self, response_text: str) -> LLMSuggestion:
        """
        Parse the LLM response into structured output.
        
        Tries JSON parsing first (for OpenAI with response_format and Ollama with format: json),
        then falls back to text-based parsing for non-compliant models.
        
        Expected JSON format:
        {
            "revised_text": "...",
            "response": "...",
            "rationale": "..."
        }
        """
        # Sanitize the response to remove invalid control characters
        response_text = self._sanitize_llm_response(response_text)
        
        # Enhanced logging for systematic testing
        print(f"\n{'='*60}", flush=True)
        print(f"[LLM PARSE] Raw response length: {len(response_text)} chars", flush=True)
        print(f"[LLM PARSE] Raw response preview: {response_text[:500]}...", flush=True)
        print(f"{'='*60}", flush=True)
        
        # Try JSON parsing first
        try:
            # Clean up response - some models add markdown code blocks
            cleaned = response_text.strip()
            needed_cleanup = False
            if cleaned.startswith('```json'):
                cleaned = cleaned[7:]
                needed_cleanup = True
            if cleaned.startswith('```'):
                cleaned = cleaned[3:]
                needed_cleanup = True
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
                needed_cleanup = True
            cleaned = cleaned.strip()
            
            if needed_cleanup:
                print(f"[LLM PARSE] Removed markdown code blocks", flush=True)
            
            data = json.loads(cleaned)
            print(f"[LLM PARSE] JSON parsed successfully", flush=True)
            print(f"[LLM PARSE] Keys found: {list(data.keys())}", flush=True)
            
            # Extract fields (support various key names)
            revised_text = data.get('revised_text') or data.get('revised_paragraph') or data.get('revision') or ""
            reply_text = data.get('response') or data.get('reply') or data.get('reply_to_reviewer') or ""
            rationale = data.get('rationale') or data.get('explanation') or None
            
            print(f"[LLM PARSE] revised_text length: {len(revised_text)}", flush=True)
            print(f"[LLM PARSE] response length: {len(reply_text)}", flush=True)
            
            # Accept response if we have both revised_text and reply_text
            if reply_text and revised_text:
                print(f"[LLM PARSE] SUCCESS - JSON parse complete", flush=True)
                return LLMSuggestion(
                    revised_text=revised_text,
                    response=reply_text,
                    rationale=rationale
                )
            else:
                print(f"[LLM PARSE] JSON valid but missing required fields, trying fallback", flush=True)
        except json.JSONDecodeError as e:
            print(f"[LLM PARSE] JSON parse failed: {e}", flush=True)
            print(f"[LLM PARSE] Falling back to text-based parsing", flush=True)
        except (TypeError, KeyError) as e:
            print(f"[LLM PARSE] JSON extraction error: {e}", flush=True)
            print(f"[LLM PARSE] Falling back to text-based parsing", flush=True)
        
        # Fallback: text-based parsing for non-JSON responses
        revised_text = ""
        reply_text = ""
        rationale = ""
        
        lines = response_text.split('\n')
        current_section = None
        current_content = []
        
        for line in lines:
            line_stripped = line.strip()
            line_upper = line_stripped.upper()
            
            is_header = False
            
            if line_upper.startswith('REVISED PARAGRAPH') or line_upper.startswith('REVISED TEXT'):
                if current_section == 'revised':
                    revised_text = '\n'.join(current_content).strip()
                elif current_section == 'reply':
                    reply_text = '\n'.join(current_content).strip()
                elif current_section == 'rationale':
                    rationale = '\n'.join(current_content).strip()
                
                current_section = 'revised'
                current_content = []
                is_header = True
                
            elif line_upper.startswith('REPLY TO REVIEWER') or line_upper.startswith('RESPONSE TO REVIEWER') or line_upper.startswith('RESPONSE:'):
                if current_section == 'revised':
                    revised_text = '\n'.join(current_content).strip()
                elif current_section == 'reply':
                    reply_text = '\n'.join(current_content).strip()
                elif current_section == 'rationale':
                    rationale = '\n'.join(current_content).strip()
                
                current_section = 'reply'
                current_content = []
                is_header = True
                
            elif line_upper.startswith('RATIONALE'):
                if current_section == 'revised':
                    revised_text = '\n'.join(current_content).strip()
                elif current_section == 'reply':
                    reply_text = '\n'.join(current_content).strip()
                elif current_section == 'rationale':
                    rationale = '\n'.join(current_content).strip()
                
                current_section = 'rationale'
                current_content = []
                is_header = True
            
            if not is_header and current_section:
                current_content.append(line)
        
        # Don't forget the last section
        if current_section == 'revised':
            revised_text = '\n'.join(current_content).strip()
        elif current_section == 'reply':
            reply_text = '\n'.join(current_content).strip()
        elif current_section == 'rationale':
            rationale = '\n'.join(current_content).strip()
        
        # Final fallback: if parsing completely failed, use whole response
        if not revised_text and not reply_text:
            print(f"[LLM PARSE] TEXT FALLBACK - Complete failure, using raw response", flush=True)
            revised_text = response_text
            reply_text = "Thank you for your comment. We have revised the text accordingly."
        elif revised_text and not reply_text:
            print(f"[LLM PARSE] TEXT FALLBACK - Found revised_text but no reply", flush=True)
            reply_text = "Thank you for your comment. We have revised the text accordingly."
        else:
            print(f"[LLM PARSE] TEXT FALLBACK - Extracted from text sections", flush=True)
            print(f"[LLM PARSE] revised_text length: {len(revised_text)}", flush=True)
            print(f"[LLM PARSE] response length: {len(reply_text)}", flush=True)
        
        return LLMSuggestion(
            revised_text=revised_text,
            response=reply_text,
            rationale=rationale if rationale else None
        )

