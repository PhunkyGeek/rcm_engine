import os
import time
import json
from typing import Dict, Any, List, Optional

# Simple in-memory rate limiter (per-process). Not persistent across restarts.
# Limits to MAX_CALLS_PER_MINUTE calls per minute across the process.
MAX_CALLS_PER_MINUTE = int(os.environ.get("OPENAI_MAX_PER_MINUTE", "10"))
_call_timestamps: List[float] = []


def _allowed_to_call() -> bool:
    """Return True if we are under rate limit."""
    global _call_timestamps
    now = time.time()
    # drop timestamps older than 60s
    _call_timestamps = [t for t in _call_timestamps if now - t < 60]
    return len(_call_timestamps) < MAX_CALLS_PER_MINUTE


def _record_call():
    _call_timestamps.append(time.time())


def call_openai_chat(claim: Dict[str, Any], model: str = "gpt-3.5-turbo", temperature: float = 0.0, max_tokens: int = 200) -> Optional[List[Dict[str, str]]]:
    """
    Safely call OpenAI ChatCompletion with basic rate-limiting and retries.
    Returns parsed JSON (list of violation dicts) or None if call wasn't made or failed.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    enabled = os.environ.get("OPENAI_ENABLED", "true").lower() in ("1", "true", "yes")
    if not api_key or not enabled:
        # Not configured
        print("[llm] OpenAI disabled or API key not found; falling back to heuristic")
        return None

    if not _allowed_to_call():
        print(f"[llm] Rate limit reached ({MAX_CALLS_PER_MINUTE}/min). Skipping LLM call.")
        return None

    try:
        import openai
    except Exception as e:
        print("[llm] openai package not installed:", e)
        return None

    openai.api_key = api_key

    system = (
        "You are a medical claims adjudication assistant. Given a single claim as JSON, "
        "identify potential issues not caught by deterministic rules and provide a short explanation and recommended action. "
        "Return a JSON array of objects with keys: error_type, explanation, recommended_action. "
    )
    prompt = f"Claim JSON:\n{json.dumps(claim, indent=2)}\n\nRespond with JSON array only."

    # Basic retry loop for transient issues
    retries = 2
    for attempt in range(retries + 1):
        try:
            resp = openai.ChatCompletion.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = resp.choices[0].message.content.strip()
            # record the successful call
            _record_call()
            try:
                parsed = json.loads(text)
                out = []
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    out.append({
                        "error_type": item.get("error_type", "Technical error"),
                        "explanation": item.get("explanation", ""),
                        "recommended_action": item.get("recommended_action", ""),
                    })
                return out
            except Exception as e:
                print("[llm] OpenAI response could not be parsed as JSON:", e)
                print("[llm] Raw response:", text)
                return None
        except Exception as e:
            # Log and retry with backoff
            print(f"[llm] OpenAI call failed (attempt {attempt+1}):", e)
            if attempt < retries:
                time.sleep(1 + attempt * 2)
            else:
                return None
