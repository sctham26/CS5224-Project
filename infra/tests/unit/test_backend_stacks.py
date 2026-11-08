import json
from pathlib import Path
import pytest
import aws_cdk as cdk
from aws_cdk.assertions import Template
from infra.backend_config import BackendConfig
from infra.backend_data_stack import BackendDataStack
from infra.backend_runtime_stack import BackendRuntimeStack


def stacks(runtime=False, persist_uploads=False):
    config = BackendConfig(
        persist_uploads=persist_uploads,
        allowed_origins=("https://example.cloudfront.net",),
        api_image="825990809862.dkr.ecr.ap-southeast-1.amazonaws.com/api@sha256:" + "a" * 64,
        worker_image="825990809862.dkr.ecr.ap-southeast-1.amazonaws.com/worker@sha256:" + "b" * 64,
        worker_command=("python", "-m", "worker"), jwt_issuer="https://issuer.example",
        jwt_audience=("test-client",), authorization_scopes=("spip/access",),
    )
    app = cdk.App()
    env = cdk.Environment(account="825990809862", region="ap-southeast-1")
    data = BackendDataStack(app, "BackendDataStack", config=config, env=env)
    worker = BackendRuntimeStack(app, "BackendRuntimeStack", data=data, config=config, env=env) if runtime else None
    # Synth both stacks together to detect cross-stack dependency cycles.
    app.synth()
    return Template.from_stack(data), Template.from_stack(worker) if worker else None


def items(template, kind):
    return list(template.find_resources(kind).values())


def test_data_boundary_and_retention():
    data, _ = stacks()
    data.resource_count_is("AWS::EC2::NatGateway", 0)
    data.has_resource_properties("AWS::RDS::DBInstance", {
        "Engine": "postgres", "DBName": "spip_public", "PubliclyAccessible": False,
        "MultiAZ": True, "StorageEncrypted": True, "DeletionProtection": True,
        "ManageMasterUserPassword": True, "BackupRetentionPeriod": 7,
        "EnableCloudwatchLogsExports": ["postgresql"],
    })
    data.has_resource_properties("AWS::RDS::DBParameterGroup", {"Parameters": {"rds.force_ssl": "1"}})
    data.resource_count_is("AWS::S3::Bucket", 2)
    for bucket in items(data, "AWS::S3::Bucket"):
        assert bucket["DeletionPolicy"] == "Retain"
        assert bucket["Properties"]["VersioningConfiguration"]["Status"] == "Enabled"
        assert all(bucket["Properties"]["PublicAccessBlockConfiguration"].values())
        assert "NotificationConfiguration" not in bucket["Properties"]
    # Only SG references may connect to PostgreSQL; no CIDR rule opens the database.
    rules = [v["Properties"] for v in items(data, "AWS::EC2::SecurityGroupIngress")]
    inline = [r for v in items(data, "AWS::EC2::SecurityGroup") for r in v["Properties"].get("SecurityGroupIngress", [])]
    db_rules = [r for r in rules + inline if r.get("FromPort") == 5432]
    assert len(db_rules) == 3
    assert all("SourceSecurityGroupId" in r and "CidrIp" not in r for r in db_rules)


def test_queue_has_retry_dlq_and_encryption():
    data, _ = stacks()
    queues = items(data, "AWS::SQS::Queue")
    assert len(queues) == 2
    assert all("KmsMasterKeyId" in q["Properties"] for q in queues)
    main = next(q["Properties"] for q in queues if "RedrivePolicy" in q["Properties"])
    assert main["RedrivePolicy"]["maxReceiveCount"] == 5
    assert main["VisibilityTimeout"] == 900
    assert main["ReceiveMessageWaitTimeSeconds"] == 20
    data.resource_count_is("AWS::CloudWatch::Alarm", 1)


