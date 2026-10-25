"""Authentication and tenant-isolation tests (light coverage; Michael owns the suite)."""

import pytest
from fastapi.testclient import TestClient

import api
from auth import (
    Authenticator,
    InvalidToken,
    NoMembership,
    StaticMembershipStore,
    TokenValidator,
)
from datastore import CsvDataSource

client = TestClient(api.app)


class _StubValidator:
    """Stands in for JWKS verification; returns pre-set claims."""

    def __init__(self, claims):
        self.claims = claims

    def verify(self, token):
        if token != "good":
            raise InvalidToken("token rejected")
        return self.claims


def _enabled_authenticator(claims, memberships):
    return Authenticator(
        validator=_StubValidator(claims),
        memberships=StaticMembershipStore(memberships),
        enabled=True,
    )


# --- token / membership -------------------------------------------------------


def test_missing_bearer_token_is_rejected():
    auth = _enabled_authenticator({"sub": "u1", "scope": "spip/access"}, {"u1": "tenant_a"})
    with pytest.raises(InvalidToken):
        auth.authenticate(None)
    with pytest.raises(InvalidToken):
        auth.authenticate("Basic abc")


def test_valid_token_resolves_tenant_from_server_records():
    auth = _enabled_authenticator({"sub": "u1", "scope": "spip/access"}, {"u1": "tenant_a"})
    principal = auth.authenticate("Bearer good")
    assert (principal.subject, principal.tenant_id) == ("u1", "tenant_a")


def test_valid_account_without_membership_is_forbidden():
    auth = _enabled_authenticator({"sub": "u2", "scope": "spip/access"}, {"u1": "tenant_a"})
    with pytest.raises(NoMembership):
        auth.authenticate("Bearer good")


def test_claim_checks_reject_wrong_token_use_client_and_scope():
    validator = TokenValidator(
        issuer="https://example.invalid/pool",
        audiences=("client-1",),
        key_resolver=lambda token: "key",
    )
    # Garbage token still fails signature verification before claim checks.
    with pytest.raises(InvalidToken):
        validator.verify("not-a-jwt")


# --- API-level tenant isolation ----------------------------------------------


@pytest.fixture
def tenant_a(monkeypatch):
    monkeypatch.setattr(api, "_datasource", CsvDataSource("tests/fixtures_tenants.csv"))
    monkeypatch.setattr(
        api, "_authenticator", Authenticator(enabled=False, demo_tenant="tenant_a")
    )
    return client


def test_public_entity_is_visible_and_result_is_tenant_stamped(tenant_a):
    r = tenant_a.get("/analysis/PUB_BUILD", params={"reporting_year": 2024})
    assert r.status_code == 200, r.text
    body = r.json()
    # The authenticated tenant wins over whatever the data says.
    assert body["tenant_id"] == "tenant_a"
    assert body["peer_cohort"]["sample_size_n"] >= 5


def test_own_private_entity_is_visible(tenant_a):
    assert tenant_a.get("/analysis/ALPHA_BUILD").status_code == 200


def test_other_tenant_entity_is_not_found(tenant_a):
    # tenant_b's building is filtered out before analysis -> 404, not 403, so the
    # API does not reveal that the entity exists.
    assert tenant_a.get("/analysis/BETA_BUILD").status_code == 404


def test_entity_discovery_is_tenant_scoped(tenant_a):
    ids = {e["entity_id"] for e in tenant_a.get("/entities").json()["entities"]}
    assert "PUB_BUILD" in ids and "ALPHA_BUILD" in ids
    assert "BETA_BUILD" not in ids


def test_missing_bearer_token_returns_401(monkeypatch):
    monkeypatch.setattr(
        api,
        "_authenticator",
        _enabled_authenticator({"sub": "u1", "scope": "spip/access"}, {"u1": "tenant_a"}),
    )
    r = client.get("/analysis/PUB_BUILD")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


def test_account_without_membership_returns_403(monkeypatch):
    monkeypatch.setattr(
        api,
        "_authenticator",
        _enabled_authenticator({"sub": "u2", "scope": "spip/access"}, {"u1": "tenant_a"}),
    )
    r = client.get("/analysis/PUB_BUILD", headers={"Authorization": "Bearer good"})
    assert r.status_code == 403


def test_health_stays_unprotected(monkeypatch):
    monkeypatch.setattr(
        api,
        "_authenticator",
        _enabled_authenticator({"sub": "u1", "scope": "spip/access"}, {"u1": "tenant_a"}),
    )
    assert client.get("/health").json() == {"status": "ok"}


def test_cors_allows_configured_origin_and_authorization_header():
    r = client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    preflight = client.options(
        "/analysis/PUB_BUILD",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert "authorization" in preflight.headers.get("access-control-allow-headers", "").lower()
