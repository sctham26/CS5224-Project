"""Independent Cognito login; no backend/database deployment required."""
from urllib.parse import urlsplit
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, aws_cognito as cognito
from constructs import Construct


def validate_origin(origin):
    parsed = urlsplit(origin)
    local = parsed.hostname == "localhost" and parsed.scheme == "http"
    if (parsed.scheme != "https" and not local) or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Auth origins must be explicit HTTPS origins or http://localhost")
    return origin.rstrip("/")


class AuthStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, frontend_origin: str,
                 local_origin: str | None = None, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        origins = [validate_origin(frontend_origin)]
        if local_origin:
            origins.append(validate_origin(local_origin))
        self.pool = cognito.UserPool(
            self, "Users", user_pool_name="spip-users",
            self_sign_up_enabled=False, sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(email=cognito.StandardAttribute(required=True, mutable=True)),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            password_policy=cognito.PasswordPolicy(min_length=12, require_lowercase=True,
                require_uppercase=True, require_digits=True, require_symbols=True,
                temp_password_validity=Duration.days(3)),
            mfa=cognito.Mfa.OPTIONAL, mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            feature_plan=cognito.FeaturePlan.ESSENTIALS,
            deletion_protection=True, removal_policy=RemovalPolicy.RETAIN,
        )
        access = cognito.ResourceServerScope(scope_name="access", scope_description="Call SPIP authenticated API")
        resource = self.pool.add_resource_server("ApiScopes", identifier="spip", scopes=[access])
        self.client = self.pool.add_client(
            "Browser", generate_secret=False, prevent_user_existence_errors=True,
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            auth_flows=cognito.AuthFlow(user_srp=True),
            enable_token_revocation=True, refresh_token_rotation_grace_period=Duration.seconds(10),
            access_token_validity=Duration.minutes(15), id_token_validity=Duration.minutes(15),
            refresh_token_validity=Duration.days(1),
            read_attributes=cognito.ClientAttributes().with_standard_attributes(email=True, email_verified=True),
            write_attributes=cognito.ClientAttributes().with_standard_attributes(email=True),
            o_auth=cognito.OAuthSettings(flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL,
                        cognito.OAuthScope.resource_server(resource, access)],
                callback_urls=[o + "/auth/callback" for o in origins],
                logout_urls=[o + "/" for o in origins]),
        )
        domain = self.pool.add_domain("LoginDomain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"spip-{self.account}-{self.region}"),
            managed_login_version=cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN)
        cognito.CfnManagedLoginBranding(self, "LoginBranding", user_pool_id=self.pool.user_pool_id,
            client_id=self.client.user_pool_client_id, use_cognito_provided_values=True)
        self.issuer = f"https://cognito-idp.{self.region}.amazonaws.com/{self.pool.user_pool_id}"
        for name, value in {
            "UserPoolId": self.pool.user_pool_id, "ClientId": self.client.user_pool_client_id,
            "Issuer": self.issuer, "LoginDomain": domain.base_url(), "ApiScope": "spip/access",
            "CallbackUrl": origins[0] + "/auth/callback", "LogoutUrl": origins[0] + "/",
        }.items():
            CfnOutput(self, name, value=value)