def test_application_cannot_receive_admin_or_migration_credentials():
    data, runtime = stacks(runtime=True)
    for task in items(runtime, "AWS::ECS::TaskDefinition"):
        container = task["Properties"]["ContainerDefinitions"][0]
        names = {secret["Name"] for secret in container["Secrets"]}
        assert names == {"SPIP_PUBLIC_DB_CREDENTIALS", "SPIP_TENANT_DB_CREDENTIALS"}
        parameter = container["Name"].title() + "ImageDigest"
        assert parameter in json.dumps(container["Image"])
        assert runtime.to_json()["Parameters"][parameter]["AllowedPattern"] == r"sha256:[a-f0-9]{64}"
        assert container["EntryPoint"] == ["python", "/opt/spip-cloud/entrypoint.py"]
        env = {item["Name"]: item["Value"] for item in container["Environment"]}
        assert env["SPIP_AUTH_ENABLED"] == "true"
        assert env["SPIP_API_PREFIX"] == ""
        assert env["SPIP_AUTH_SCOPE"] == "spip/access"
        assert env["SPIP_JOB_LEASE_SECONDS"] == "840"
    # Administrative credentials are confined to an explicitly launched task.
    bootstrap = items(data, "AWS::ECS::TaskDefinition")[0]["Properties"]["ContainerDefinitions"][0]
    assert "SPIP_ADMIN_CREDENTIALS" in {secret["Name"] for secret in bootstrap["Secrets"]}
    routes = items(runtime, "AWS::ApiGatewayV2::Route")
    assert len(routes) == 6
    protected = [r for r in routes if r["Properties"]["RouteKey"] != "GET /health"]
    assert len(protected) == 5
    assert next(r for r in routes if r["Properties"]["RouteKey"] == "GET /health")["Properties"]["AuthorizationType"] == "NONE"
    assert all(r["Properties"]["AuthorizationType"] == "JWT" for r in protected)
    assert all(r["Properties"]["AuthorizationScopes"] == ["spip/access"] for r in protected)
    assert not any("/analyze" == r["Properties"]["RouteKey"].split()[-1] for r in protected)
    assert not items(runtime, "AWS::ElasticLoadBalancingV2::LoadBalancer")[0]["Properties"]["Scheme"] == "internet-facing"
    for policy in items(runtime, "AWS::IAM::Policy"):
        content = json.dumps(policy)
        assert "Credentials-public_migrator" not in content
        assert "Credentials-tenant_migrator" not in content
    execution_policies = [r for name, r in runtime.find_resources("AWS::IAM::Policy").items() if "ExecutionRole" in name]
    assert len(execution_policies) == 2
    for policy in execution_policies:
        assert "kms:Decrypt" in json.dumps(policy["Properties"]["PolicyDocument"])
    # IAM policies may send/consume the work queue, but no ordinary DLQ consumer.
    assert "s3:DeleteObject" not in json.dumps(items(runtime, "AWS::IAM::Policy"))


@pytest.mark.parametrize("kwargs", [
    {"multi_az": "false"}, {"visibility_seconds": 0}, {"max_receive_count": True},
    {"job_lease_seconds": 900},
    {"allowed_origins": ("*",)}, {"allowed_origins": ("http://example.com",)},
])
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        BackendConfig(**kwargs)


def test_placeholder_runtime_is_rejected():
    with pytest.raises(ValueError, match="immutable"):
        BackendConfig().validate_runtime()
    with pytest.raises(ValueError):
        BackendConfig.from_dict({"worker_command": "python worker.py"})


@pytest.mark.parametrize("enabled", [False, True])
def test_persistence_is_opt_in_and_worker_only(enabled):
    _, runtime = stacks(runtime=True, persist_uploads=enabled)
    for task in items(runtime, "AWS::ECS::TaskDefinition"):
        container = task["Properties"]["ContainerDefinitions"][0]
        env = {item["Name"]: item["Value"] for item in container["Environment"]}
        if container["Name"] == "worker" and enabled:
            assert env["SPIP_PERSIST_UPLOADS"] == "1"
        else:
            assert "SPIP_PERSIST_UPLOADS" not in env


def test_persistence_rejects_string_boolean():
    with pytest.raises(ValueError, match="persist_uploads"):
        BackendConfig.from_dict({"persist_uploads": "true"})
