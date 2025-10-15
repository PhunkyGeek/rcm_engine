"""
Mini RCM Validation Engine FastAPI application.

This module exposes REST endpoints for ingesting claims and rules,
triggering validation, retrieving adjudicated results and viewing
analytics.  It uses only the built‑in :mod:`sqlite3` database and
FastAPI (already available in the environment), avoiding any
heavyweight dependencies.  The endpoints are documented below and
return JSON responses suitable for consumption by a simple
front‑end.

The application implements a login endpoint with a fixed set of
credentials for demonstration purposes.  In a production system
authentication should be delegated to a proper identity provider.
"""
import base64
import csv
import io
import json
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Optional: load .env file if python-dotenv is installed. This allows local
# development without committing secrets. If python-dotenv is not present we
# continue silently and rely on environment variables set by the user/CI.
try:
    from dotenv import load_dotenv
    # load_dotenv respects an existing .env in the project root
    load_dotenv()
    print("[app] Loaded .env from project root")
except Exception:
    print("[app] python-dotenv not installed; skipping .env load. To enable, pip install python-dotenv and add a .env file")


from db import (
    init_db,
    save_rules,
    insert_claims,
    update_claim_result,
    fetch_claims,
    save_metrics,
    fetch_metrics,
    delete_tenant_data,
    fetch_refined_entries,
)
from rule_engine import (
    parse_rules_text,
    evaluate_static_rules,
    evaluate_llm_rules,
    evaluate_static_rules_full,
)


app = FastAPI(title="Mini RCM Validation Engine")

# Mount static files folder
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")

# Serve the index.html for root route
@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


# Initialise database on startup
init_db()

# Simple user store – in production use proper authentication
USERS = {"admin": "admin123"}


class LoginRequest(BaseModel):
    username: str
    password: str


class UploadRequest(BaseModel):
    tenant_id: str
    claims_file: str  # base64 encoded CSV
    technical_rules_file: Optional[str] = None  # raw text
    medical_rules_file: Optional[str] = None  # raw text


@app.get("/health")
def health_check() -> Dict[str, str]:
    """Return a simple health status."""
    return {"status": "ok"}


@app.post("/login")
def login(payload: LoginRequest) -> Dict[str, str]:
    if USERS.get(payload.username) == payload.password:
        return {"message": f"Welcome {payload.username}!"}
    raise HTTPException(status_code=401, detail="Invalid username or password")


def decode_csv_from_base64(b64: str) -> List[Dict[str, Any]]:
    try:
        raw_bytes = base64.b64decode(b64)
        text = raw_bytes.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        claims = [row for row in reader if any(row.values())]
        return claims
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to decode CSV: {exc}")


