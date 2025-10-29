"""Small configurable LLM provider stub.

This module provides a single function ``evaluate_claim_llm`` which is
designed to be a drop-in integration point for different LLM providers.
It reads the environment variable ``LLM_PROVIDER`` to choose the provider
and looks for provider-specific API keys (for example ``GEMINI_API_KEY`` or
``OPENAI_API_KEY``).

Behaviour:
- If a supported SDK is available and an API key is present the module will
  attempt a best-effort call. All calls are wrapped in try/except so
  failures fall back to a deterministic, safe local heuristic.
- If no SDK or key is available we return a simulated / heuristic result.

This keeps the rest of the codebase independent from a particular SDK and
allows you to drop in credentials or replace the best-effort call with a
real implementation later.
"""
from typing import List, Dict, Any, Optional
import os
import json
import time
import traceback
import logging

logger = logging.getLogger(__name__)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()


def _heuristic_suggestions(claim: Dict[str, Any]) -> List[Dict[str, str]]:
    """Create deterministic heuristic suggestions similar to earlier behavior.

    This is used as a safe fallback when no provider is configured or an
    SDK call fails. Output format matches the expectations of
    :mod:`rule_engine` (error_type, explanation, recommended_action).
    """
    out = []
    try:
        paid = 0.0
        try:
            paid = float(claim.get('paid_amount_aed') or 0)
        except Exception:
            paid = 0.0

        service = (claim.get('service_code') or '').strip()
        encounter = (claim.get('encounter_type') or '').strip().lower()

        # simple heuristics
        if paid and paid > 250.0 and not claim.get('approval_number'):
            out.append({
                'error_type': 'Technical error',
                'explanation': f'Paid amount AED {paid} is high and typically requires review/approval.',
                'recommended_action': 'Verify prior approval and supporting documentation for high-value claims.'
            })

        if service and service.startswith('SRV1') and encounter != 'inpatient':
            out.append({
                'error_type': 'Technical error',
                'explanation': f'Service {service} is commonly inpatient; check encounter type.',
                'recommended_action': 'Confirm encounter type and clinical justification.'
            })
    except Exception:
        # keep fallback silent — return whatever (possibly empty)
        pass
    return out


