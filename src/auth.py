"""Cognito access-token validation and trusted tenant resolution.

Per ``docs/AUTH_CONTRACT.md`` the API must not trust client-supplied identities:

1. the bearer token is verified against the pool's JWKS (issuer, expiry,
   ``token_use=access``, browser ``client_id`` and the ``spip/access`` scope);
2. the verified ``sub`` is resolved to one active tenant membership from
   server-controlled records — never from an email, header or request body.

Local development can disable verification explicitly (``SPIP_AUTH_ENABLED``),
which yields the ``PUBLIC`` tenant. Production must keep it enabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

PUBLIC_TENANT = "PUBLIC"


class AuthError(Exception):
    """Base class for authentication/authorisation failures."""


class InvalidToken(AuthError):
    """Token missing, malformed, expired or failing a required claim check."""


class NoMembership(AuthError):
    """Valid account, but no active tenant membership -> 403."""


@dataclass(frozen=True)
class Principal:
    """Verified caller identity used to scope every data read."""

    subject: str
    tenant_id: str
    scopes: tuple[str, ...] = ()


class MembershipStore(Protocol):
    """Server-controlled user -> tenant mapping."""

    def active_tenant(self, subject: str) -> Optional[str]: ...


class StaticMembershipStore:
    """In-memory mapping for tests and single-tenant deployments."""

    def __init__(self, memberships: dict[str, str]):
        self._memberships = dict(memberships)

    def active_tenant(self, subject: str) -> Optional[str]:
        return self._memberships.get(subject)


class DbMembershipStore:
    """Reads ``tenant_membership`` from the tenant database.

    The lookup is guarded by ``app.user_sub`` so a row-level-security policy can
    restrict the table to the current caller.
    """

    def __init__(self, tenant_url: str):
        self.tenant_url = tenant_url

    def active_tenant(self, subject: str) -> Optional[str]:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - configuration error
            raise RuntimeError("psycopg is required for database membership lookup") from exc

        with psycopg.connect(self.tenant_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.user_sub', %s, true)", (subject,))
                cur.execute(
                    "SELECT tenant_id FROM tenant_membership "
                    "WHERE user_sub = %s AND active ORDER BY tenant_id LIMIT 1",
                    (subject,),
                )
                row = cur.fetchone()
        return row[0] if row else None


class TokenValidator:
    """Verifies a Cognito access token and returns its claims."""

    def __init__(
        self,
        issuer: str,
        client_id: str,
        required_scope: str = "spip/access",
        jwks_url: Optional[str] = None,
        key_resolver=None,
    ):
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.required_scope = required_scope
        self.jwks_url = jwks_url or f"{self.issuer}/.well-known/jwks.json"
        self._key_resolver = key_resolver
        self._jwk_client = None

    def _signing_key(self, token: str):
        if self._key_resolver is not None:  # injected in tests
            return self._key_resolver(token)
        import jwt  # imported lazily so local runs do not require crypto deps

        if self._jwk_client is None:
            self._jwk_client = jwt.PyJWKClient(self.jwks_url)
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> dict:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - configuration error
            raise RuntimeError("PyJWT is required when SPIP_AUTH_ENABLED=true") from exc

        try:
            claims = jwt.decode(
                token,
                self._signing_key(token),
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False},  # access tokens carry client_id, not aud
                leeway=int(os.environ.get("SPIP_AUTH_LEEWAY_SECONDS", 30)),
            )
        except Exception as exc:  # jwt raises many subclasses; all mean "reject"
            raise InvalidToken(f"token rejected: {exc}") from None

        if claims.get("token_use") != "access":
            raise InvalidToken("token_use must be access")
        if claims.get("client_id") != self.client_id:
            raise InvalidToken("client_id does not match this application")
        scopes = tuple(str(claims.get("scope", "")).split())
        if self.required_scope not in scopes:
            raise InvalidToken(f"missing required scope {self.required_scope}")
        if not claims.get("sub"):
            raise InvalidToken("token has no subject")
        return claims


class Authenticator:
    """Turns an ``Authorization`` header into a :class:`Principal`."""

    def __init__(
        self,
        validator: Optional[TokenValidator] = None,
        memberships: Optional[MembershipStore] = None,
        enabled: bool = True,
        demo_tenant: str = PUBLIC_TENANT,
    ):
        self.validator = validator
        self.memberships = memberships
        self.enabled = enabled
        self.demo_tenant = demo_tenant

    def authenticate(self, authorization: Optional[str]) -> Principal:
        if not self.enabled:
            # Local mode: no Cognito, every caller is the shared public dataset
            # plus, if configured, one development tenant.
            return Principal(subject="local-dev", tenant_id=self.demo_tenant)

        if not authorization or not authorization.lower().startswith("bearer "):
            raise InvalidToken("missing bearer token")
        if self.validator is None or self.memberships is None:
            raise InvalidToken("authentication is not configured")

        claims = self.validator.verify(authorization.split(" ", 1)[1].strip())
        subject = str(claims["sub"])
        tenant = self.memberships.active_tenant(subject)
        if not tenant:
            raise NoMembership("no active tenant membership for this account")
        return Principal(
            subject=subject,
            tenant_id=tenant,
            scopes=tuple(str(claims.get("scope", "")).split()),
        )


def build_authenticator(environ: dict[str, str] | None = None) -> Authenticator:
    """Construct the authenticator from runtime configuration.

    ``SPIP_AUTH_ENABLED`` defaults to ``false`` so local development keeps
    working; the deployment sets it to ``true``.
    """
    env = os.environ if environ is None else environ
    enabled = env.get("SPIP_AUTH_ENABLED", "false").lower() == "true"
    if not enabled:
        return Authenticator(
            enabled=False,
            demo_tenant=env.get("SPIP_DEMO_TENANT", PUBLIC_TENANT),
        )

    issuer = env["SPIP_AUTH_ISSUER"]
    validator = TokenValidator(
        issuer=issuer,
        client_id=env["SPIP_AUTH_CLIENT_ID"],
        required_scope=env.get("SPIP_AUTH_SCOPE", "spip/access"),
    )
    tenant_url = env.get("SPIP_TENANT_DATABASE_URL")
    memberships: MembershipStore
    if tenant_url:
        memberships = DbMembershipStore(tenant_url)
    else:  # explicit env mapping for a single-tenant first deployment
        memberships = StaticMembershipStore(
            {env["SPIP_DEMO_USER_SUB"]: env.get("SPIP_DEMO_TENANT", PUBLIC_TENANT)}
            if env.get("SPIP_DEMO_USER_SUB")
            else {}
        )
    return Authenticator(validator=validator, memberships=memberships, enabled=True)
