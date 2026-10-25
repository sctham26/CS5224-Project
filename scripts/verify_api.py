"""Check live CloudFront-to-backend routing and negative JWT authorization."""
import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def response(url, headers=None):
    try:
        result = urlopen(Request(url, headers=headers or {}), timeout=20)
    except HTTPError as error:
        result = error
    with result:
        return result.status, result.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://d10rc41o4pb0h.cloudfront.net")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    if not base.startswith("https://"):
        raise SystemExit("Use the HTTPS CloudFront URL")
    status, body = response(base + "/api/health")
    if status != 200 or json.loads(body) != {"status": "ok"}:
        raise SystemExit("CloudFront health did not reach the backend: HTTP " + str(status))
    for headers in ({}, {"Authorization": "Bearer invalid-cloud-smoke-token"}):
        status, _ = response(base + "/api/entities?scope=asset", headers)
        if status != 401:
            raise SystemExit("A protected route must reject missing/invalid tokens; received HTTP " + str(status))
    print("Verified CloudFront /api/health=200 and /api/entities=401 for missing/invalid tokens.")
    print("A real account and approved membership are still required for an authorized-user test.")


if __name__ == "__main__":
    main()
