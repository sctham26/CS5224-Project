"""Invoke the fixed image-only broker and verify CloudFormation/ECS completion."""
import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--region", "ap-southeast-1",
        "--output", "json", "--no-cli-pager"], text=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    if aws("sts", "get-caller-identity")["Account"] != "825990809862":
        raise SystemExit("Unexpected AWS account")
    metadata = json.loads(args.metadata.read_text())
    repository = "825990809862.dkr.ecr.ap-southeast-1.amazonaws.com/spip-backend@"
    if not metadata["image"].startswith(repository):
        raise ValueError("Unexpected image repository")
    digest = metadata["image"][len(repository):]
    payload = {"image_digest": digest, "source_sha": metadata["backend_commit"], "release_id": args.release_id}
    with tempfile.TemporaryDirectory() as directory:
        result_path = Path(directory) / "response.json"
        response = aws("lambda", "invoke", "--function-name", "spip-backend-release",
            "--cli-binary-format", "raw-in-base64-out", "--payload", json.dumps(payload), str(result_path))
        if response.get("FunctionError"):
            raise SystemExit("Release broker rejected the update: " + result_path.read_text())
        result = json.loads(result_path.read_text())
    if result.get("image_digest") != digest or result.get("stack") != "BackendRuntimeStack":
        raise SystemExit("Unexpected release response")
    deadline = time.monotonic() + 1500
    last_status = None
    while time.monotonic() < deadline:
        stack = aws("cloudformation", "describe-stacks", "--stack-name", "BackendRuntimeStack")["Stacks"][0]
        status = stack["StackStatus"]
        if status != last_status:
            print("Runtime stack:", status, flush=True)
            last_status = status
        if "ROLLBACK" in status or "FAILED" in status:
            raise SystemExit("Release failed; inspect CloudFormation stack events: " + status)
        parameters = {p["ParameterKey"]: p["ParameterValue"] for p in stack["Parameters"]}
        if status in {"CREATE_COMPLETE", "UPDATE_COMPLETE"} and all(
                parameters.get(key) == digest for key in ("ApiImageDigest", "WorkerImageDigest")):
            break
        time.sleep(15)
    else:
        raise SystemExit("Timed out waiting for runtime update")
    outputs = {p["OutputKey"]: p["OutputValue"] for p in stack["Outputs"]}
    services = aws("ecs", "describe-services", "--cluster", outputs["ClusterName"], "--services",
        outputs["ApiServiceArn"], outputs["WorkerServiceArn"])
    if services.get("failures") or len(services["services"]) != 2:
        raise SystemExit("Could not verify both application services")
    for service in services["services"]:
        if (service["runningCount"] != 1 or service["pendingCount"] != 0 or
                len(service["deployments"]) != 1 or service["deployments"][0]["rolloutState"] != "COMPLETED"):
            raise SystemExit("Application service is not stable")
        definition = aws("ecs", "describe-task-definition", "--task-definition", service["taskDefinition"])
        containers = definition["taskDefinition"]["containerDefinitions"]
        if len(containers) != 1 or containers[0]["image"] != metadata["image"]:
            raise SystemExit("Service is not running the requested immutable image")
    print("API and worker are stable on", metadata["image"])


if __name__ == "__main__":
    main()
