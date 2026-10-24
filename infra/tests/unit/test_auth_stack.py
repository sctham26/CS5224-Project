import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from infra.auth_stack import AuthStack, validate_origin


def test_browser_login_is_invite_only_code_flow_without_client_secret():
    app = cdk.App()
    stack = AuthStack(app, "AuthStack",
        env=cdk.Environment(account="825990809862", region="ap-southeast-1"),
        frontend_origin="https://example.cloudfront.net", local_origin="http://localhost:5173")
    t = Template.from_stack(stack)
    t.has_resource_properties("AWS::Cognito::UserPool", {
        "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
        "DeletionProtection": "ACTIVE", "UserPoolTier": "ESSENTIALS",
        "UsernameAttributes": ["email"],
    })
    t.has_resource_properties("AWS::Cognito::UserPoolClient", {
        "GenerateSecret": False, "AllowedOAuthFlows": ["code"],
        "CallbackURLs": ["https://example.cloudfront.net/auth/callback", "http://localhost:5173/auth/callback"],
        "LogoutURLs": ["https://example.cloudfront.net/", "http://localhost:5173/"],
        "EnableTokenRevocation": True, "AccessTokenValidity": 15,
        "RefreshTokenRotation": {"Feature": "ENABLED", "RetryGracePeriodSeconds": 10},
        "WriteAttributes": ["email"],
    })
    client = next(iter(t.find_resources("AWS::Cognito::UserPoolClient").values()))["Properties"]
    resource_id = next(iter(t.find_resources("AWS::Cognito::UserPoolResourceServer")))
    assert client["AllowedOAuthScopes"] == ["openid", "email",
        {"Fn::Join": ["", [{"Ref": resource_id}, "/access"]]}]
    t.has_resource_properties("AWS::Cognito::UserPoolResourceServer", {
        "Identifier": "spip", "Scopes": [{"ScopeName": "access", "ScopeDescription": "Call SPIP authenticated API"}]})
    assert "ALLOW_REFRESH_TOKEN_AUTH" not in client["ExplicitAuthFlows"]
    t.has_resource_properties("AWS::Cognito::UserPoolDomain", {"ManagedLoginVersion": 2})
    t.has_resource_properties("AWS::Cognito::ManagedLoginBranding", {"UseCognitoProvidedValues": True})
    # No database, IAM app roles or backend task can be started by login provisioning.
    t.resource_count_is("AWS::RDS::DBInstance", 0)
    t.resource_count_is("AWS::ECS::Service", 0)


@pytest.mark.parametrize("origin", ["http://evil.example", "https://app.example/path", "https://app.example?x=1", "https://user@app.example"])
def test_auth_redirect_origins_are_explicit(origin):
    with pytest.raises(ValueError):
        validate_origin(origin)
