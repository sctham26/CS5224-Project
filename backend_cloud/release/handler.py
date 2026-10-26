"""Accept an existing ECR digest; change only two parameters of the existing template."""
import os
import re

_clients = {}


def client(service):
    if service not in _clients:
        import boto3
        from botocore.config import Config
        _clients[service] = boto3.client(service, config=Config(
            retries={"mode": "standard", "total_max_attempts": 3},
            connect_timeout=5, read_timeout=15))
    return _clients[service]


def handler(event, context):
    if not isinstance(event, dict) or set(event) != {"image_digest", "source_sha", "release_id"}:
        raise ValueError("Only image_digest, source_sha and release_id are accepted")
    digest, source, release = (event[key] for key in ("image_digest", "source_sha", "release_id"))
    for value, pattern in [(digest, r"sha256:[a-f0-9]{64}"), (source, r"[a-f0-9]{40}"),
                           (release, r"gh-[0-9]+-[0-9]+")]:
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError("Invalid release identifier")
    image = client("ecr").describe_images(repositoryName="spip-backend",
        imageIds=[{"imageDigest": digest}])["imageDetails"][0]
    if not any(tag.startswith(source + "-") for tag in image.get("imageTags", [])):
        raise ValueError("Image is not tagged for the supplied backend source")
    cfn = client("cloudformation")
    stack_name = os.environ["RUNTIME_STACK"]
    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}:
        raise ValueError("Runtime stack is busy or needs operator recovery")
    previous = {p["ParameterKey"]: p["ParameterValue"] for p in stack["Parameters"]}
    keys = {"ApiImageDigest", "WorkerImageDigest"}
    if not keys.issubset(previous):
        raise ValueError("Image parameters have not been provisioned by cloud operations")
    if all(previous[key] == digest for key in keys):
        return {"stack": stack_name, "image_digest": digest, "changed": False}
    parameters = [({"ParameterKey": key, "ParameterValue": digest} if key in keys else
                   {"ParameterKey": key, "UsePreviousValue": True}) for key in previous]
    # Never accept a template, role, capabilities, parameter names or stack from the caller.
    cfn.update_stack(StackName=stack_name, UsePreviousTemplate=True,
        Parameters=parameters, Capabilities=["CAPABILITY_NAMED_IAM"], ClientRequestToken=release)
    return {"stack": stack_name, "image_digest": digest, "changed": True}
