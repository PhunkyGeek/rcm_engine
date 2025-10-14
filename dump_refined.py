import sqlite3
import sys

DB = 'rcm.db'

def dump(tenant):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT tenant_id, claim_id, status, error_type, error_explanation, recommended_action, processed_at FROM refined_table WHERE tenant_id = ? ORDER BY id', (tenant,))
    rows = cur.fetchall()
    if not rows:
        print('No refined rows for', tenant)
        return
    for r in rows:
        print(dict(r))

if __name__ == '__main__':
    tenant = sys.argv[1] if len(sys.argv) > 1 else 'rules_test_tenant'
    dump(tenant)
