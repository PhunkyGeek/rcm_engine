# db_manager.py
# Streamlit Database Manager for the Mini RCM Validation Engine
# Usage:
#   1) pip install streamlit pandas
#   2) streamlit run db_manager.py
#
# This tool lets you: browse tables, filter/search, edit data (replace table),
# run ad-hoc SQL, export/import CSV — all against a local SQLite database file.
#
# Default DB file: 'rcm.db' in the current working directory.
# You can change it at runtime via the sidebar.

import os
import io
import sqlite3
import pandas as pd
import streamlit as st
from contextlib import closing

st.set_page_config(page_title="RCM DB Manager", layout="wide")

# ---------- Sidebar: database selection ----------
st.sidebar.title("Database")
default_db = "rcm.db"
db_path = st.sidebar.text_input("SQLite DB path", value=default_db, help="Path to your SQLite database file (e.g., rcm.db)")
refresh_btn = st.sidebar.button("🔄 Refresh")

def get_conn(path: str):
  if not os.path.exists(path):
    st.error(f"Database file not found: {path}")
    return None
  conn = sqlite3.connect(path)
  conn.row_factory = sqlite3.Row
  return conn

conn = get_conn(db_path)

st.title("🗄️ RCM Database Manager")
st.caption("Browse, filter, edit, query, and export your RCM data.")

if not conn:
  st.stop()

# ---------- Utility functions ----------
def list_tables(connection: sqlite3.Connection):
  q = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
  return [r["name"] for r in connection.execute(q).fetchall()]

def read_table(connection: sqlite3.Connection, table: str) -> pd.DataFrame:
  return pd.read_sql_query(f"SELECT * FROM {table}", connection)

def distinct_values(connection: sqlite3.Connection, table: str, col: str):
  try:
    rows = connection.execute(f"SELECT DISTINCT {col} FROM {table} ORDER BY {col}").fetchall()
    return [r[0] for r in rows if r[0] is not None]
  except sqlite3.OperationalError:
    return []

def replace_table_from_df(connection: sqlite3.Connection, table: str, df: pd.DataFrame):
  with connection:
    # Safer full replace: create temp, then swap
    tmp = f"__tmp_{table}"
    df.to_sql(tmp, connection, if_exists="replace", index=False)
    # Drop old and rename
    connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.execute(f"ALTER TABLE {tmp} RENAME TO {table}")

def export_csv(df: pd.DataFrame, filename: str = "export.csv"):
  csv = df.to_csv(index=False).encode("utf-8")
  st.download_button("⬇️ Download CSV", data=csv, file_name=filename, mime="text/csv")

def run_query(connection: sqlite3.Connection, sql: str):
  with closing(connection.cursor()) as cur:
    cur.execute(sql)
    if sql.strip().lower().startswith("select"):
      rows = cur.fetchall()
      cols = [desc[0] for desc in cur.description]
      return pd.DataFrame(rows, columns=cols)
    else:
      connection.commit()
      return pd.DataFrame({"result": [f"OK ({cur.rowcount} rows affected)"]})

# ---------- Main: table explorer ----------
st.subheader("📋 Table Explorer")
tables = list_tables(conn)
if not tables:
  st.info("No user tables found. Once you upload/validate claims, tables will appear here.")
  st.stop()

table = st.selectbox("Choose a table", options=tables, index=max(0, tables.index("claims_master")) if "claims_master" in tables else 0)

df = read_table(conn, table)

# ---------- Filters (tenant/status/error) if present ----------
filters = st.expander("🔎 Filters", expanded=False)
with filters:
  filter_cols = []
  if "tenant_id" in df.columns:
    tenants = ["(All)"] + sorted([t for t in df["tenant_id"].dropna().unique().tolist()])
    tenant_sel = st.selectbox("tenant_id", tenants, index=0)
    if tenant_sel != "(All)":
      df = df[df["tenant_id"] == tenant_sel]
      filter_cols.append(("tenant_id", tenant_sel))
  if "status" in df.columns:
    statuses = ["(All)"] + sorted([s for s in df["status"].dropna().unique().tolist()])
    status_sel = st.selectbox("status", statuses, index=0)
    if status_sel != "(All)":
      df = df[df["status"] == status_sel]
      filter_cols.append(("status", status_sel))
  if "error_type" in df.columns:
    etypes = ["(All)"] + sorted([e for e in df["error_type"].dropna().unique().tolist()])
    etype_sel = st.selectbox("error_type", etypes, index=0)
    if etype_sel != "(All)":
      df = df[df["error_type"] == etype_sel]
      filter_cols.append(("error_type", etype_sel))

  # Free-text search across string columns
  search = st.text_input("Search (matches any text column)")
  if search:
    mask = pd.Series([False] * len(df))
    for c in df.select_dtypes(include=["object", "string"]).columns:
      mask = mask | df[c].astype(str).str.contains(search, case=False, na=False)
    df = df[mask]

# ---------- Data grid + editing ----------
st.write(f"**Preview:** `{table}`  — {len(df):,} rows")
edited_df = st.data_editor(
  df,
  use_container_width=True,
  hide_index=True,
  num_rows="dynamic",  # allow add/remove rows
  key=f"grid_{table}"
)

col1, col2, col3 = st.columns([1,1,1])
with col1:
  export_csv(edited_df, f"{table}.csv")
with col2:
  st.download_button(
    "📄 Download JSON",
    data=edited_df.to_json(orient="records", indent=2).encode("utf-8"),
    file_name=f"{table}.json",
    mime="application/json"
  )
with col3:
  st.info("Tip: You can add/delete rows in the grid, then save.")

st.warning("⚠️ Saving will **replace the entire table** with the edited grid. Use with care.", icon="⚠️")
confirm = st.checkbox("I understand and want to replace the table", value=False)
if st.button("💾 Save changes (replace table)", disabled=not confirm):
  try:
    replace_table_from_df(conn, table, edited_df)
    st.success(f"Saved. Table `{table}` replaced with {len(edited_df):,} rows.")
    if refresh_btn:
      st.experimental_rerun()
  except Exception as e:
    st.error(f"Save failed: {e}")

# ---------- Import/Append from CSV ----------
st.subheader("➕ Import / Append CSV")
upload_csv = st.file_uploader("Choose CSV to append (columns must match)", type=["csv"])
if upload_csv is not None:
  try:
    new_df = pd.read_csv(upload_csv)
    st.write("Preview of CSV to append:", new_df.head())
    if st.button("Append to table"):
      with conn:
        new_df.to_sql(table, conn, if_exists="append", index=False)
      st.success(f"Appended {len(new_df):,} rows to `{table}`")
  except Exception as e:
    st.error(f"Upload failed: {e}")

# ---------- Query runner ----------
st.subheader("🧪 SQL Query Runner")
st.caption("Run ad‑hoc SELECT/UPDATE/DELETE/INSERT. Be careful — changes are immediate.")
default_sql = f"SELECT * FROM {table} LIMIT 50;"
sql = st.text_area("SQL", height=140, value=default_sql, help="Write a valid SQLite statement. For schema: PRAGMA table_info(table_name);")
if st.button("▶️ Run SQL"):
  try:
    result = run_query(conn, sql)
    st.dataframe(result, use_container_width=True)
    if not result.empty:
      export_csv(result, "query_result.csv")
  except Exception as e:
    st.error(f"Query error: {e}")
