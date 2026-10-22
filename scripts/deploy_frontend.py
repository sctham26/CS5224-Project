"""Publish an already-built Vite site using AWS CLI credentials (including OIDC)."""
import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def aws(*args):
    return subprocess.check_output(["aws", *args, "--no-cli-pager"], text=True).strip()


def deploy(dist, bucket, distribution_id, account_id, commit):
    dist = Path(dist).resolve()
    if not (dist / "index.html").is_file() or not (dist / "assets").is_dir():
        raise ValueError("Expected a Vite build containing index.html and assets/")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Release commit must be a complete Git SHA")
    if not re.fullmatch(r"\d{12}", account_id):
        raise ValueError("AWS_ACCOUNT_ID must be a 12-digit account number")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError("Invalid frontend bucket name")
    if not re.fullmatch(r"[A-Z0-9]+", distribution_id):
        raise ValueError("Invalid CloudFront distribution ID")
    actual = aws("sts", "get-caller-identity", "--query", "Account", "--output", "text")
    if actual != account_id:
        raise ValueError(f"AWS account mismatch: expected {account_id}, got {actual}")

    destination = f"s3://{bucket}"
    # Upload dependencies before switching HTML. Keep previous hashed assets.
    aws("s3", "sync", str(dist / "assets"), destination + "/assets",
        "--cache-control", "public,max-age=31536000,immutable", "--only-show-errors")
    aws("s3", "sync", str(dist), destination,
        "--exclude", "assets/*", "--exclude", "index.html", "--exclude", "release.json",
        "--cache-control", "public,max-age=300", "--only-show-errors")
    aws("s3", "cp", str(dist / "index.html"), destination + "/index.html",
        "--content-type", "text/html", "--cache-control", "no-cache,max-age=0,must-revalidate",
        "--only-show-errors")
    with tempfile.TemporaryDirectory() as temp:
        release = Path(temp) / "release.json"
        release.write_text(json.dumps({"commit": commit}) + "\n")
        aws("s3", "cp", str(release), destination + "/release.json",
            "--content-type", "application/json", "--cache-control", "no-store",
            "--only-show-errors")
    invalidation = aws("cloudfront", "create-invalidation", "--distribution-id", distribution_id,
                       "--paths", "/*", "--query", "Invalidation.Id", "--output", "text")
    aws("cloudfront", "wait", "invalidation-completed", "--distribution-id", distribution_id,
        "--id", invalidation)
    print(f"Published {commit}; CloudFront invalidation {invalidation} completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default="frontend/dist")
    args = parser.parse_args()
    deploy(args.dist, os.environ["FRONTEND_BUCKET_NAME"], os.environ["CLOUDFRONT_DISTRIBUTION_ID"],
           os.environ["AWS_ACCOUNT_ID"], os.environ["GITHUB_SHA"])
