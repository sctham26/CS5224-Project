"""GitHub publishes application images; a fixed broker owns the parameter-only update."""
from pathlib import Path
from aws_cdk import (CfnOutput, Duration, Stack, aws_iam as iam, aws_ecr as ecr,
                     aws_lambda as lambda_, aws_logs as logs)
from constructs import Construct


class BackendReleaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, data, runtime, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        repository = ecr.Repository.from_repository_name(self, "Images", "spip-backend")
        group = logs.LogGroup(self, "ReleaseLog", log_group_name="/aws/lambda/spip-backend-release",
            retention=logs.RetentionDays.ONE_MONTH)
        broker = lambda_.Function(self, "ImageRelease", function_name="spip-backend-release",
            runtime=lambda_.Runtime.PYTHON_3_12, handler="handler.handler",
            code=lambda_.Code.from_asset(str(Path(__file__).resolve().parents[2] / "backend_cloud/release"),
                exclude=["__pycache__", "*.pyc"]),
            timeout=Duration.seconds(60), memory_size=128,
            environment={"RUNTIME_STACK": runtime.stack_name},
            log_group=group)
        runtime_arn = f"arn:{self.partition}:cloudformation:{self.region}:{self.account}:stack/{runtime.stack_name}/*"
        broker.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudformation:DescribeStacks", "cloudformation:UpdateStack"], resources=[runtime_arn]))
        broker.add_to_role_policy(iam.PolicyStatement(
            actions=["ecr:DescribeImages"], resources=[repository.repository_arn]))
        provider = f"arn:{self.partition}:iam::{self.account}:oidc-provider/token.actions.githubusercontent.com"
        role = iam.Role(self, "GitHubReleaseRole", role_name="spip-backend-github-release",
            description="Publish backend ECR images and invoke the fixed image-only release broker",
            assumed_by=iam.FederatedPrincipal(provider, {"StringEquals": {
                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                "token.actions.githubusercontent.com:sub":
                    "repo:sctham26@337585649/CS5224-Project@1403949135:ref:refs/heads/backend-analysis",
            }}, "sts:AssumeRoleWithWebIdentity"), max_session_duration=Duration.hours(1))
        repository.grant_push(role)
        role.add_to_policy(iam.PolicyStatement(actions=["ecr:DescribeImages"],
            resources=[repository.repository_arn]))
        broker.grant_invoke(role)
        role.add_to_policy(iam.PolicyStatement(actions=["cloudformation:DescribeStacks"], resources=[runtime_arn]))
        role.add_to_policy(iam.PolicyStatement(actions=["ecs:DescribeServices"],
            resources=[runtime.api_service.service_arn, runtime.worker_service.service_arn]))
        CfnOutput(self, "GitHubRoleArn", value=role.role_arn)
        CfnOutput(self, "ReleaseFunctionName", value=broker.function_name)
