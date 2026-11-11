"""Run the reviewed one-off database setup task and require a zero container exit."""
import argparse
import json
import subprocess
from pathlib import Path


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--output", "json", "--no-cli-pager"], text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", type=Path)
    parser.add_argument("--region", default="ap-southeast-1")
    args = parser.parse_args()
    outputs = json.loads(args.outputs.read_text())["BackendDataStack"]
    identity = aws("sts", "get-caller-identity", "--region", args.region)
    if identity["Account"] != "825990809862":
        raise SystemExit("Unexpected AWS account; database bootstrap not started")
    request = {
        "cluster": outputs["ClusterName"], "taskDefinition": outputs["BootstrapTaskDefinitionArn"],
        "launchType": "FARGATE", "count": 1,
        "networkConfiguration": {"awsvpcConfiguration": {
            "subnets": outputs["TaskSubnets"].split(","),
            "securityGroups": [outputs["BootstrapSecurityGroupId"]], "assignPublicIp": "ENABLED",
        }},
    }
    started = aws("ecs", "run-task", "--region", args.region, "--cli-input-json", json.dumps(request))
    if started.get("failures") or len(started.get("tasks", [])) != 1:
        raise SystemExit("Bootstrap task was not started; inspect ECS task-placement errors")
    arn = started["tasks"][0]["taskArn"]
    print("Waiting for database bootstrap:", arn, flush=True)
    subprocess.run(["aws", "ecs", "wait", "tasks-stopped", "--cluster", outputs["ClusterName"],
                    "--tasks", arn, "--region", args.region], check=True)
    result = aws("ecs", "describe-tasks", "--cluster", outputs["ClusterName"], "--tasks", arn, "--region", args.region)
    if result.get("failures") or not result.get("tasks"):
        raise SystemExit("Cannot read bootstrap completion status")
    containers = result["tasks"][0].get("containers", [])
    if len(containers) != 1 or containers[0].get("exitCode") != 0:
        raise SystemExit("Database bootstrap failed; inspect its protected CloudWatch log")
    print("Database bootstrap succeeded. Backend business migrations/RLS are still required.")


if __name__ == "__main__":
    main()
