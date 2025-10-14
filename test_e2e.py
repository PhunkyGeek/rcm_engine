import base64
import json
import urllib.request
import urllib.error
import time

BASE = 'http://127.0.0.1:8000'
TENANT = 'testtenant'

def post_json(path, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(BASE + path, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


if __name__ == '__main__':
    # Read and encode CSV
    with open('sample_claims.csv', 'rb') as f:
        b = f.read()
    b64 = base64.b64encode(b).decode('ascii')

    print('Uploading sample claims...')
    try:
        res = post_json('/upload', {
            'tenant_id': TENANT,
            'claims_file': b64,
            'technical_rules_file': None,
            'medical_rules_file': None
        })
        print('Upload response:', res)
    except urllib.error.HTTPError as e:
        print('Upload failed:', e.read().decode())
        raise

    print('Triggering validation...')
    try:
        vres = post_json(f'/validate/{TENANT}', {})
        print('Validate response keys:', list(vres.keys()))
        print('Processed:', vres.get('processed'))
    except urllib.error.HTTPError as e:
        print('Validate failed:', e.read().decode())
        raise

    time.sleep(0.5)
    print('\nFetching metrics...')
    m = get_json(f'/metrics/{TENANT}')
    print(json.dumps(m, indent=2))

    print('\nFetching results (count)...')
    r = get_json(f'/results/{TENANT}')
    print('Returned claims:', len(r.get('claims', [])))
    # Print a small sample
    for c in r.get('claims', [])[:5]:
        print('-', c.get('claim_id'), c.get('status'), c.get('error_type'))
