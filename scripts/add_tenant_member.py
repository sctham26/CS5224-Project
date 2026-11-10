"""Assign an existing Cognito user to an explicitly selected tenant via ECS."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid


def resolve_subject(users, email):
    matches = [u for u in users if any(a.get("Name") == "email" and
               a.get("Value") == email for a in u.get("Attributes", []))]
    if len(matches) != 1 or not matches[0].get("Enabled"):
        raise ValueError("Expected exactly one enabled Cognito user with this email")
    attrs = {a["Name"]: a["Value"] for a in matches[0]["Attributes"]}
    return str(uuid.UUID(attrs["sub"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--tenant", required=True, help="Explicit approved tenant; existing assignments are replaced")
    parser.add_argument("--profile", default="sandbox")
    parser.add_argument("--dry-run", action="store_true", help="Resolve identity and print assignment without starting a task")
    args = parser.parse_args()
    if not re.fullmatch(r"[^\s@\"\\]+@[^\s@\"\\]+\.[^\s@\"\\]+", args.email):
        parser.error("Provide a valid email")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.tenant):
        parser.error("Provide an explicit valid tenant ID")
    def aws(*command):
        return json.loads(subprocess.check_output(["aws", *command, "--profile", args.profile,
            "--region", "ap-southeast-1", "--output", "json", "--no-cli-pager"], text=True))
    def outputs(name):
        return {v["OutputKey"]: v["OutputValue"] for v in
                aws("cloudformation", "describe-stacks", "--stack-name", name)["Stacks"][0]["Outputs"]}
    if aws("sts", "get-caller-identity")["Account"] != "825990809862":
        raise SystemExit("Unexpected AWS account")
    pool = outputs("AuthStack")["UserPoolId"]
    users = aws("cognito-idp", "list-users", "--user-pool-id", pool,
                "--filter", 'email = "' + args.email + '"')["Users"]
    subject = resolve_subject(users, args.email)
    print(json.dumps({"email": args.email, "sub": subject, "tenant": args.tenant,
                      "dry_run": args.dry_run}), flush=True)
    if args.dry_run:
        return
    task = outputs("BackendOperationsStack")["MembershipTaskDefinitionArn"]
    data = outputs("BackendDataStack")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "outputs.json"
        path.write_text(json.dumps({"BackendDataStack": data}))
        subprocess.run([sys.executable, str(Path(__file__).with_name("run_backend_task.py")),
            str(path), "--task-definition", task, "--container", "Membership", "--command",
            json.dumps(["--sub", subject, "--tenant", args.tenant])],
            env=dict(os.environ, AWS_PROFILE=args.profile), check=True)


if __name__ == "__main__":
    main()