@app.post("/upload")
async def upload_files(payload: dict):
    tenant_id = payload.get("tenant_id", "default")
    claims_b64 = payload.get("claims_file")
    tech_rules_raw = payload.get("technical_rules_file")
    med_rules_raw = payload.get("medical_rules_file")

    if not claims_b64:
        raise HTTPException(status_code=400, detail="Missing claims file")

    try:
        claims = decode_csv_from_base64(claims_b64)
        insert_claims(tenant_id, claims)
        print(f"✅ Inserted {len(claims)} claims for {tenant_id}")

        def parse_rules(raw_text, rule_type):
            if not raw_text:
                return []
            try:
                data = json.loads(raw_text)
                if isinstance(data, dict):
                    data = [data]
                elif not isinstance(data, list):
                    raise ValueError("Unexpected format")
                print(f"✅ Parsed {len(data)} {rule_type} rules")
                return data
            except Exception as e:
                print(f"⚠️ Could not parse {rule_type} rules: {e}")
                return []

        tech_rules = parse_rules(tech_rules_raw, "technical")
        med_rules = parse_rules(med_rules_raw, "medical")

        required_keys = ["rule_id", "field", "condition", "value", "error_type", "explanation", "recommended_action"]
        def normalize_rule(rule: dict) -> dict:
            return {k: rule.get(k, "") for k in required_keys}

        if tech_rules:
            save_rules(tenant_id, "technical", [normalize_rule(r) for r in tech_rules])
        if med_rules:
            save_rules(tenant_id, "medical", [normalize_rule(r) for r in med_rules])

        return {"status": "success", "processed": len(claims)}

    except Exception as e:
        print("❌ Upload error:", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validate/{tenant_id}")
def validate_claims(tenant_id: str) -> Dict[str, Any]:
    """Validate claims and return results + metrics immediately."""
    claims = fetch_claims(tenant_id)
    if not claims:
        raise HTTPException(status_code=404, detail="No claims found for tenant")

    category_counts = {"No error": 0, "Medical error": 0, "Technical error": 0, "Both": 0}
    category_totals = {"No error": 0.0, "Medical error": 0.0, "Technical error": 0.0, "Both": 0.0}

    for claim in claims:
        # Evaluate DB-persisted rules first
        db_errors = evaluate_static_rules(tenant_id, claim)
        # Evaluate deterministic static checks (medical/technical spec)
        spec_errors = evaluate_static_rules_full(tenant_id, claim)
        # Merge errors (flatten)
        errors = (db_errors or []) + (spec_errors or [])
        # LLM-based evaluation (non-blocking; currently returns [])
        try:
            llm_violations = evaluate_llm_rules(claim)
            if llm_violations:
                errors += llm_violations
        except Exception:
            pass
        # If static rules produced no errors, we still apply a few basic
        # sanity checks so the UI shows something useful out-of-the-box.
        if not errors:
            # Example basic rule: negative paid amounts indicate an issue.
            try:
                paid_val = float(claim.get("paid_amount_aed") or 0)
            except Exception:
                paid_val = 0

            if paid_val < 0:
                # Populate a synthetic rule violation so the frontend has
                # error_type, explanation and recommended_action to display.
                status = "Not validated"
                error_type = "Technical error"
                explanation = "- Paid amount is negative; possible refund or data error."
                recommended_action = "Investigate payment record; correct negative amount"
                errors = [
                    {
                        "error_type": error_type,
                        "explanation": explanation.replace('^- ', ''),
                        "recommended_action": recommended_action,
                    }
                ]
            else:
                status, error_type, explanation, recommended_action = "Validated", "No error", "", ""
        else:
            status = "Not validated"
            types = {e["error_type"] for e in errors}
            if types == {"Medical error"}:
                error_type = "Medical error"
            elif types == {"Technical error"}:
                error_type = "Technical error"
            else:
                error_type = "Both"
            explanation = "\n".join(f"- {e['explanation']}" for e in errors)
            recs = list({e["recommended_action"] for e in errors})
            recommended_action = "; ".join(recs)

        update_claim_result(tenant_id, claim["claim_id"], status, error_type, explanation, recommended_action)
        # Persist a refined view for analytics/PII-free consumption
        try:
            from db import save_refined_entry
            save_refined_entry(tenant_id, claim.get("claim_id"), status, error_type, explanation, recommended_action)
        except Exception:
            pass

        category_counts[error_type] += 1
        paid = float(claim.get("paid_amount_aed") or 0)
        category_totals[error_type] += paid

    # Persist metrics
    metrics = [(cat, count, category_totals[cat]) for cat, count in category_counts.items()]
    save_metrics(tenant_id, metrics)

    # Fetch updated results
    updated_claims = fetch_claims(tenant_id)
    updated_metrics = fetch_metrics(tenant_id)

    formatted_metrics = []
    for m in updated_metrics:
        if isinstance(m, dict):
            amt = m.get("amount")
            if amt is None:
                amt = m.get("total_paid")
            formatted_metrics.append({
                "category": m.get("category"),
                "count": int(m.get("count", 0)),
                "amount": float(amt or 0)
            })
        else:
            formatted_metrics.append({
                "category": m[0],
                "count": int(m[1]),
                "amount": float(m[2] or 0)
            })

    return {
        "processed": len(claims),
        "claims": updated_claims,
        "metrics": formatted_metrics,
        "category_counts": category_counts,
        "category_totals": category_totals
    }


@app.get('/refined/{tenant_id}')
def get_refined(tenant_id: str) -> Dict[str, Any]:
    try:
        rows = fetch_refined_entries(tenant_id)
        return {"refined": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/seed-sample-rules/{tenant_id}')
def seed_sample_rules(tenant_id: str):
    """Seed sample technical and medical rules into a tenant for demo purposes."""
    # Load the sample files if present in the workspace
    try:
        base = os.path.dirname(__file__)
        tech_path = os.path.join(base, 'sample_technical_rules.json')
        med_path = os.path.join(base, 'sample_medical_rules.json')
        tech = open(tech_path).read() if os.path.exists(tech_path) else '[]'
        med = open(med_path).read() if os.path.exists(med_path) else '[]'
        if tech:
            save_rules(tenant_id, 'technical', json.loads(tech))
        if med:
            save_rules(tenant_id, 'medical', json.loads(med))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/results/{tenant_id}")
def get_results(tenant_id: str) -> Dict[str, Any]:
    claims = fetch_claims(tenant_id)
    normalized = [{
        "claim_id": c.get("claim_id"),
        "status": c.get("status") or "",
        "error_type": c.get("error_type") or "No error",
        # Ensure frontend always gets strings (not None) so UI shows "No issues"
        "error_explanation": (c.get("error_explanation") or c.get("explanation") or "No issues"),
        "recommended_action": (c.get("recommended_action") or ""),
    } for c in claims]
    return {"claims": normalized}


@app.get("/metrics/{tenant_id}")
def get_metrics(tenant_id: str) -> Dict[str, Any]:
    metrics = fetch_metrics(tenant_id)
    formatted = []
    for m in metrics:
        if isinstance(m, dict):
            # Some DB rows may use 'total_paid' (DB schema) while the
            # frontend expects 'amount'. Normalize both to 'amount'.
            amt = m.get("amount")
            if amt is None:
                amt = m.get("total_paid")
            formatted.append({
                "category": m.get("category"),
                "count": int(m.get("count", 0)),
                "amount": float(amt or 0),
            })
        else:
            formatted.append({
                "category": m[0],
                "count": int(m[1]),
                "amount": float(m[2] or 0),
            })
    return {"metrics": formatted}


@app.delete('/tenant/{tenant_id}')
def clear_tenant(tenant_id: str) -> Dict[str, Any]:
    """Delete all data associated with a tenant. Useful for tests/demos."""
    counts = delete_tenant_data(tenant_id)
    return {"status": "ok", "deleted": counts}


@app.get('/settings/{tenant_id}')
def get_settings(tenant_id: str) -> Dict[str, Any]:
    try:
        from db import list_tenant_config
        cfg = list_tenant_config(tenant_id)
        return {"tenant_id": tenant_id, "config": cfg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/settings/{tenant_id}')
def set_settings(tenant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from db import set_tenant_config
        # payload expected to be { key: value, ... }
        for k, v in payload.items():
            set_tenant_config(tenant_id, k, str(v))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))