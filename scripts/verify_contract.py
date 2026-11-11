"""Acceptance checks for the analytics API; run by the cloud team after deploying.

Stdlib only, so it runs from any laptop or ECS task without installing the app.

    python scripts/verify_contract.py --base-url https://dxxxx.cloudfront.net/api --token <access-token>
    python scripts/verify_contract.py --base-url http://localhost:8000        # local, auth disabled
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REQUIRED_ENTITY_FIELDS = ("entity_id", "entity_name", "property_type", "region",
                          "reporting_years", "latest_reporting_year")
REQUIRED_METRIC_FIELDS = ("metric_code", "standardised_value", "comparability_status",
                          "canonical_unit", "benchmark", "gap_analysis")
REQUIRED_TOP_LEVEL = ("tenant_id", "reporting_year", "entity_id", "entity_name",
                      "peer_cohort", "metrics")

results: list[tuple[str, bool, str]] = []


def call(method: str, url: str, token: str | None, body: bytes | None = None,
         headers: dict | None = None) -> tuple[int, object]:
    request = urllib.request.Request(url, data=body, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json" if body else "text/plain")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except ValueError:
            return exc.code, raw
    except urllib.error.URLError as exc:
        return 0, f"unreachable: {exc.reason}"


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("SPIP_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.environ.get("SPIP_TOKEN"))
    parser.add_argument("--entity", default=None, help="entity_id to analyse; default: first from /entities")
    parser.add_argument("--allow-auth-off", action="store_true",
                        help="accept 200 on /entities without a token (local runs)")
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    # /health is deliberately unprefixed for the ALB probe, even when the gateway keeps /api.
    api_base = base[: -len("/api")] if base.endswith("/api") else base

    status, body = call("GET", f"{api_base}/health", None)
    check(f"GET {api_base}/health -> 200", status == 200, f"got {status}")

    status, body = call("GET", f"{base}/entities", args.token)
    if args.token:
        check(f"GET {base}/entities (token) -> 200", status == 200, f"got {status}: {body}")
    elif status in (401, 403):
        check(f"GET {base}/entities (no token) -> 401", True, f"got {status}")
    elif status == 200 and args.allow_auth_off:
        check(f"GET {base}/entities (no token, auth off)", True, "got 200")
    else:
        check(f"GET {base}/entities (no token) -> 401", False, f"got {status}: auth may be disabled")

    if status == 200 and isinstance(body, dict):
        entities = body.get("entities") or []
        check("/entities returns entities", bool(entities), f"{len(entities)} entity(ies)")
        if entities:
            missing = [f for f in REQUIRED_ENTITY_FIELDS if f not in entities[0]]
            check("entity fields present", not missing, f"missing {missing}")
            entity_id = args.entity or entities[0]["entity_id"]
            status, analysis = call("GET", f"{base}/analysis/{entity_id}?scope=asset", args.token)
            check(f"GET /analysis/{entity_id} -> 200", status == 200, f"got {status}: {analysis}"[:300])
            if status == 200 and isinstance(analysis, dict):
                missing = [f for f in REQUIRED_TOP_LEVEL if f not in analysis]
                check("analysis top-level fields", not missing, f"missing {missing}")
                metrics = analysis.get("metrics") or []
                check("metrics non-empty", bool(metrics), f"{len(metrics)} metric(s)")
                if metrics:
                    missing = [f for f in REQUIRED_METRIC_FIELDS if f not in metrics[0]]
                    check("metric fields present", not missing, f"missing {missing}")
                cohort = analysis.get("peer_cohort") or {}
                size = cohort.get("sample_size_n")
                check("peer cohort reported", isinstance(size, int),
                      f"sample_size_n={size} (benchmark null when < 5)")
    else:
        entity_id = args.entity

    status, _ = call("GET", f"{base}/analysis/DOES_NOT_EXIST_XYZ?scope=asset", args.token)
    check("unknown entity -> 404", status == 404, f"got {status}")

    status, _ = call("GET", f"{base}/jobs/job_does_not_exist", args.token)
    check("unknown job -> 404", status in (404, 401), f"got {status}")
    if status == 401:
        check("GET /jobs requires auth", True, "401 without/with invalid token")

    payload = json.dumps({"upload_key": "tenants/none/uploads/x.csv", "entity_id": "X"}).encode()
    status, body = call("POST", f"{base}/jobs", args.token, body=payload)
    check("POST /jobs without Idempotency-Key -> 422", status in (422, 503),
          f"got {status} (503 = pipeline not configured)")

    print()
    failed = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
