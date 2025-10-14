import base64
import json
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)
TENANT = 'rules_test_tenant'

# We'll reuse the sample_claims.csv created earlier but ensure one claim uses SC2
# which our technical rule flags, and another claim includes D123 in diagnosis_codes

# Prepare a modified claims set inline for clarity
claims_csv = """claim_id,paid_amount_aed,service_code,diagnosis_codes
R001,100.00,SC1,
R002,200.00,SC2,
R003,50.00,SC3,D123
"""

def upload_claims_and_rules():
    # Clear any existing data for a deterministic test run
    client.delete(f'/tenant/{TENANT}')

    b64_claims = base64.b64encode(claims_csv.encode('utf-8')).decode('ascii')
    with open('sample_technical_rules.json','r') as f:
        tech = f.read()
    with open('sample_medical_rules.json','r') as f:
        med = f.read()

    # Upload via /upload
    r = client.post('/upload', json={
        'tenant_id': TENANT,
        'claims_file': b64_claims,
        'technical_rules_file': tech,
        'medical_rules_file': med
    })
    assert r.status_code == 200, r.text
    return r.json()


def run_validation_and_get_metrics():
    r = client.post(f'/validate/{TENANT}')
    assert r.status_code == 200, r.text
    payload = r.json()
    metrics = payload.get('metrics') or []
    return payload, metrics


if __name__ == '__main__':
    print('Uploading claims and rules...')
    up = upload_claims_and_rules()
    print('Upload response:', up)

    print('Running validation...')
    payload, metrics = run_validation_and_get_metrics()
    print('Validate payload keys:', list(payload.keys()))
    print('Metrics returned:')
    print(json.dumps(metrics, indent=2))

    cats = {m['category']: m for m in metrics}
    print('\nAssertions:')
    assert 'Technical error' in cats, 'Technical error category missing from metrics'
    assert 'Medical error' in cats, 'Medical error category missing from metrics'
    print('Both Technical and Medical categories present in metrics')
    # Print counts for visibility
    print('Technical count:', cats['Technical error']['count'])
    print('Medical count:', cats['Medical error']['count'])
