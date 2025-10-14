"""
Rule engine for Mini RCM Validation Engine.

The system implements a simplified version of the Rules Engine pattern
described by DevIQ【106747799892513†L216-L266】.  A rules engine
encapsulates business rules outside of the main application code
and applies them to inputs.  This design allows rules to be
modified without changing the rest of the system and supports
multi‑tenant operation by storing rule sets separately per tenant.
"""
import json
from typing import List, Dict, Any

from db import fetch_rules, get_tenant_config
import re
from typing import Tuple

# Facility registry (from spec)
FACILITY_TYPES = {
    "0DBYE6KP": "DIALYSIS_CENTER",
    "2XKSZK4T": "MATERNITY_HOSPITAL",
    "7R1VMIGX": "CARDIOLOGY_CENTER",
    "96GUDLMT": "GENERAL_HOSPITAL",
    "9V7HTI6E": "GENERAL_HOSPITAL",
    "EGVP0QAQ": "GENERAL_HOSPITAL",
    "EPRETQTL": "DIALYSIS_CENTER",
    "FLXFBIMD": "GENERAL_HOSPITAL",
    "GLCTDQAJ": "MATERNITY_HOSPITAL",
    "GY0GUI8G": "GENERAL_HOSPITAL",
    "I2MFYKYM": "GENERAL_HOSPITAL",
    "LB7I54Z7": "CARDIOLOGY_CENTER",
    "M1XCZVQD": "CARDIOLOGY_CENTER",
    "M7DJYNG5": "GENERAL_HOSPITAL",
    "MT5W4HIR": "MATERNITY_HOSPITAL",
    "OCQUMGDW": "GENERAL_HOSPITAL",
    "OIAP2DTP": "CARDIOLOGY_CENTER",
    "Q3G9N34N": "GENERAL_HOSPITAL",
    "Q8OZ5Z7C": "GENERAL_HOSPITAL",
    "RNPGDXCU": "MATERNITY_HOSPITAL",
    "S174K5QK": "GENERAL_HOSPITAL",
    "SKH7D31V": "CARDIOLOGY_CENTER",
    "SZC62NTW": "GENERAL_HOSPITAL",
    "VV1GS6P0": "MATERNITY_HOSPITAL",
    "ZDE6M6NJ": "GENERAL_HOSPITAL",
}

# Service groups
INPATIENT_ONLY = {"SRV1001", "SRV1002", "SRV1003"}
OUTPATIENT_ONLY = {"SRV2001", "SRV2002", "SRV2003", "SRV2004", "SRV2006", "SRV2007", "SRV2008", "SRV2010", "SRV2011"}

FACILITY_SERVICE_MAP = {
    "MATERNITY_HOSPITAL": {"SRV2008"},
    "DIALYSIS_CENTER": {"SRV1003", "SRV2010"},
    "CARDIOLOGY_CENTER": {"SRV2001", "SRV2011"},
    "GENERAL_HOSPITAL": {"SRV1001", "SRV1002", "SRV1003", "SRV2001", "SRV2002", "SRV2003", "SRV2004", "SRV2006", "SRV2007", "SRV2008", "SRV2010", "SRV2011"}
}

# Diagnosis -> required services mapping
DIAG_REQUIRED_SERVICE = {
    "E11.9": "SRV2007",
    "J45.909": "SRV2006",
    "R07.9": "SRV2001",
    "Z34.0": "SRV2008",
    "N39.0": "SRV2005",
}

# Mutually exclusive diagnosis pairs
MUTUALLY_EXCLUSIVE_PAIRS = [
    ("R73.03", "E11.9"),
    ("E66.9", "E66.3"),
    ("R51", "G43.9"),
]

# Services requiring prior approval
SERVICES_REQUIRING_APPROVAL = {"SRV1001", "SRV1002", "SRV2008"}

# Diagnosis codes requiring approval
DIAG_REQUIRING_APPROVAL = {"E11.9", "R07.9", "Z34.0"}

PAID_AMOUNT_APPROVAL_THRESHOLD = 250.0

ID_SEGMENT_RE = re.compile(r'^[A-Z0-9]+$')


