import json
from pathlib import Path
import aws_cdk as cdk
from aws_cdk.assertions import Template
from infra.backend_config import BackendConfig
from infra.backend_data_stack import BackendDataStack
from infra.backend_operations_stack import BackendOperationsStack


def test_operator_tasks_keep_import_and_migration_credentials_separate_and_decryptable():
    app = cdk.App()
    env = cdk.Environment(account="825990809862", region="ap-southeast-1")
    config = BackendConfig.from_dict(json.loads((Path(__file__).parents[1] / "fixtures/backend-runtime.json").read_text()))
    data = BackendDataStack(app, "BackendDataStack", config=config, env=env)
    ops = BackendOperationsStack(app, "BackendOperationsStack", data=data, config=config, env=env)
    app.synth()
    template = Template.from_stack(ops)
    tasks = list(template.find_resources("AWS::ECS::TaskDefinition").values())
    assert len(tasks) == 3
    for task in tasks:
        container = task["Properties"]["ContainerDefinitions"][0]
        names = {v["Name"] for v in container["Secrets"]}
        if container["Name"] == "PublicImport":
            assert names == {"SPIP_PUBLIC_DB_CREDENTIALS"}
        elif container["Name"] == "Membership":
            assert names == {"SPIP_TENANT_DB_CREDENTIALS"}
            assert container["EntryPoint"] == ["python", "/opt/spip-cloud/operations.py", "membership"]
            assert container["Command"] == ["--help"]
        else:
            assert container["Name"] == "Migration"
            assert names == {"SPIP_PUBLIC_DB_CREDENTIALS", "SPIP_TENANT_DB_CREDENTIALS"}
        assert "SPIP_ADMIN_CREDENTIALS" not in names
    policies = template.find_resources("AWS::IAM::Policy")
    assert len(policies) == 3
    for policy in policies.values():
        statements = policy["Properties"]["PolicyDocument"]["Statement"]
        decrypt = [v for v in statements if v["Action"] == "kms:Decrypt"]
        assert len(decrypt) == 1 and decrypt[0]["Resource"] != "*"
    template.resource_count_is("AWS::ECS::Service", 0)
