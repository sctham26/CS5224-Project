"""Assign reviewed Cognito role groups; never create IAM roles or change tenants."""
import argparse
import json
from pathlib import Path
import subprocess

GROUPS = {"spip-admin", "spip-backend", "spip-tester", "spip-customer"}

def validate_user(user, assignment):
    attributes = {a["Name"]: a["Value"] for a in user["UserAttributes"]}
    if attributes.get("sub") != assignment["subject"] or attributes.get("email", "").lower() != assignment["email"].lower():
        raise ValueError("Cognito identity differs from the reviewed assignment")
    if assignment["group"] not in GROUPS:
        raise ValueError("Unknown application role group")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--profile", default="sandbox")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.manifest.read_text())
    def aws(service, *command):
        result = subprocess.check_output(["aws", service, *command, "--profile", args.profile,
            "--region", config["region"], "--output", "json"], text=True)
        return json.loads(result) if result.strip() else {}
    if aws("sts", "get-caller-identity")["Account"] != config["account"]:
        raise ValueError("Unexpected AWS account")
    pool = ["--user-pool-id", config["user_pool_id"]]
    reviewed = []
    # Validate every identity before the first mutation.
    for assignment in config["assignments"]:
        user = aws("cognito-idp", "admin-get-user", *pool, "--username", assignment["subject"])
        validate_user(user, assignment)
        existing = aws("cognito-idp", "admin-list-groups-for-user", *pool, "--username", assignment["subject"])
        reviewed.append((assignment, {g["GroupName"] for g in existing["Groups"]}))
    existing_groups = {g["GroupName"] for g in aws("cognito-idp", "list-groups", *pool)["Groups"]}
    for assignment, existing in reviewed:
        target = assignment["group"]
        print(assignment["email"], "->", target, flush=True)
        if not args.apply:
            continue
        if target not in existing_groups:
            aws("cognito-idp", "create-group", *pool, "--group-name", target,
                "--description", f"Application role {target}; backend RBAC enforcement required")
            existing_groups.add(target)
        aws("cognito-idp", "admin-add-user-to-group", *pool, "--username", assignment["subject"], "--group-name", target)
        for group in sorted((existing & GROUPS) - {target}):
            aws("cognito-idp", "admin-remove-user-from-group", *pool, "--username", assignment["subject"], "--group-name", group)
        actual = aws("cognito-idp", "admin-list-groups-for-user", *pool, "--username", assignment["subject"])
        if {g["GroupName"] for g in actual["Groups"]} & GROUPS != {target}:
            raise RuntimeError("Role assignment read-back failed")
    print("Verified role groups." if args.apply else "Dry run only; pass --apply to assign.")

if __name__ == "__main__":
    main()