def validate_id_format(national_id: str, member_id: str, facility_id: str, unique_id: str) -> Tuple[bool, str]:
    # Check uppercase alphanumeric
    for v in (national_id, member_id, facility_id):
        if v and not ID_SEGMENT_RE.match(str(v)):
            return False, "IDs must be uppercase alphanumeric"
    # unique_id pattern: AAAA-BBBB-CCCC
    if unique_id:
        parts = unique_id.split('-')
        if len(parts) != 3 or not all(ID_SEGMENT_RE.match(p) for p in parts):
            return False, "unique_id must be 3 segments of uppercase alphanumeric separated by hyphens"
    return True, ""



def parse_rules_text(text: str, delimiter: str = "|") -> List[Dict[str, Any]]:
    """Parse rules from a text blob into a list of rule dictionaries.

    The format expected is one rule per line with fields separated by
    ``delimiter``.  The columns are:

      1. rule_id – unique identifier
      2. field – claim field name on which to operate
      3. condition – operator such as 'equals', 'not_in', 'less_than', 'greater_than',
         'contains' etc.
      4. value – JSON encoded value (string, number or list)
      5. error_type – 'Technical error' or 'Medical error'
      6. explanation – human readable explanation of the error
      7. recommended_action – recommended corrective action

    Lines beginning with ``#`` are treated as comments and skipped.  Empty
    lines are ignored.  Values are parsed using :func:`json.loads` so that
    lists or numbers may be represented.  If parsing fails the value is
    treated as a plain string.
    """
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(delimiter)]
        if len(parts) < 7:
            # Not enough columns; skip this rule
            continue
        rule_id, field, condition, value_raw, error_type, explanation, recommended_action = parts[:7]
        try:
            value = json.loads(value_raw)
        except Exception:
            value = value_raw
        rules.append(
            {
                "rule_id": rule_id,
                "field": field,
                "condition": condition,
                "value": value,
                "error_type": error_type,
                "explanation": explanation,
                "recommended_action": recommended_action,
            }
        )
    return rules


def apply_rule(rule: Dict[str, Any], claim: Dict[str, Any]) -> bool:
    """Return True if the rule is violated for the given claim.

    The supported conditions include:

      * ``equals`` – claim[field] == value
      * ``not_equals`` – claim[field] != value
      * ``less_than`` – claim[field] < value
      * ``greater_than`` – claim[field] > value
      * ``in`` – claim[field] in value (value should be a list)
      * ``not_in`` – claim[field] not in value (value should be a list)
      * ``contains`` – value substring is contained in claim[field] (for strings)

    Returns True when the condition fails (i.e., an error is detected).  If
    the claim field is missing the rule is considered violated.
    """
    field = rule["field"]
    condition = rule["condition"]
    value = rule["value"]
    claim_value = claim.get(field)
    # Missing value counts as violation
    if claim_value is None:
        return True
    try:
        if condition == "equals":
            # violation when values differ
            return claim_value != value
        elif condition == "not_equals":
            # violation when values are the same
            return claim_value == value
        elif condition == "less_than":
            # violation when claim_value is strictly less than the threshold
            try:
                return float(claim_value) < float(value)
            except Exception:
                return True
        elif condition == "greater_than":
            # violation when claim_value is strictly greater than the threshold
            try:
                return float(claim_value) > float(value)
            except Exception:
                return True
        elif condition == "in":
            # violation when the claim value is contained in the given set (e.g. banned values)
            try:
                return claim_value in value
            except Exception:
                return False
        elif condition == "not_in":
            # violation when the claim value is not contained in the allowed set
            try:
                return claim_value not in value
            except Exception:
                return True
        elif condition == "contains":
            # violation when the claim value string contains the value substring
            return str(value) in str(claim_value)
    except Exception:
        # If comparison fails treat as violated
        return True
    # Unknown condition – assume no violation
    return False


def evaluate_static_rules(
    tenant_id: str, claim: Dict[str, Any], db_path: str = "rcm.db"
) -> List[Dict[str, Any]]:
    """Evaluate all stored static rules for a tenant against a claim.

    Returns a list of dictionaries for each violated rule containing
    ``error_type``, ``explanation`` and ``recommended_action``.  If no rules
    are violated an empty list is returned.
    """
    violated = []
    rules = fetch_rules(tenant_id, db_path=db_path)
    for rule in rules:
        if apply_rule(rule, claim):
            violated.append(
                {
                    "error_type": rule["error_type"],
                    "explanation": rule["explanation"],
                    "recommended_action": rule["recommended_action"],
                }
            )
    return violated


