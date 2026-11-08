"""Deploy reviewed sandbox infrastructure with all routing context enabled."""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["diff", "deploy"], default="diff", nargs="?")
    parser.add_argument("--profile", default="sandbox")
    args = parser.parse_args()
    env = dict(os.environ, AWS_PROFILE=args.profile, AWS_REGION="ap-southeast-1", AWS_DEFAULT_REGION="ap-southeast-1")
    infra = Path(__file__).resolve().parents[1] / "infra"
    command = ["npx", "cdk", args.action, "--all", "-c", "backend_config=backend.sandbox.json"]
    for flag in ("enable_auth", "enable_backend", "enable_backend_operations", "enable_backend_runtime", "enable_backend_release"):
        command += ["-c", flag + "=true"]
    subprocess.run(command, cwd=infra, env=env, check=True)


if __name__ == "__main__":
    main()
