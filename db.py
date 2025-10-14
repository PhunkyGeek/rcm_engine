"""
Database access layer for Mini RCM Validation Engine.

This module manages the SQLite database used by the system.  It
defines functions to create the schema, insert and update claims,
persist rule sets for different tenants and query analytics.  The
database lives in the local filesystem (``rcm.db`` by default) and
uses Python's built‑in :mod:`sqlite3` module so that the system has
zero external dependencies.  Each tenant is identified by a
``tenant_id``.  Rule sets and claims are stored separately but
referenced through this identifier, making it possible to support
multi‑tenant deployments as described in the Frontegg multi‑tenant
architecture guide【131609292750414†L118-L131】.
"""
import sqlite3
from typing import List, Dict, Any, Tuple, Optional
import time

def get_connection(db_path: str = "rcm.db") -> sqlite3.Connection:
    """Return a SQLite connection that is safe for multi-threaded FastAPI use."""
    # Allow multi-thread access and wait if DB is busy
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def safe_commit(conn, retries: int = 5, delay: float = 0.5):
    """Retry commits if the database is locked."""
    for _ in range(retries):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                time.sleep(delay)
            else:
                raise
    raise Exception("Database remained locked after multiple retries")



def init_db(db_path: str = "rcm.db") -> None:
    """Initialise the database schema.

    This function creates the master table, refined table, rules table and
    metrics table if they don't already exist.  It is idempotent and
    safe to call on every start‑up.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    # Master table storing raw claims and adjudication results
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS master_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            claim_id TEXT,
            encounter_type TEXT,
            service_date TEXT,
            national_id TEXT,
            member_id TEXT,
            facility_id TEXT,
            unique_id TEXT,
            diagnosis_codes TEXT,
            service_code TEXT,
            paid_amount_aed REAL,
            approval_number TEXT,
            status TEXT,
            error_type TEXT,
            error_explanation TEXT,
            recommended_action TEXT
        );
        """
    )
    # Rules table storing technical and medical rules per tenant
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            rule_type TEXT NOT NULL, -- 'technical' or 'medical'
            rule_id TEXT NOT NULL,
            field TEXT NOT NULL,
            condition TEXT NOT NULL,
            value TEXT NOT NULL,
            error_type TEXT NOT NULL,
            explanation TEXT NOT NULL,
            recommended_action TEXT NOT NULL
        );
        """
    )
    # Metrics table summarising analytics for charts
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            category TEXT NOT NULL,
            count INTEGER,
            total_paid REAL
        );
        """
    )
    # Refined table stores adjudicated/refined claim view after validation/pipeline
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS refined_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            claim_id TEXT,
            status TEXT,
            error_type TEXT,
            error_explanation TEXT,
            recommended_action TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    safe_commit(conn)

    conn.close()


def save_rules(tenant_id: str, rule_type: str, rules: List[Dict[str, Any]], db_path: str = "rcm.db") -> None:
    """Persist a list of rules to the database.

    Existing rules for the tenant and type are removed prior to insert.  Each
    rule dictionary must contain the keys ``rule_id``, ``field``, ``condition``,
    ``value``, ``error_type``, ``explanation`` and ``recommended_action``.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    # Remove existing rules for this tenant and type
    cur.execute(
        "DELETE FROM rules WHERE tenant_id = ? AND rule_type = ?",
        (tenant_id, rule_type),
    )
    # Insert new rules
    for rule in rules:
        cur.execute(
            """
            INSERT INTO rules (tenant_id, rule_type, rule_id, field, condition, value, error_type, explanation, recommended_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                rule_type,
                rule["rule_id"],
                rule["field"],
                rule["condition"],
                str(rule["value"]),  # store as text to allow JSON lists etc.
                rule["error_type"],
                rule["explanation"],
                rule["recommended_action"],
            ),
        )
    safe_commit(conn)

    conn.close()


