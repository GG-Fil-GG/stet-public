"""
Config router - handles configuration endpoints.

Endpoints:
- POST /update_instructions/{session_id} - Update session instructions
- POST /update_thread_instructions/{session_id}/{thread_id} - Update thread instructions
- GET /get_instructions/{session_id}/{thread_id} - Get thread instructions
- GET /llm-config - Get LLM provider configuration
"""

from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse

from src.routes.state import get_session, save_session
from src.constants import DEFAULT_INSTRUCTIONS
from src import llm_config

router = APIRouter()


@router.post("/update_instructions/{session_id}")
async def update_session_instructions(
    request: Request,
    session_id: str,
    instructions: str = Form(...)
):
    """Update session-level custom instructions."""
    session = get_session(session_id)
    session["default_instructions"] = instructions
    save_session(session_id)
    return JSONResponse({"status": "ok", "message": "Session instructions updated"})


@router.post("/update_thread_instructions/{session_id}/{thread_id}")
async def update_thread_instructions(
    request: Request,
    session_id: str,
    thread_id: str,
    instructions: str = Form(...)
):
    """Update per-thread custom instructions."""
    session = get_session(session_id)
    
    if instructions.strip() == session.get("default_instructions", DEFAULT_INSTRUCTIONS).strip():
        # If same as default, remove the override
        if thread_id in session["thread_instructions"]:
            del session["thread_instructions"][thread_id]
    else:
        session["thread_instructions"][thread_id] = instructions
    
    save_session(session_id)
    return JSONResponse({"status": "ok", "message": "Thread instructions updated"})


@router.get("/get_instructions/{session_id}/{thread_id}")
async def get_thread_instructions(session_id: str, thread_id: str):
    """Get the effective instructions for a thread (thread-specific or session default)."""
    session = get_session(session_id)
    instructions = session["thread_instructions"].get(
        thread_id,
        session.get("default_instructions", DEFAULT_INSTRUCTIONS)
    )
    is_custom = thread_id in session["thread_instructions"]
    return JSONResponse({
        "instructions": instructions,
        "is_custom": is_custom
    })


@router.get("/llm-config")
async def get_llm_config():
    """
    Get LLM provider and model configuration for the frontend.
    
    Returns providers with their models, including display names and context windows.
    """
    providers = []
    
    for provider_id in llm_config.get_providers():
        provider_data = {
            'id': provider_id,
            'name': llm_config.get_provider_name(provider_id),
            'requires_api_key': llm_config.requires_api_key(provider_id),
            'default_model': llm_config.get_default_model(provider_id),
            'models': []
        }
        
        # Add Ollama-specific config
        if provider_id == 'ollama':
            provider_data['default_url'] = llm_config.get_ollama_default_url()
        
        # Add models for this provider
        for model_id in llm_config.get_models(provider_id):
            model_data = {
                'id': model_id,
                'name': llm_config.get_model_name(provider_id, model_id),
                'description': llm_config.get_model_description(provider_id, model_id),
                'context_window': llm_config.get_context_window(provider_id, model_id),
                'max_output': llm_config.get_max_output(provider_id, model_id)
            }
            
            # Add pricing for paid models
            pricing = llm_config.get_pricing(provider_id, model_id)
            if pricing:
                model_data['pricing'] = pricing
            
            provider_data['models'].append(model_data)
        
        providers.append(provider_data)
    
    return {
        'providers': providers,
        'defaults': llm_config.get_defaults()
    }
