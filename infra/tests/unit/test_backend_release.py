import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import aws_cdk as cdk
from aws_cdk.assertions import Template
import pytest
from infra.backend_config import BackendConfig
from infra.backend_data_stack import BackendDataStack
from infra.backend_runtime_stack import BackendRuntimeStack
from infra.backend_release_stack import BackendReleaseStack

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("release_handler", ROOT / "backend_cloud/release/handler.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
DIGEST = "sha256:" + "a" * 64
SOURCE = "b" * 40
EVENT = {"image_digest": DIGEST, "source_sha": SOURCE, "release_id": "gh-123-1"}


@pytest.fixture
def clients(monkeypatch):
    cfn, ecr = Mock(), Mock()
    cfn.describe_stacks.return_value = {"Stacks": [{"StackStatus": "UPDATE_COMPLETE", "Parameters": [
        {"ParameterKey": "ApiImageDigest", "ParameterValue": "sha256:" + "c" * 64},
        {"ParameterKey": "WorkerImageDigest", "ParameterValue": "sha256:" + "c" * 64},
        {"ParameterKey": "BootstrapVersion", "ParameterValue": "/cdk-bootstrap/version"}]}]}
    ecr.describe_images.return_value = {"imageDetails": [{"imageTags": [SOURCE + "-support-123-1"]}]}
    monkeypatch.setattr(release, "client", lambda name: {"ecr": ecr, "cloudformation": cfn}[name])
    monkeypatch.setenv("RUNTIME_STACK", "BackendRuntimeStack")
    return SimpleNamespace(cfn=cfn, ecr=ecr)


def test_broker_cannot_replace_template_roles_or_nonimage_parameters(clients):
    assert release.handler(EVENT, None)["changed"] is True
    call = clients.cfn.update_stack.call_args.kwargs
    assert call == {"StackName": "BackendRuntimeStack", "UsePreviousTemplate": True,
        "Parameters": [{"ParameterKey": "ApiImageDigest", "ParameterValue": DIGEST},
            {"ParameterKey": "WorkerImageDigest", "ParameterValue": DIGEST},
            {"ParameterKey": "BootstrapVersion", "UsePreviousValue": True}],
        "Capabilities": ["CAPABILITY_NAMED_IAM"], "ClientRequestToken": "gh-123-1"}


@pytest.mark.parametrize("bad", [
    {**EVENT, "template": "arbitrary"}, {**EVENT, "image_digest": "latest"},
    {**EVENT, "source_sha": "backend-analysis"}, {**EVENT, "release_id": "bad;command"},
])
def test_broker_rejects_arbitrary_inputs_before_aws(bad, clients):
    with pytest.raises(ValueError):
        release.handler(bad, None)
    clients.ecr.describe_images.assert_not_called()
    clients.cfn.update_stack.assert_not_called()


def test_broker_does_not_deploy_unrelated_source_or_busy_stack(clients):
    clients.ecr.describe_images.return_value = {"imageDetails": [{"imageTags": ["other-source"]}]}
    with pytest.raises(ValueError, match="source"):
        release.handler(EVENT, None)
    clients.cfn.update_stack.assert_not_called()
    clients.ecr.describe_images.return_value = {"imageDetails": [{"imageTags": [SOURCE + "-support"]}]}
    clients.cfn.describe_stacks.return_value["Stacks"][0]["StackStatus"] = "UPDATE_IN_PROGRESS"
    with pytest.raises(ValueError, match="busy"):
        release.handler(EVENT, None)
    clients.cfn.update_stack.assert_not_called()


def test_matching_image_is_idempotent(clients):
    for parameter in clients.cfn.describe_stacks.return_value["Stacks"][0]["Parameters"][:2]:
        parameter["ParameterValue"] = DIGEST
    assert release.handler(EVENT, None)["changed"] is False
    clients.cfn.update_stack.assert_not_called()


def test_github_role_has_no_infrastructure_or_secret_write_permissions():
    app = cdk.App()
    env = cdk.Environment(account="825990809862", region="ap-southeast-1")
    config = BackendConfig.from_dict(json.loads((ROOT / "infra/tests/fixtures/backend-runtime.json").read_text()))
    data = BackendDataStack(app, "BackendDataStack", config=config, env=env)
    runtime = BackendRuntimeStack(app, "BackendRuntimeStack", data=data, config=config, env=env)
    stack = BackendReleaseStack(app, "BackendReleaseStack", data=data, runtime=runtime, env=env)
    app.synth()
    template = Template.from_stack(stack)
    roles = template.find_resources("AWS::IAM::Role")
    github = next(v for v in roles.values() if v["Properties"].get("RoleName") == "spip-backend-github-release")
    trust = github["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"]
    assert trust["token.actions.githubusercontent.com:sub"].endswith(":ref:refs/heads/backend-analysis")
    policies = template.find_resources("AWS::IAM::Policy")
    github_policy = next(v["Properties"]["PolicyDocument"] for key, v in policies.items() if "GitHubReleaseRole" in key)
    actions = set()
    for statement in github_policy["Statement"]:
        action = statement["Action"]
        actions.update([action] if isinstance(action, str) else action)
    assert {"ecr:PutImage", "ecr:BatchGetImage", "lambda:InvokeFunction", "cloudformation:DescribeStacks"}.issubset(actions)
    assert not any(action.startswith(("iam:", "secretsmanager:", "rds:")) for action in actions)
    assert "cloudformation:UpdateStack" not in actions and "ecs:UpdateService" not in actions
    assert "ecs:DescribeTaskDefinition" not in actions