def evaluate_llm_rules(
    claim: Dict[str, Any], llm_model: str = "", temperature: float = 0.0
) -> List[Dict[str, str]]:
    """Placeholder for LLM based rule evaluation.

    In a real system this function would call an external large
    language model to perform more nuanced adjudication, such as
    verifying whether a diagnosis and service code pair makes
    clinical sense.  Due to environment limitations we return an
    empty list.  The function signature is retained so that it can
    be easily swapped for an actual implementation.  The Rules
    Engine pattern allows the rule evaluation strategy to be
    replaced without affecting the rest of the system【106747799892513†L216-L266】.
    """
    # Try to call an external LLM (OpenAI) if configured. If not available
    # fall back to a deterministic heuristic that produces human-friendly
    # suggestions which simulate what an LLM might add.
    # Prefer the dedicated wrapper which includes rate-limiting and error logging.
    try:
        from llm import call_openai_chat
    except Exception:
        call_openai_chat = None

    if call_openai_chat:
        try:
            res = call_openai_chat(claim, model=llm_model or "gpt-3.5-turbo", temperature=temperature or 0.0)
            if res:
                # The wrapper returns a list of dicts with keys error_type, explanation, recommended_action
                return res
        except Exception as e:
            print("[rule_engine] LLM wrapper raised an exception:", e)
            # fall through to heuristic
            pass

    # Heuristic fallback (deterministic, helpful suggestions)
    suggestions: List[Dict[str, str]] = []

    try:
        service = (claim.get('service_code') or '').strip()
        encounter = (claim.get('encounter_type') or '').strip().lower()
        facility_id = (claim.get('facility_id') or '').strip()
        diag_field = claim.get('diagnosis_codes') or ''
        diags = [d.strip() for d in re.split('[,;|]', str(diag_field)) if d.strip()]
        paid = 0.0
        try:
            paid = float(claim.get('paid_amount_aed') or 0)
        except Exception:
            paid = 0.0

        # High-value soft-suggestion
        if paid > PAID_AMOUNT_APPROVAL_THRESHOLD and not claim.get('approval_number'):
            suggestions.append({
                'error_type': 'Technical error',
                'explanation': f'Paid amount AED {paid} is high and typically requires review/approval.',
                'recommended_action': 'Verify prior approval and supporting documentation for high-value claims.'
            })

        # Soft clinical plausibility checks
        if service in INPATIENT_ONLY and encounter != 'inpatient':
            suggestions.append({
                'error_type': 'Technical error',
                'explanation': f'Service {service} is usually inpatient-only; check encounter context.',
                'recommended_action': 'Confirm encounter type and clinical justification for outpatient submission.'
            })

        # If diagnosis list includes mutually exclusive codes, the LLM may suggest clinician review
        for a, b in MUTUALLY_EXCLUSIVE_PAIRS:
            if a in diags and b in diags:
                suggestions.append({
                    'error_type': 'Medical error',
                    'explanation': f'Diagnoses {a} and {b} rarely co-exist; clinical review recommended.',
                    'recommended_action': 'Ask clinician to verify diagnoses and update claim.'
                })

        # If diagnosis indicates pregnancy but service is not pregnancy related, suggest check
        if 'Z34.0' in diags and service != 'SRV2008':
            suggestions.append({
                'error_type': 'Medical error',
                'explanation': 'Pregnancy diagnosis present but pregnancy-specific service not billed.',
                'recommended_action': 'If pregnancy care provided, ensure appropriate pregnancy service codes are included.'
            })

    except Exception:
        pass

    # Remove duplicate explanations
    seen = set()
    out = []
    for s in suggestions:
        if s['explanation'] in seen:
            continue
        seen.add(s['explanation'])
        out.append(s)

    return out


