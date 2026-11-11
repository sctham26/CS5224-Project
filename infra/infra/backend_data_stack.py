"""Private data foundation, without business tables, parsing or running services."""
import json
from pathlib import Path
from aws_cdk import (
    CfnOutput, Duration, RemovalPolicy, Stack, Tags,
    aws_cloudwatch as cw, aws_ec2 as ec2, aws_ecs as ecs,
    aws_ecr_assets as assets, aws_kms as kms, aws_logs as logs,
    aws_rds as rds, aws_s3 as s3, aws_secretsmanager as sm, aws_sqs as sqs, aws_ecr as ecr,
)
from constructs import Construct
from .backend_config import BackendConfig


class BackendDataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, config: BackendConfig, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        self.config = config
        self.backend_repository = ecr.Repository(self, "BackendImages", repository_name="spip-backend",
            image_scan_on_push=True, image_tag_mutability=ecr.TagMutability.IMMUTABLE,
            removal_policy=RemovalPolicy.RETAIN)
        self.key = kms.Key(self, "DataKey", enable_key_rotation=True, removal_policy=RemovalPolicy.RETAIN)
        # No NAT gateways: Fargate tasks later use public subnets for outbound
        # HTTPS only, with no internet ingress. RDS stays in isolated subnets.
        self.vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=0, subnet_configuration=[
            ec2.SubnetConfiguration(name="Tasks", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
            ec2.SubnetConfiguration(name="Data", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24),
        ])
        self.vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)
        self.api_sg = ec2.SecurityGroup(self, "ApiSecurityGroup", vpc=self.vpc)
        self.worker_sg = ec2.SecurityGroup(self, "WorkerSecurityGroup", vpc=self.vpc)
        self.bootstrap_sg = ec2.SecurityGroup(self, "BootstrapSecurityGroup", vpc=self.vpc)
        db_sg = ec2.SecurityGroup(self, "DatabaseSecurityGroup", vpc=self.vpc)
        for peer in (self.api_sg, self.worker_sg, self.bootstrap_sg):
            db_sg.add_ingress_rule(peer, ec2.Port.tcp(5432), "PostgreSQL from approved tasks only")
        cors = []
        if config.allowed_origins:
            cors = [s3.CorsRule(
                allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.GET, s3.HttpMethods.HEAD],
                allowed_origins=list(config.allowed_origins),
                allowed_headers=["Content-Type", "x-amz-checksum-sha256"],
                exposed_headers=["ETag", "x-amz-version-id"],
                max_age=300,
            )]
        self.public_bucket = s3.Bucket(
            self, "PublicData", block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.KMS, encryption_key=self.key,
            bucket_key_enabled=True, enforce_ssl=True, versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.tenant_bucket = s3.Bucket(
            self, "TenantData", block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.KMS, encryption_key=self.key,
            bucket_key_enabled=True, enforce_ssl=True, versioned=True, cors=cors,
            removal_policy=RemovalPolicy.RETAIN,
        )
        # Raw data is retained; no S3 notification guesses which job to run.
        self.dlq = sqs.Queue(
            self, "JobDLQ", encryption=sqs.QueueEncryption.KMS, encryption_master_key=self.key,
            retention_period=Duration.days(14), enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.queue = sqs.Queue(
            self, "JobQueue", encryption=sqs.QueueEncryption.KMS, encryption_master_key=self.key,
            visibility_timeout=Duration.seconds(config.visibility_seconds),
            receive_message_wait_time=Duration.seconds(20), retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(queue=self.dlq, max_receive_count=config.max_receive_count),
            enforce_ssl=True, removal_policy=RemovalPolicy.RETAIN,
        )
        cw.Alarm(self, "DeadLetterAlarm", metric=self.dlq.metric_approximate_number_of_messages_visible(),
                 threshold=1, evaluation_periods=1, treat_missing_data=cw.TreatMissingData.NOT_BREACHING)

        db_name = "spip-backend-data"
        self.database_identifier = db_name
        self.database_log = logs.LogGroup(
            self, "DatabaseLog", log_group_name=f"/aws/rds/instance/{db_name}/postgresql",
            encryption_key=self.key, retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.RETAIN,
        )
        # CloudWatch Logs uses its regional service principal to encrypt streams.
        from aws_cdk import aws_iam as iam
        self.key.add_to_resource_policy(iam.PolicyStatement(
            principals=[iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")],
            actions=["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"],
            resources=["*"],
            conditions={"ArnLike": {"kms:EncryptionContext:aws:logs:arn":
                f"arn:{self.partition}:logs:{self.region}:{self.account}:log-group:*"}},
        ))
        version = rds.PostgresEngineVersion.of(config.postgres_version, config.postgres_version.split(".")[0])
        self.database = rds.DatabaseInstance(
            self, "Postgres", instance_identifier=db_name,
            engine=rds.DatabaseInstanceEngine.postgres(version=version),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO),
            vpc=self.vpc, vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[db_sg], publicly_accessible=False, multi_az=config.multi_az,
            database_name="spip_public", manage_master_user_password=True,
            credentials=rds.Credentials.from_username("spip_operator", encryption_key=self.key),
            storage_encrypted=True, storage_encryption_key=self.key,
            storage_type=rds.StorageType.GP3, allocated_storage=20, max_allocated_storage=100,
            parameters={"rds.force_ssl": "1"}, backup_retention=Duration.days(7),
            deletion_protection=True, delete_automated_backups=False,
            removal_policy=RemovalPolicy.SNAPSHOT,
            enable_performance_insights=True, performance_insight_encryption_key=self.key,
            performance_insight_retention=rds.PerformanceInsightRetention.DEFAULT,
            cloudwatch_logs_exports=["postgresql"], auto_minor_version_upgrade=True,
        )
        self.database.node.add_dependency(self.database_log)
        Tags.of(self.database).add("created_by", "rds-oss-skill")
        Tags.of(self.database).add("project", "SPIP")
        Tags.of(self.database).add("generation_model", "gpt-6")
        # Each login is database-specific; business migrations remain backend-owned.
        self.credentials = {}
        for role, database in {
            "public_reader": "spip_public", "tenant_app": "spip_tenant",
            "public_writer": "spip_public", "public_migrator": "spip_public",
            "tenant_migrator": "spip_tenant",
        }.items():
            self.credentials[role] = sm.Secret(
                self, f"Credentials-{role}", encryption_key=self.key,
                generate_secret_string=sm.SecretStringGenerator(
                    secret_string_template=json.dumps({"username": f"spip_{role}", "dbname": database}),
                    generate_string_key="password", password_length=32, exclude_punctuation=True,
                ), removal_policy=RemovalPolicy.RETAIN,
            )
        self.cluster = ecs.Cluster(self, "Cluster", vpc=self.vpc)
        self.bootstrap_task = ecs.FargateTaskDefinition(self, "DatabaseBootstrapTask", cpu=256, memory_limit_mib=512)
        bootstrap_secrets = {"SPIP_ADMIN_CREDENTIALS": ecs.Secret.from_secrets_manager(self.database.secret)}
        bootstrap_secrets.update({f"SPIP_{role.upper()}_CREDENTIALS": ecs.Secret.from_secrets_manager(secret)
                                  for role, secret in self.credentials.items()})
        log = logs.LogGroup(self, "BootstrapLog", encryption_key=self.key,
                            retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.RETAIN)
        self.bootstrap_task.add_container(
            "bootstrap", image=ecs.ContainerImage.from_asset(
                str(Path(__file__).resolve().parents[2] / "backend_cloud"),
                platform=assets.Platform.LINUX_AMD64,
            ), environment={"SPIP_DB_HOST": self.database.db_instance_endpoint_address,
                            "PGSSLROOTCERT": "/opt/spip-cloud/rds-ca.pem"},
            secrets=bootstrap_secrets, logging=ecs.LogDrivers.aws_logs(stream_prefix="bootstrap", log_group=log),
        )
        self.key.grant_decrypt(self.bootstrap_task.execution_role)
        for name, value in {
            "VpcId": self.vpc.vpc_id, "ClusterName": self.cluster.cluster_name,
            "BackendRepositoryUri": self.backend_repository.repository_uri,
            "TaskSubnets": ",".join(s.subnet_id for s in self.vpc.public_subnets),
            "BootstrapSecurityGroupId": self.bootstrap_sg.security_group_id,
            "BootstrapTaskDefinitionArn": self.bootstrap_task.task_definition_arn,
            "DatabaseHost": self.database.db_instance_endpoint_address,
            "PublicDataBucket": self.public_bucket.bucket_name,
            "TenantDataBucket": self.tenant_bucket.bucket_name,
            "JobQueueUrl": self.queue.queue_url, "JobDeadLetterQueueUrl": self.dlq.queue_url,
            "PublicMigrationSecretArn": self.credentials["public_migrator"].secret_arn,
            "TenantMigrationSecretArn": self.credentials["tenant_migrator"].secret_arn,
            "PublicWriterSecretArn": self.credentials["public_writer"].secret_arn,
        }.items():
            CfnOutput(self, name, value=value)
