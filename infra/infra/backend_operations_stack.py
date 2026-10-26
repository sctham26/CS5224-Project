"""Unstarted migration/import tasks; runtime services receive none of these secrets."""
from aws_cdk import CfnOutput, Stack, aws_ecs as ecs, aws_ecr as ecr, aws_logs as logs
from constructs import Construct
from .backend_data_stack import BackendDataStack
from .backend_config import BackendConfig


class BackendOperationsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, data: BackendDataStack,
                 config: BackendConfig, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        config.validate_runtime()
        repository = ecr.Repository.from_repository_name(self, "Images", "spip-backend")
        digest = config.api_image.split("@")[1]
        for label, command, credentials in [
            ("Migration", ["migrate"], {"PUBLIC": "public_migrator", "TENANT": "tenant_migrator"}),
            ("PublicImport", ["import-baseline", "--dry-run"], {"PUBLIC": "public_writer"}),
        ]:
            task = ecs.FargateTaskDefinition(self, label + "Task", cpu=512, memory_limit_mib=1024)
            # Execution-role grants live in this stack: avoid reverse stack references.
            from aws_cdk import aws_secretsmanager as sm, aws_kms as kms
            key = kms.Key.from_key_arn(self, label + "Key", data.key.key_arn)
            secrets = {}
            for name, role in credentials.items():
                secret = sm.Secret.from_secret_attributes(self, label + role,
                    secret_complete_arn=data.credentials[role].secret_arn, encryption_key=key)
                secrets[f"SPIP_{name}_DB_CREDENTIALS"] = ecs.Secret.from_secrets_manager(secret)
            task.add_container(label, image=ecs.ContainerImage.from_ecr_repository(repository, tag=digest),
                entry_point=["python", "/opt/spip-cloud/operations.py"], command=command,
                environment={"SPIP_DB_HOST": data.database.db_instance_endpoint_address,
                    "PGSSLROOTCERT": "/opt/spip-cloud/rds-ca.pem"}, secrets=secrets,
                logging=ecs.LogDrivers.aws_logs(stream_prefix=label,
                    log_group=logs.LogGroup(self, label + "Log", retention=logs.RetentionDays.ONE_MONTH)))
            key.grant_decrypt(task.execution_role)
            CfnOutput(self, label + "TaskDefinitionArn", value=task.task_definition_arn)
