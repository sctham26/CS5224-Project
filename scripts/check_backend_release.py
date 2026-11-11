"""Block automatic schema/dependency changes until cloud operations reviews them."""
import argparse
import hashlib
import json
from pathlib import Path


def fingerprints(root):
    paths = sorted(p for p in (root / "migrations").rglob("*") if p.is_file()) + [root / "requirements.txt", root / "pyproject.toml"]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--baseline", type=Path, default=Path("backend_cloud/release-baseline.json"))
    args = parser.parse_args()
    expected = json.loads(args.baseline.read_text())["files"]
    if fingerprints(args.source) != expected:
        raise SystemExit("Schema/dependency files changed. Cloud operations must review migrations, dependency locks and the release baseline before automatic deployment.")
    print("Schema and dependency declarations match the reviewed release baseline.")


if __name__ == "__main__":
    main()
