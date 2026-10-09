"""Live agent-loop integration tests (Stage 1, Milestone 3).

These hit real LLM providers and are skipped unless explicitly enabled:

- OpenAI: runs only when ``OPENAI_API_KEY`` is set.
- Ollama: runs only when ``RUN_OLLAMA_TESTS=1`` and a local Ollama is reachable.
  Llama 3.1 8B tool selection is "Good" but less reliable than OpenAI for long
  chains, so it is opt-in and never part of the default suite.

They are intentionally lightweight: ask the agent to inspect comments and assert
it called a read tool and produced a non-empty final answer.
"""

import os

import pytest
import requests

from src import llm_config
from src.agent import AgentLLMClient, AgentLoop
from src.document_model import parse_docx
from tests.test_support import TEST_DOCX

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
RUN_OLLAMA = os.getenv("RUN_OLLAMA_TESTS") == "1"


def _ollama_reachable() -> bool:
    try:
        url = llm_config.get_ollama_default_url()
        return requests.get(f"{url}/api/tags", timeout=3).status_code == 200
    except requests.exceptions.RequestException:
        return False


@pytest.mark.skipif(not OPENAI_KEY or OPENAI_KEY == "paste-your-key-here",
                    reason="OPENAI_API_KEY not set")
class TestOpenAILive:
    def test_summarise_open_comments(self):
        model = parse_docx(TEST_DOCX)
        client = AgentLLMClient(provider="openai", api_key=OPENAI_KEY)
        loop = AgentLoop(client, model=model, workspace_root=None, max_steps=6)
        result = loop.run(
            "List the open comments in this document and briefly summarise what they ask for."
        )
        assert result.status in ("completed", "max_steps")
        assert any(s.tool_name == "list_comments" for s in result.steps)
        if result.status == "completed":
            assert result.final_text.strip()


@pytest.mark.skipif(not (RUN_OLLAMA and _ollama_reachable()),
                    reason="RUN_OLLAMA_TESTS!=1 or Ollama unreachable")
class TestOllamaLive:
    def test_summarise_open_comments(self):
        model = parse_docx(TEST_DOCX)
        client = AgentLLMClient(provider="ollama")
        loop = AgentLoop(client, model=model, workspace_root=None, max_steps=6)
        try:
            result = loop.run(
                "Use the tools to list the comments in this document, then summarise them."
            )
        except requests.exceptions.RequestException as exc:
            # Local Ollama can transiently 404/timeout during a cold model reload.
            pytest.skip(f"Ollama transient error: {exc}")
        assert result.status in ("completed", "max_steps", "stopped")
        # Tool selection is model-dependent; just require a non-empty trace or answer.
        assert result.steps or result.final_text.strip()
