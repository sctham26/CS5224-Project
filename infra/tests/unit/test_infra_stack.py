import json
import subprocess

import aws_cdk as cdk
from aws_cdk.assertions import Template
from infra.infra_stack import InfraStack


def template(context=None):
    app = cdk.App(context=context or {})
    stack = InfraStack(app, "TestFrontend", env=cdk.Environment(
        account="825990809862", region="ap-southeast-1"))
    return Template.from_stack(stack)


def resources_of(t, resource_type):
    return list(t.find_resources(resource_type).values())


def test_bucket_and_cdn_access_boundary():
    t = template()
    t.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        },
        "VersioningConfiguration": {"Status": "Enabled"},
        "BucketEncryption": {"ServerSideEncryptionConfiguration": [
            {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
        ]},
    })
    bucket = resources_of(t, "AWS::S3::Bucket")[0]
    assert bucket["DeletionPolicy"] == "Retain"
    policy = resources_of(t, "AWS::S3::BucketPolicy")[0]["Properties"]["PolicyDocument"]
    statements = policy["Statement"]
    assert any(s["Effect"] == "Deny" and s.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false" for s in statements)
    cf = next(s for s in statements if s.get("Principal") == {"Service": "cloudfront.amazonaws.com"})
    assert "AWS:SourceArn" in cf["Condition"]["StringEquals"]
    t.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)
    distribution = resources_of(t, "AWS::CloudFront::Distribution")[0]["Properties"]["DistributionConfig"]
    assert distribution["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    assert "CustomErrorResponses" not in distribution
    t.has_resource_properties("AWS::CloudFront::CachePolicy", {"CachePolicyConfig": {"MinTTL": 0}})


def test_oidc_restricts_subjects_and_release_permissions():
    t = template()
    role = resources_of(t, "AWS::IAM::Role")[0]["Properties"]
    trust = role["AssumeRolePolicyDocument"]["Statement"][0]
    condition = trust["Condition"]["StringEquals"]
    prefix = "repo:sctham26@337585649/CS5224-Project@1403949135"
    assert condition["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert condition["token.actions.githubusercontent.com:sub"] == [
        f"{prefix}:ref:refs/heads/cloud-config", f"{prefix}:ref:refs/heads/main"]
    statements = resources_of(t, "AWS::IAM::Policy")[0]["Properties"]["PolicyDocument"]["Statement"]
    actions = {action for s in statements for action in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])}
    assert actions == {"s3:ListBucket", "s3:GetBucketLocation", "s3:GetObject", "s3:PutObject",
                       "cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"}
    assert all(s["Resource"] != "*" for s in statements)


def test_existing_oidc_provider_is_referenced_without_recreating():
    t = template({"github_oidc_provider_arn": "arn:aws:iam::825990809862:oidc-provider/token.actions.githubusercontent.com"})
    t.resource_count_is("AWS::IAM::OIDCProvider", 0)


def test_spa_routes_preserve_api_and_missing_asset_errors():
    t = template()
    code = resources_of(t, "AWS::CloudFront::Function")[0]["Properties"]["FunctionCode"]
    cases = {"/": "/index.html", "/portfolio/123": "/index.html",
             "/assets/missing.js": "/assets/missing.js", "/assets/missing": "/assets/missing",
             "/api": "/api", "/api/analysis/A001": "/api/analysis/A001",
             "/favicon.svg": "/favicon.svg"}
    runner = code + "\nconst cases = " + json.dumps(cases) + ";\n" + '''
for (const [uri, expected] of Object.entries(cases)) {
    if (handler({request: {uri}}).uri !== expected) throw Error(uri);
}
'''
    subprocess.run(["node", "-e", runner], check=True)