def evaluate_static_rules_full(tenant_id: str, claim: Dict[str, Any]) -> List[Dict[str, str]]:
    """Run the full set of deterministic static checks described in the spec.

    Returns a list of violations where each violation is a dict with keys:
      - error_type ("Technical error" or "Medical error")
      - explanation
      - recommended_action
    """
    violations = []

    # Simple helpers
    def add_violation(t, explanation, action):
        violations.append({"error_type": t, "explanation": explanation, "recommended_action": action})

    service = (claim.get('service_code') or '').strip()
    facility_id = (claim.get('facility_id') or '').strip()
    encounter = (claim.get('encounter_type') or '').strip()
    diag_field = claim.get('diagnosis_codes') or ''
    # diagnosis codes may be CSV or pipe-separated
    diags = [d.strip() for d in re.split('[,;|]', str(diag_field)) if d.strip()]

    # A. Encounter type checks
    if service in INPATIENT_ONLY and encounter.lower() != 'inpatient':
        add_violation('Technical error', f'Service {service} is inpatient-only but encounter is {encounter}', 'Submit as inpatient encounter or change service code')
    if service in OUTPATIENT_ONLY and encounter.lower() == 'inpatient':
        add_violation('Technical error', f'Service {service} is outpatient-only but encounter is inpatient', 'Submit as outpatient encounter or change service code')

    # B. Facility type checks
    fac_type = FACILITY_TYPES.get(facility_id)
    if fac_type:
        allowed = FACILITY_SERVICE_MAP.get(fac_type, set())
        if service and service not in allowed:
            add_violation('Technical error', f'Service {service} is not allowed at facility type {fac_type}', f'Perform service at appropriate facility or update facility type to support {service}')
    else:
        # Unknown facility id is a technical error only when an ID was provided
        if facility_id:
            add_violation('Technical error', f'Unknown facility id {facility_id}', 'Verify facility registry and correct facility_id')

    # C. Services requiring specific diagnoses
    for diag, req_service in DIAG_REQUIRED_SERVICE.items():
        if diag in diags and service != req_service:
            add_violation('Medical error', f'Diagnosis {diag} requires service {req_service}', f'Ensure service {req_service} is billed when diagnosis {diag} is present')

    # D. Mutually exclusive diagnoses
    for a, b in MUTUALLY_EXCLUSIVE_PAIRS:
        if a in diags and b in diags:
            add_violation('Medical error', f'Diagnoses {a} and {b} are mutually exclusive', 'Review clinical documentation; remove incorrect diagnosis')

    # Technical: prior approval rules by service/diagnosis/amount
    if service in SERVICES_REQUIRING_APPROVAL and not claim.get('approval_number'):
        add_violation('Technical error', f'Service {service} requires prior approval', 'Obtain prior approval before processing')
    for d in diags:
        if d in DIAG_REQUIRING_APPROVAL and not claim.get('approval_number'):
            add_violation('Technical error', f'Diagnosis {d} requires prior approval', 'Obtain prior authorization before processing')
    # Allow per-tenant override of the approval amount threshold via tenant_config
    try:
        paid = float(claim.get('paid_amount_aed') or 0)
    except Exception:
        paid = 0
    try:
        cfg = get_tenant_config(tenant_id, 'paid_amount_approval_threshold')
        if cfg:
            try:
                threshold = float(cfg)
            except Exception:
                threshold = PAID_AMOUNT_APPROVAL_THRESHOLD
        else:
            threshold = PAID_AMOUNT_APPROVAL_THRESHOLD
    except Exception:
        threshold = PAID_AMOUNT_APPROVAL_THRESHOLD

    if paid > threshold and not claim.get('approval_number'):
        add_violation('Technical error', f'Paid amount AED {paid} exceeds threshold {threshold}', 'Obtain approval for high-value claims')

    # Per-service caps: tenant can configure a JSON list under 'paid_amount_caps'
    # Format expected: [{"service":"SRV2001","cap":150.0}, ...]
    try:
        caps_raw = get_tenant_config(tenant_id, 'paid_amount_caps')
        if caps_raw:
            try:
                caps = json.loads(caps_raw)
                # find matching service cap
                svc = (service or '').strip()
                for entry in caps:
                    try:
                        if str(entry.get('service') or '') == svc:
                            cap_val = float(entry.get('cap') or 0)
                            if cap_val > 0 and paid > cap_val and not claim.get('approval_number'):
                                add_violation('Technical error', f'Paid amount AED {paid} exceeds cap {cap_val} for service {svc}', 'Verify service-specific cap or obtain approval')
                            break
                    except Exception:
                        continue
            except Exception:
                # ignore malformed config
                pass
    except Exception:
        pass

    # ID formatting
    ok, msg = validate_id_format(claim.get('national_id'), claim.get('member_id'), claim.get('facility_id'), claim.get('unique_id'))
    if not ok:
        add_violation('Technical error', msg, 'Correct ID formats to uppercase alphanumeric and unique_id segments')

    return violations
