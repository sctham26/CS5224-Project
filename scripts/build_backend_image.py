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
    parser.add_argument("--output", type=Path, default=Path("infra/backend-image.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sha = subprocess.check_output(["git", "rev-parse", args.ref + "^{commit}"], cwd=root, text=True).strip()
    support_digest = hashlib.sha256(b"".join((root / "backend_cloud" / name).read_bytes()
        for name in ("runtime.Dockerfile", "runtime-requirements.lock", "entrypoint.py", "operations.py"))).hexdigest()
    image_tag = sha + "-" + support_digest[:12]
    tag = args.repository + ":" + image_tag
    with tempfile.TemporaryDirectory(prefix="spip-backend-") as directory:
        context = Path(directory)
        archive = subprocess.check_output(["git", "archive", sha], cwd=root)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(context, filter="data")
        support = context / ".cloud"
        support.mkdir()
        shutil.copy(root / "backend_cloud/runtime-requirements.lock", support / "requirements.lock")
        for name in ("entrypoint.py", "operations.py"):
            shutil.copy(root / "backend_cloud" / name, support / name)
        subprocess.run(["docker", "build", "--platform", "linux/amd64", "--build-arg", "BACKEND_COMMIT=" + sha,
            "-f", str(root / "backend_cloud/runtime.Dockerfile"), "-t", tag, str(context)], check=True)
    region = args.repository.split(".")[3]
    password = subprocess.check_output(["aws", "ecr", "get-login-password", "--profile", args.profile, "--region", region])
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
    digest = subprocess.check_output(["aws", "ecr", "describe-images", "--profile", args.profile, "--region", region,
        "--repository-name", repository_name, "--image-ids", "imageTag=" + image_tag,
        "--query", "imageDetails[0].imageDigest", "--output", "text"], text=True).strip()
    print("Immutable image:", args.repository + "@" + digest)
    args.output.write_text(json.dumps({"backend_commit": sha, "cloud_support_sha256": support_digest,
        "image": args.repository + "@" + digest}, indent=2) + "\n")


if __name__ == "__main__":
    main()