def fetch_rules(tenant_id: str, rule_type: Optional[str] = None, db_path: str = "rcm.db") -> List[Dict[str, Any]]:
    """Return all rules for a tenant.

    If ``rule_type`` is provided it will filter on that type ('technical' or 'medical').
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    if rule_type:
        cur.execute(
            "SELECT * FROM rules WHERE tenant_id = ? AND rule_type = ?",
            (tenant_id, rule_type),
        )
    else:
        cur.execute(
            "SELECT * FROM rules WHERE tenant_id = ?",
            (tenant_id,),
        )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def insert_claims(tenant_id: str, claims: List[Dict[str, Any]], db_path: str = "rcm.db") -> None:
    """Insert claims into the master table.

    Accepts a list of dictionaries with keys corresponding to the master table
    columns.  The function sets ``status``, ``error_type``, ``error_explanation``
    and ``recommended_action`` to NULL initially; they will be filled during
    validation.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    for claim in claims:
        # Try to update an existing claim (dedupe); if none updated, insert a new row.
        paid_val = None
        if claim.get("paid_amount_aed") not in (None, ""):
            try:
                paid_val = float(claim.get("paid_amount_aed"))
            except Exception:
                paid_val = None

        cur.execute(
            """
            UPDATE master_table SET
                encounter_type = ?,
                service_date = ?,
                national_id = ?,
                member_id = ?,
                facility_id = ?,
                unique_id = ?,
                diagnosis_codes = ?,
                service_code = ?,
                paid_amount_aed = ?,
                approval_number = ?
            WHERE tenant_id = ? AND claim_id = ?
            """,
            (
                claim.get("encounter_type"),
                claim.get("service_date"),
                claim.get("national_id"),
                claim.get("member_id"),
                claim.get("facility_id"),
                claim.get("unique_id"),
                claim.get("diagnosis_codes"),
                claim.get("service_code"),
                paid_val,
                claim.get("approval_number"),
                tenant_id,
                claim.get("claim_id"),
            ),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO master_table (
                    tenant_id, claim_id, encounter_type, service_date, national_id,
                    member_id, facility_id, unique_id, diagnosis_codes, service_code,
                    paid_amount_aed, approval_number, status, error_type, error_explanation, recommended_action
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)
                """,
                (
                    tenant_id,
                    claim.get("claim_id"),
                    claim.get("encounter_type"),
                    claim.get("service_date"),
                    claim.get("national_id"),
                    claim.get("member_id"),
                    claim.get("facility_id"),
                    claim.get("unique_id"),
                    claim.get("diagnosis_codes"),
                    claim.get("service_code"),
                    paid_val,
                    claim.get("approval_number"),
                ),
            )
    safe_commit(conn)

    conn.close()


def delete_tenant_data(tenant_id: str, db_path: str = "rcm.db") -> Dict[str, int]:
    """Remove all data for a tenant from master_table, rules, and metrics.

    Returns a dict with counts of deleted rows per table.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    counts = {}
    cur.execute("SELECT COUNT(*) FROM master_table WHERE tenant_id = ?", (tenant_id,))
    counts['master_table'] = cur.fetchone()[0]
    cur.execute("DELETE FROM master_table WHERE tenant_id = ?", (tenant_id,))

    cur.execute("SELECT COUNT(*) FROM rules WHERE tenant_id = ?", (tenant_id,))
    counts['rules'] = cur.fetchone()[0]
    cur.execute("DELETE FROM rules WHERE tenant_id = ?", (tenant_id,))

    cur.execute("SELECT COUNT(*) FROM metrics WHERE tenant_id = ?", (tenant_id,))
    counts['metrics'] = cur.fetchone()[0]
    cur.execute("DELETE FROM metrics WHERE tenant_id = ?", (tenant_id,))

    safe_commit(conn)
    conn.close()
    return counts


def update_claim_result(
    tenant_id: str,
    claim_id: str,
    status: str,
    error_type: str,
    error_explanation: str,
    recommended_action: str,
    db_path: str = "rcm.db",
) -> None:
    """Update adjudication results for a single claim.

    The claim is identified by ``tenant_id`` and ``claim_id``.  Status
    indicates whether the claim is valid or not ('Validated' or 'Not validated').
    ``error_type`` can be 'No error', 'Medical error', 'Technical error' or 'Both'.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE master_table SET
            status = ?,
            error_type = ?,
            error_explanation = ?,
            recommended_action = ?
        WHERE tenant_id = ? AND claim_id = ?
        """,
        (status, error_type, error_explanation, recommended_action, tenant_id, claim_id),
    )
    safe_commit(conn)

    conn.close()


def fetch_claims(tenant_id: str, db_path: str = "rcm.db") -> List[Dict[str, Any]]:
    """Return all claims for a tenant.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM master_table WHERE tenant_id = ?", (tenant_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_metrics(tenant_id: str, metrics: List[Tuple[str, int, float]], db_path: str = "rcm.db") -> None:
    """Persist computed metrics.

    Each entry in ``metrics`` should be a tuple of (category, count, total_paid).
    Existing metrics for the tenant are removed before insertion.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM metrics WHERE tenant_id = ?", (tenant_id,))
    for category, count, total_paid in metrics:
        cur.execute(
            "INSERT INTO metrics (tenant_id, category, count, total_paid) VALUES (?, ?, ?, ?)",
            (tenant_id, category, count, total_paid),
        )
    safe_commit(conn)

    conn.close()


def fetch_metrics(tenant_id: str, db_path: str = "rcm.db") -> List[Dict[str, Any]]:
    """Return aggregated metrics for a tenant.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT category, count, total_paid FROM metrics WHERE tenant_id = ?", (tenant_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_refined_entry(
    tenant_id: str,
    claim_id: str,
    status: str,
    error_type: str,
    error_explanation: str,
    recommended_action: str,
    db_path: str = "rcm.db",
) -> None:
    """Insert a row into the refined_table capturing adjudication results."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO refined_table (tenant_id, claim_id, status, error_type, error_explanation, recommended_action)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tenant_id, claim_id, status, error_type, error_explanation, recommended_action),
    )
    safe_commit(conn)
    conn.close()


def fetch_refined_entries(tenant_id: str, db_path: str = "rcm.db") -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT tenant_id, claim_id, status, error_type, error_explanation, recommended_action, processed_at FROM refined_table WHERE tenant_id = ? ORDER BY id",
        (tenant_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]