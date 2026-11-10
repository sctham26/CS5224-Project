"""Bounded authenticated API/upload load test; JSON timings contain no credentials."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit, quote
from urllib.request import Request, urlopen
import uuid


def request(url, token=None, payload=None, method='GET', headers=None, timeout=60):
    h = dict(headers or {})
    if token:
        h['Authorization'] = 'Bearer ' + token
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode()
        h['Content-Type'] = 'application/json'
    try:
        with urlopen(Request(url, data=payload, headers=h, method=method), timeout=timeout) as r:
            body = r.read()
            return r.status, json.loads(body) if body and method != 'PUT' else {}
    except HTTPError as e:
        # Never include response bodies or signed URLs in the report.
        raise RuntimeError(f'HTTP {e.code}') from None


def summary(rows):
    values = sorted(r['seconds'] for r in rows if r['success'])
    return {'total': len(rows), 'successful': len(values), 'failed': len(rows)-len(values),
            'p50_seconds': values[math.ceil(len(values)*.5)-1] if values else None,
            'p95_seconds': values[math.ceil(len(values)*.95)-1] if values else None,
            'max_seconds': max(values) if values else None}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['api', 'upload'])
    p.add_argument('--base-url', default='https://d10rc41o4pb0h.cloudfront.net/api')
    p.add_argument('--requests', type=int, default=20)
    p.add_argument('--concurrency', type=int, default=4)
    p.add_argument('--path', default='/entities?scope=asset')
    p.add_argument('--file', type=Path)
    p.add_argument('--entity')
    p.add_argument('--year', type=int)
    p.add_argument('--timeout', type=int, default=600)
    p.add_argument('--target-seconds', type=float, default=300)
    p.add_argument('--output', type=Path, default=Path('load-test-results.json'))
    a = p.parse_args()
    if not 1 <= a.requests <= 10000 or not 1 <= a.concurrency <= 100 or not 1 <= a.timeout <= 780:
        p.error('Use requests 1–10000, concurrency 1–100, timeout 1–780 seconds')
    if urlsplit(a.base_url).scheme != 'https' or not a.path.startswith('/') or a.path.startswith('//'):
        p.error('Use an HTTPS API base and relative API path')
    token = os.environ.get('SPIP_TEST_TOKEN', '').strip()
    if not token:
        p.error('Set SPIP_TEST_TOKEN to a test tenant access token; never pass it on the command line')
    if a.mode == 'upload' and (not a.file or not a.file.is_file() or not a.entity or not a.year):
        p.error('Upload requires --file, --entity and --year; use a valid test-tenant CSV')
    base = a.base_url.rstrip('/')
    # Fail before generating traffic if authorization/membership is invalid.
    request(base + '/entities?scope=asset', token)

    def run(index):
        started = time.monotonic()
        row = {'index': index, 'success': False}
        try:
            if a.mode == 'api':
                request(base + a.path, token)
            else:
                _, reservation = request(base+'/uploads', token, {}, 'POST')
                signed = reservation['upload_url']
                host = urlsplit(signed)
                if host.scheme != 'https' or not host.hostname or not host.hostname.endswith('.amazonaws.com'):
                    raise RuntimeError('Unexpected upload destination')
                with a.file.open('rb') as stream:
                    request(signed, payload=stream, method='PUT', timeout=a.timeout,
                            headers={'Content-Type': reservation.get('content_type', 'text/csv'), 'Content-Length': str(a.file.stat().st_size)})
                row['upload_seconds'] = time.monotonic()-started
                _, job = request(base+'/jobs', token, {'upload_key': reservation['key'], 'entity_id': a.entity,
                    'reporting_year': a.year, 'scope': 'asset'}, 'POST', {'Idempotency-Key': str(uuid.uuid4())})
                row['job_id'] = job['job_id']
                deadline = time.monotonic() + a.timeout
                while time.monotonic() < deadline:
                    _, state = request(base+'/jobs/'+quote(job['job_id'], safe=''), token)
                    row['job_status'] = state['status']
                    if state['status'] == 'SUCCEEDED':
                        if not state.get('result'):
                            raise RuntimeError('Missing job result')
                        break
                    if state['status'] == 'FAILED':
                        raise RuntimeError('Job failed; inspect tenant-authorized job details')
                    time.sleep(2)
                else:
                    raise RuntimeError('Polling deadline exceeded; job may still be running')
            row['success'] = True
        except Exception as e:
            row['error'] = str(e) if isinstance(e, RuntimeError) else type(e).__name__
        row['seconds'] = round(time.monotonic()-started, 3)
        return row

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
        rows = list(pool.map(run, range(a.requests)))
    result = summary(rows)
    result.update(mode=a.mode, concurrency=a.concurrency, elapsed_seconds=time.monotonic()-start,
                  file_bytes=a.file.stat().st_size if a.mode == 'upload' else None, samples=rows)
    result['passed'] = result['failed'] == 0 and result['p95_seconds'] <= a.target_seconds
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'samples'}, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
