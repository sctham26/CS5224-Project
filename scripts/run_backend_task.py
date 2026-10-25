"""Run one explicit operator task inside the backend VPC and verify exit status."""
import argparse
import json
import subprocess
from pathlib import Path


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--output", "json", "--no-cli-pager"], text=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("outputs", type=Path)
    parser.add_argument("--task-definition", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--command", required=True, help="Explicit JSON argument array; never a shell command")
    parser.add_argument("--region", default="ap-southeast-1")
    args = parser.parse_args()
    command = json.loads(args.command)
    if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
        raise ValueError("Command must be a nonempty JSON string array")
    if aws("sts", "get-caller-identity", "--region", args.region)["Account"] != "825990809862":
        raise SystemExit("Unexpected AWS account")
    data = json.loads(args.outputs.read_text())["BackendDataStack"]
    request = {
        "cluster": data["ClusterName"], "taskDefinition": args.task_definition, "launchType": "FARGATE", "count": 1,
        "networkConfiguration": {"awsvpcConfiguration": {
            "subnets": data["TaskSubnets"].split(","), "securityGroups": [data["BootstrapSecurityGroupId"]],
            "assignPublicIp": "ENABLED"}},
        "overrides": {"containerOverrides": [{"name": args.container, "command": command}]},
    }
    started = aws("ecs", "run-task", "--region", args.region, "--cli-input-json", json.dumps(request))
    if started.get("failures") or len(started.get("tasks", [])) != 1:
        raise SystemExit("Task placement failed: " + json.dumps(started.get("failures")))
    arn = started["tasks"][0]["taskArn"]
    print("Waiting for operator task:", arn, flush=True)
    subprocess.run(["aws", "ecs", "wait", "tasks-stopped", "--cluster", data["ClusterName"],
        "--tasks", arn, "--region", args.region], check=True)
    result = aws("ecs", "describe-tasks", "--cluster", data["ClusterName"], "--tasks", arn, "--region", args.region)
    task = result["tasks"][0]
    containers = task.get("containers", [])
    if len(containers) != 1 or containers[0].get("exitCode") != 0:
        raise SystemExit("Operator task failed: " + task.get("stoppedReason", "") + "; inspect its CloudWatch log.")
    print("Operator task completed successfully.", flush=True)


if __name__ == "__main__":
    main()
