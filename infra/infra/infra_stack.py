"""Static frontend hosting. Application releases do not require CDK privileges."""
from aws_cdk import (
    CfnOutput, Duration, RemovalPolicy, Stack,
    aws_cloudfront as cloudfront, aws_cloudfront_origins as origins,
    aws_iam as iam, aws_s3 as s3,
)
from constructs import Construct


class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.web_bucket = s3.Bucket(
            self, "WebBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        # Rewrite browser navigation only. Missing assets and /api/* keep errors.
        routing = cloudfront.Function(
            self, "SpaRouting",
            code=cloudfront.FunctionCode.from_inline("""
function handler(event) {
    var request = event.request;
    var uri = request.uri;
    if (uri !== '/api' && uri.indexOf('/api/') !== 0 &&
        uri !== '/assets' && uri.indexOf('/assets/') !== 0 &&
        uri.split('/').pop().indexOf('.') === -1) {
        request.uri = '/index.html';
    }
    return request;
}
"""),
        )
        cache = cloudfront.CachePolicy(
            self, "WebCache",
            min_ttl=Duration.seconds(0),
            default_ttl=Duration.minutes(5),
            max_ttl=Duration.days(365),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )
        self.distribution = cloudfront.Distribution(
            self, "WebDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.web_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                cache_policy=cache,
                compress=True,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                function_associations=[cloudfront.FunctionAssociation(
                    function=routing,
                    event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                )],
            ),
        )
        # Reuse an account-wide provider when one exists; never adopt it.
        provider_arn = self.node.try_get_context("github_oidc_provider_arn")
        if not provider_arn:
            provider_arn = iam.CfnOIDCProvider(
                self, "GitHubOidc",
                url="https://token.actions.githubusercontent.com",
                client_id_list=["sts.amazonaws.com"],
            ).attr_arn
        # Verified with GitHub's OIDC configuration API on 2026-10-22.
        prefix = self.node.try_get_context("github_subject_prefix") or (
            "repo:sctham26@337585649/CS5224-Project@1403949135"
        )
        self.deploy_role = iam.Role(
            self, "FrontendDeployRole",
            description="Upload SPIP frontend releases and invalidate its CDN only",
            assumed_by=iam.FederatedPrincipal(
                provider_arn,
                {"StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    "token.actions.githubusercontent.com:sub": [
                        f"{prefix}:ref:refs/heads/cloud-config",
                        f"{prefix}:ref:refs/heads/main",
                    ],
                }},
                "sts:AssumeRoleWithWebIdentity",
            ),
            max_session_duration=Duration.hours(1),
        )
        # Omit DeleteObject: old hashed assets support already-open pages.
        self.deploy_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket", "s3:GetBucketLocation"],
            resources=[self.web_bucket.bucket_arn],
        ))
        self.deploy_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject"],
            resources=[self.web_bucket.arn_for_objects("*")],
        ))
        self.deploy_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"],
            resources=[self.distribution.distribution_arn],
        ))
        CfnOutput(self, "FrontendBucketName", value=self.web_bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
        CfnOutput(self, "FrontendUrl", value=f"https://{self.distribution.distribution_domain_name}")
        CfnOutput(self, "FrontendDeployRoleArn", value=self.deploy_role.role_arn)
