"""Optional real-image API/worker runtime; JWT-protected routes only."""
from aws_cdk import (
    CfnOutput, CfnParameter, Duration, RemovalPolicy, Stack,
    aws_apigatewayv2 as gateway, aws_apigatewayv2_authorizers as auth,
    aws_apigatewayv2_integrations as integrations, aws_ec2 as ec2,
    aws_ecs as ecs, aws_elasticloadbalancingv2 as elb, aws_logs as logs,
    aws_kms as kms, aws_s3 as s3, aws_secretsmanager as sm, aws_sqs as sqs, aws_ecr as ecr,
)
from constructs import Construct
from .backend_config import BackendConfig
from .backend_data_stack import BackendDataStack


class BackendRuntimeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, data: BackendDataStack,
                 config: BackendConfig, **kwargs):
        config.validate_runtime()
        super().__init__(scope, construct_id, **kwargs)
        image_digests = {
            name: CfnParameter(self, name.title() + "ImageDigest", type="String",
                default=image.split("@")[1], allowed_pattern=r"sha256:[a-f0-9]{64}",
                description="Immutable application image; retain the previous value on infrastructure updates.")
            for name, image in [("api", config.api_image), ("worker", config.worker_image)]
        }
        api_sg = ec2.SecurityGroup.from_security_group_id(
            self, "ApiIngressTarget", data.api_sg.security_group_id
        )
        # Import grant targets into this stack so IAM grants cannot create
        # reverse dependencies from retained data resources to runtime roles.
        key = kms.Key.from_key_arn(self, "DataKeyRef", data.key.key_arn)
        public_bucket = s3.Bucket.from_bucket_attributes(
            self, "PublicBucketRef", bucket_arn=data.public_bucket.bucket_arn, encryption_key=key)
        tenant_bucket = s3.Bucket.from_bucket_attributes(
            self, "TenantBucketRef", bucket_arn=data.tenant_bucket.bucket_arn, encryption_key=key)
        queue = sqs.Queue.from_queue_attributes(
            self, "QueueRef", queue_arn=data.queue.queue_arn, queue_url=data.queue.queue_url, key_arn=key.key_arn)
        public_secret = sm.Secret.from_secret_attributes(
            self, "PublicCredentialsRef", secret_complete_arn=data.credentials["public_reader"].secret_arn,
            encryption_key=key)
        tenant_secret = sm.Secret.from_secret_attributes(
            self, "TenantCredentialsRef", secret_complete_arn=data.credentials["tenant_app"].secret_arn,
            encryption_key=key)
        environment = {
            "AWS_REGION": self.region, "SPIP_DB_HOST": data.database.db_instance_endpoint_address,
            "SPIP_PUBLIC_DATA_BUCKET": data.public_bucket.bucket_name,
            "SPIP_TENANT_DATA_BUCKET": data.tenant_bucket.bucket_name,
            "SPIP_JOB_QUEUE_URL": data.queue.queue_url, "SPIP_JOB_DLQ_URL": data.dlq.queue_url,
            "SPIP_UPLOAD_URL_TTL_SECONDS": str(config.upload_url_ttl_seconds),
            "SPIP_ALLOWED_ORIGINS": ",".join(config.allowed_origins),
            "SPIP_JWT_ISSUER": config.jwt_issuer, "SPIP_JWT_AUDIENCE": ",".join(config.jwt_audience),
            "SPIP_AUTH_ENABLED": "true", "SPIP_AUTH_ISSUER": config.jwt_issuer,
            "SPIP_AUTH_CLIENT_ID": config.jwt_audience[0], "SPIP_AUTH_SCOPE": config.authorization_scopes[0],
            "SPIP_API_PREFIX": "", "SPIP_JOB_LEASE_SECONDS": str(config.job_lease_seconds),
            "PGSSLROOTCERT": "/opt/spip-cloud/rds-ca.pem",
        }
        secrets = {
            "SPIP_PUBLIC_DB_CREDENTIALS": ecs.Secret.from_secrets_manager(public_secret),
            "SPIP_TENANT_DB_CREDENTIALS": ecs.Secret.from_secrets_manager(tenant_secret),
        }
        self.api_task = ecs.FargateTaskDefinition(self, "ApiTask", cpu=256, memory_limit_mib=512)
        self.worker_task = ecs.FargateTaskDefinition(self, "WorkerTask", cpu=512, memory_limit_mib=1024)
        import re
        for name, task, image, command in [
            ("api", self.api_task, config.api_image,
             ["python", "-m", "uvicorn", "api:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]),
            ("worker", self.worker_task, config.worker_image, list(config.worker_command)),
        ]:
            group = logs.LogGroup(self, f"{name}Log", encryption_key=key,
                                  retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.RETAIN)
            account, region, repository, digest = re.fullmatch(
                r"(\d{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/(.+)@(sha256:[a-f0-9]{64})", image
            ).groups()
            image_repository = ecr.Repository.from_repository_attributes(
                self, f"{name}ImageRepository", repository_name=repository,
                repository_arn=f"arn:{self.partition}:ecr:{region}:{account}:repository/{repository}")
            container_environment = dict(environment)
            if name == "worker" and config.persist_uploads:
                container_environment["SPIP_PERSIST_UPLOADS"] = "1"
            container = task.add_container(
                name, image=ecs.ContainerImage.from_registry(
                    image_repository.repository_uri + "@" + image_digests[name].value_as_string),
                entry_point=["python", "/opt/spip-cloud/entrypoint.py"], command=command,
                environment=container_environment, secrets=secrets,
                logging=ecs.LogDrivers.aws_logs(stream_prefix=name, log_group=group),
            )
            image_repository.grant_pull(task.execution_role)
            if name == "api":
                container.add_port_mappings(ecs.PortMapping(container_port=8000))
        public_bucket.grant_read(self.api_task.task_role)
        key.grant_decrypt(self.api_task.execution_role)
        key.grant_decrypt(self.worker_task.execution_role)
        public_bucket.grant_read(self.worker_task.task_role)
        tenant_bucket.grant_read(self.api_task.task_role, "tenants/*/uploads/*")
        tenant_bucket.grant_put(self.api_task.task_role, "tenants/*/uploads/*")
        tenant_bucket.grant_read(self.api_task.task_role, "tenants/*/jobs/*")
        tenant_bucket.grant_read(self.worker_task.task_role, "tenants/*/uploads/*")
        tenant_bucket.grant_put(self.worker_task.task_role, "tenants/*/jobs/*")
        queue.grant_send_messages(self.api_task.task_role)
        queue.grant_consume_messages(self.worker_task.task_role)

        self.api_service = api_service = ecs.FargateService(
            self, "ApiService", cluster=data.cluster, task_definition=self.api_task,
            desired_count=1, min_healthy_percent=100, max_healthy_percent=200, assign_public_ip=True, security_groups=[api_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            health_check_grace_period=Duration.seconds(60),
        )
        self.worker_service = ecs.FargateService(
            self, "WorkerService", cluster=data.cluster, task_definition=self.worker_task,
            desired_count=1, min_healthy_percent=100, max_healthy_percent=200, assign_public_ip=True, security_groups=[data.worker_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        link_sg = ec2.SecurityGroup(self, "VpcLinkSecurityGroup", vpc=data.vpc)
        alb_sg = ec2.SecurityGroup(self, "AlbSecurityGroup", vpc=data.vpc)
        alb_sg.add_ingress_rule(link_sg, ec2.Port.tcp(80), "HTTP API VPC link only")
        api_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(8000), "Internal ALB only")
        balancer = elb.ApplicationLoadBalancer(
            self, "InternalAlb", vpc=data.vpc, internet_facing=False, security_group=alb_sg,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        )
        listener = balancer.add_listener("Http", port=80, open=False)
        listener.add_targets("Api", port=8000, targets=[api_service],
                             health_check=elb.HealthCheck(path="/health"))
        link = gateway.VpcLink(self, "VpcLink", vpc=data.vpc, security_groups=[link_sg],
                               subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED))
        integration = integrations.HttpAlbIntegration(
            "ApiIntegration", listener, vpc_link=link,
            parameter_mapping=gateway.ParameterMapping().overwrite_path(gateway.MappingValue.request_path()),
        )
        authorizer = auth.HttpJwtAuthorizer("AccessToken", config.jwt_issuer, jwt_audience=list(config.jwt_audience))
        self.api = gateway.HttpApi(
            self, "HttpApi", cors_preflight=gateway.CorsPreflightOptions(
                allow_origins=list(config.allowed_origins),
                allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
                allow_methods=[gateway.CorsHttpMethod.GET, gateway.CorsHttpMethod.POST, gateway.CorsHttpMethod.OPTIONS],
            ),
        )
        self.api.add_routes(path="/health", methods=[gateway.HttpMethod.GET], integration=integration)
        for method, path in [(gateway.HttpMethod.GET, "/entities"),
                             (gateway.HttpMethod.POST, "/uploads"), (gateway.HttpMethod.POST, "/jobs"),
                             (gateway.HttpMethod.GET, "/jobs/{job_id}"),
                             (gateway.HttpMethod.GET, "/analysis/{entity_id}")]:
            self.api.add_routes(path=path, methods=[method], integration=integration,
                                authorizer=authorizer, authorization_scopes=list(config.authorization_scopes))
        CfnOutput(self, "ApiEndpoint", value=self.api.api_endpoint)
        CfnOutput(self, "ApiTaskDefinitionArn", value=self.api_task.task_definition_arn)
        CfnOutput(self, "WorkerTaskDefinitionArn", value=self.worker_task.task_definition_arn)
        CfnOutput(self, "ApiServiceArn", value=self.api_service.service_arn)
        CfnOutput(self, "WorkerServiceArn", value=self.worker_service.service_arn)
        CfnOutput(self, "ClusterName", value=data.cluster.cluster_name)
