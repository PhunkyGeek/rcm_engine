import base64
import json
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

TENANT = 'testtenant_inproc'

if __name__ == '__main__':
    # Ensure a clean tenant dataset for deterministic test runs
    client.delete('/tenant/testtenant_inproc')

    with open('sample_claims.csv', 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')

    print('POST /upload')
    r = client.post('/upload', json={
        'tenant_id': TENANT,
        'claims_file': b64,
        'technical_rules_file': None,
        'medical_rules_file': None
    })
    print('status', r.status_code)
    print(r.json())

    print('\nPOST /validate')
    r2 = client.post(f'/validate/{TENANT}')
    print('status', r2.status_code)
    print(json.dumps(r2.json(), indent=2))

    print('\nGET /metrics')
    r3 = client.get(f'/metrics/{TENANT}')
    print('status', r3.status_code)
    print(json.dumps(r3.json(), indent=2))

    print('\nGET /results')
    r4 = client.get(f'/results/{TENANT}')
    print('status', r4.status_code)
    print(json.dumps(r4.json(), indent=2))
