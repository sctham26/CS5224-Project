"""Package a pinned Git backend snapshot without modifying its source branch."""
import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import time
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--profile", default="sandbox")
    parser.add_argument("--source-repo", type=Path)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--tag-suffix", default="")
    parser.add_argument("--output", type=Path, default=Path("infra/backend-image.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source_root = (args.source_repo or root).resolve()
    sha = subprocess.check_output(["git", "rev-parse", args.ref + "^{commit}"], cwd=source_root, text=True).strip()
    support_digest = hashlib.sha256(b"".join((root / "backend_cloud" / name).read_bytes()
        for name in ("runtime.Dockerfile", "runtime-requirements.lock", "entrypoint.py", "operations.py"))).hexdigest()
    image_tag = sha + "-" + support_digest[:12]
    if args.tag_suffix:
        import re
        if not re.fullmatch(r"[a-z0-9-]{1,50}", args.tag_suffix):
            raise ValueError("Invalid immutable tag suffix")
        image_tag += "-" + args.tag_suffix
    tag = args.repository + ":" + image_tag
    with tempfile.TemporaryDirectory(prefix="spip-backend-") as directory:
        context = Path(directory)
        archive = subprocess.check_output(["git", "archive", sha], cwd=source_root)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(context, filter="data")
        support = context / ".cloud"
        support.mkdir()
        shutil.copy(root / "backend_cloud/runtime-requirements.lock", support / "requirements.lock")
        for name in ("entrypoint.py", "operations.py"):
            shutil.copy(root / "backend_cloud" / name, support / name)
        subprocess.run(["docker", "build", "--platform", "linux/amd64", "--build-arg", "BACKEND_COMMIT=" + sha,
            "-f", str(root / "backend_cloud/runtime.Dockerfile"), "-t", tag, str(context)], check=True)
        if args.test:
            subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64",
                "--mount", f"type=bind,src={context / 'tests'},dst=/app/tests,readonly",
                "--mount", f"type=bind,src={context / 'data'},dst=/app/data,readonly",
                "--mount", f"type=bind,src={context / 'pyproject.toml'},dst=/app/pyproject.toml,readonly",
                tag, "python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], check=True)
    metadata = {"backend_commit": sha, "cloud_support_sha256": support_digest, "tag": tag}
    if args.build_only:
        args.output.write_text(json.dumps(metadata, indent=2) + "\n")
        return
    profile = ["--profile", args.profile] if args.profile else []
    region = args.repository.split(".")[3]
    password = subprocess.check_output(["aws", "ecr", "get-login-password", *profile, "--region", region])
    subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin", args.repository.split("/")[0]],
                   input=password, check=True, stdout=subprocess.DEVNULL)
    for attempt in range(3):
        result = subprocess.run(["docker", "push", tag])
        if result.returncode == 0:
            break
        if attempt == 2:
            raise SystemExit("ECR push failed after three attempts; the remote tag was not selected for deployment.")
        time.sleep(2)
    repository_name = args.repository.split("/", 1)[1]
    digest = subprocess.check_output(["aws", "ecr", "describe-images", *profile, "--region", region,
        "--repository-name", repository_name, "--image-ids", "imageTag=" + image_tag,
        "--query", "imageDetails[0].imageDigest", "--output", "text"], text=True).strip()
    print("Immutable image:", args.repository + "@" + digest)
    args.output.write_text(json.dumps({**metadata, "image": args.repository + "@" + digest}, indent=2) + "\n")


if __name__ == "__main__":
    main()
