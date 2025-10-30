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
import requests
from threading import Lock

logger = logging.getLogger(__name__)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# ---- simple in-memory throttle guard ----
_last_request_time = 0.0
_request_lock = Lock()
_MIN_INTERVAL = 2.0  # seconds between Gemini calls


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


# ---------------- STATIC RULE FALLBACK ----------------
def _evaluate_static_rules(
    claim: Dict[str, Any],
    technical_rules: Optional[List[Dict[str, Any]]],
    medical_rules: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, str]]:
    """Static rule evaluation engine (no LLM required).

    This applies simple condition checks present in the uploaded rule
    JSONs and returns suggestions using the same output shape as the LLM.
    If no static rule matches are found it falls back to heuristics.
    """
    suggestions: List[Dict[str, str]] = []

    def _safe_get_float(val, default=0.0):
        try:
            return float(val)
        except Exception:
            return default

    def val(key):
        return str(claim.get(key, "")).lower().strip()

    rulesets: List[Dict[str, Any]] = []
    if technical_rules:
        rulesets.extend(technical_rules)
    if medical_rules:
        rulesets.extend(medical_rules)

    for rule in rulesets:
        try:
            cond = (rule.get("condition") or "").lower()
            desc = rule.get("explanation") or rule.get("description") or ""
            action = rule.get("recommended_action") or rule.get("action") or "Review claim."

            # Approval-related rule
            if "approval" in cond and not claim.get("approval_number"):
                suggestions.append({
                    "error_type": rule.get("error_type") or "Technical error",
                    "explanation": desc or "Missing approval number for this rule.",
                    "recommended_action": action,
                })

            # Encounter type mismatch (e.g., inpatient required)
            elif "inpatient" in cond and val("encounter_type") != "inpatient":
                suggestions.append({
                    "error_type": rule.get("error_type") or "Medical error",
                    "explanation": desc or "Rule expects inpatient encounter type.",
                    "recommended_action": action,
                })

            # Paid amount threshold
            elif "paid_amount" in cond or "amount" in cond or "threshold" in rule:
                threshold = _safe_get_float(rule.get("threshold") or rule.get("value") or 250)
                if _safe_get_float(claim.get("paid_amount_aed") or 0) > threshold:
                    suggestions.append({
                        "error_type": rule.get("error_type") or "Technical error",
                        "explanation": desc or f"Claim exceeds threshold AED {threshold}.",
                        "recommended_action": action,
                    })

        except Exception as e:
            logger.warning("Static rule evaluation error: %s", e)

    return suggestions or _heuristic_suggestions(claim)


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

    # Prefer Gemini (Google generative models) only. If GEMINI_API_KEY is
    # not set we log and fall back to heuristics. Use the REST API when the
    # Python SDK surface is unreliable in the runtime environment.
    # If provider isn't Gemini, use static rules directly
    if provider not in ("gemini", "google"):
        return _evaluate_static_rules(claim, technical_rules, medical_rules)

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("No GEMINI_API_KEY found; using static rules.")
        return _evaluate_static_rules(claim, technical_rules, medical_rules)

    try:
        # --- Rate limit enforcement (local safeguard) ---
        global _last_request_time
        with _request_lock:
            now = time.time()
            if now - _last_request_time < _MIN_INTERVAL:
                logger.warning("Gemini locally throttled; using static rules instead.")
                return _evaluate_static_rules(claim, technical_rules, medical_rules)
            _last_request_time = now

        prompt = _build_prompt_from_claim(claim, technical_rules=technical_rules, medical_rules=medical_rules)
        model_name = model or "gemini-2.5-flash"

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": float(temperature or 0.0),
                "maxOutputTokens": 800,
            },
        }

        res = requests.post(
            f"{GEMINI_URL}?key={api_key}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        # Handle quota / rate-limit responses explicitly
        if res.status_code == 429:
            # Quota exceeded or rate-limited by Google
            try:
                err = res.json().get("error", {})
                err_msg = err.get("message", "Quota exceeded")
            except Exception:
                err_msg = "Quota exceeded"
            logger.error("Gemini quota exceeded: %s", err_msg)
            # Back off temporarily: set next allowed time further in future
            with _request_lock:
                _last_request_time = time.time() + 60
            # Switch to static rule evaluation when quota exhausted
            return _evaluate_static_rules(claim, technical_rules, medical_rules)

        if not res.ok:
            logger.error(f"Gemini HTTP error {res.status_code}: {res.text}")
            return _evaluate_static_rules(claim, technical_rules, medical_rules)

        data = res.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )

        parsed = _parse_text_to_suggestions(text)
        # If parsing failed or returned nothing, fall back to static rules
        return parsed or _evaluate_static_rules(claim, technical_rules, medical_rules)

    except Exception as e:
        logger.warning("Gemini call failed; reverting to static rules: %s", e, exc_info=True)
        return _evaluate_static_rules(claim, technical_rules, medical_rules)

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
    """Try to parse model output as JSON.

    Important: this parser returns an empty list when parsing fails so the
    caller can decide whether to fall back to static rules or heuristics.
    """
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
    # Could not parse — return empty to let caller choose fallback
    return []


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
