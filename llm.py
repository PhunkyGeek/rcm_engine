"""
Deprecated OpenAI helper (removed).

This file previously contained OpenAI-specific helpers. OpenAI support
has been removed from the codebase in favor of Gemini (google.generativeai).
The module is retained as a no-op shim to avoid import errors from any
leftover references; its public function returns None.
"""
from typing import Dict, Any, List, Optional


def call_openai_chat(*args, **kwargs) -> Optional[List[Dict[str, Any]]]:
    """Compatibility shim for removed OpenAI support.

    Always returns None to indicate no LLM result. If you see this being
    used, switch the caller to use `llm_provider.evaluate_claim_llm` which
    now handles Gemini.
    """
    return None