def evaluate_claim_llm(
    claim: Dict[str, Any],
    model: Optional[str] = None,
    temperature: float = 0.0,
    technical_rules: Optional[List[Dict[str, Any]]] = None,
    medical_rules: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """Evaluate a claim via a configurable LLM provider.

    Parameters
    - claim: claim dictionary
    - model: optional model identifier (e.g. 'gemini-2.5-flash')
    - temperature: sampling temperature

    Returns a list of suggestion dicts with keys: ``error_type``, ``explanation``,
    ``recommended_action``. On error or when providers are not configured the
    function returns heuristic suggestions.
    """
    provider = LLM_PROVIDER

    # Prefer Gemini (Google generative models) if configured. Use the
    # official `google.generativeai` SDK when available and an API key is
    # provided. The code below uses the common chat/completions interface
    # used by that SDK; if any step fails we fall back to the deterministic
    # heuristic suggestions.
    if provider in ("gemini", "google"):
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if api_key:
            try:
                import google.generativeai as genai
                # Configure with the provided API key
                try:
                    if hasattr(genai, 'configure'):
                        genai.configure(api_key=api_key)
                except Exception:
                    # ignore configure errors; some environments pick key from env
                    pass

                prompt = _build_prompt_from_claim(claim, technical_rules=technical_rules, medical_rules=medical_rules)

                # Try the chat completions endpoint which is the recommended
                # surface for Gemini-style chat models.
                try:
                    # Newer SDKs may expose chat.completions.create
                    if hasattr(genai, 'chat') and hasattr(genai.chat, 'completions') and hasattr(genai.chat.completions, 'create'):
                        resp = genai.chat.completions.create(model=model or 'gemini-2.5-flash', messages=[{"role": "user", "content": prompt}], temperature=temperature)
                    else:
                        # Fallback to older helper names
                        resp = genai.chat.create(model=model or 'gemini-2.5-flash', messages=[{"role": "user", "content": prompt}], temperature=temperature)

                    # Extract textual content robustly from SDK response
                    txt = ''
                    try:
                        # Preferred: candidates/content
                        if hasattr(resp, 'candidates'):
                            cand = resp.candidates[0]
                            # candidate may be an object with content attr
                            txt = getattr(cand, 'content', None) or str(cand)
                        elif isinstance(resp, dict) and 'candidates' in resp:
                            cand = resp['candidates'][0]
                            txt = cand.get('content') or str(cand)
                        elif hasattr(resp, 'last'):
                            txt = str(resp.last)
                        else:
                            txt = str(resp)
                    except Exception:
                        txt = str(resp)

                    return _parse_text_to_suggestions(txt)
                except Exception:
                    # If the SDK call or parsing fails, log a warning and fall back
                    logger.warning("Gemini SDK call or parsing failed; falling back to heuristic", exc_info=True)
            except Exception:
                # SDK not installed or import failed; fall back to heuristic
                pass

    # Last-resort: return deterministic heuristic suggestions
    return _heuristic_suggestions(claim)


def _build_prompt_from_claim(claim: Dict[str, Any], technical_rules: Optional[List[Dict[str, Any]]] = None, medical_rules: Optional[List[Dict[str, Any]]] = None) -> str:
    # Keep prompt short and structured to make parsing easy if a real model is used.
    parts = []
    for k in ("claim_id", "service_code", "facility_id", "encounter_type", "diagnosis_codes", "paid_amount_aed", "approval_number"):
        v = claim.get(k)
        parts.append(f"{k}: {v}")
    # Attach rules context if present. Include a compact JSON representation
    # to help the model reason with the dynamically uploaded rule sets.
    if technical_rules:
        try:
            parts.append("\nTECHNICAL_RULES:\n" + json.dumps(technical_rules, ensure_ascii=False))
        except Exception:
            parts.append("\nTECHNICAL_RULES: (unserializable)")
    if medical_rules:
        try:
            parts.append("\nMEDICAL_RULES:\n" + json.dumps(medical_rules, ensure_ascii=False))
        except Exception:
            parts.append("\nMEDICAL_RULES: (unserializable)")

    parts.append("\nPlease list any likely technical or medical errors found in the claim given the rules above and a single recommended action for each as a JSON array of objects with keys: error_type, explanation, recommended_action.")
    return "\n".join(parts)


def _parse_text_to_suggestions(text: str) -> List[Dict[str, str]]:
    """Try to parse model output as JSON, or fall back to heuristic if parsing fails."""
    try:
        # Model may return JSON directly — try to find the first JSON array
        text = text.strip()
        # Attempt direct load
        parsed = json.loads(text)
        if isinstance(parsed, list):
            # Validate shape
            out = []
            for item in parsed:
                if isinstance(item, dict):
                    out.append({
                        'error_type': item.get('error_type') or item.get('type') or 'Medical error',
                        'explanation': item.get('explanation') or item.get('explain') or str(item),
                        'recommended_action': item.get('recommended_action') or item.get('action') or ''
                    })
            return out
    except Exception:
        pass
    # Could not parse — return heuristic
    return _heuristic_suggestions({})


if __name__ == '__main__':
    # Quick local smoke test
    sample = {
        'claim_id': 'C123',
        'service_code': 'SRV1001',
        'facility_id': '96GUDLMT',
        'encounter_type': 'outpatient',
        'diagnosis_codes': 'E11.9',
        'paid_amount_aed': '360.0'
    }
    print('LLM_PROVIDER=', LLM_PROVIDER)
    print('Suggestions:', evaluate_claim_llm(sample))
