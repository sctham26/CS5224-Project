"""The optional /api prefix switch must not disturb the default (no prefix)."""

import importlib

from fastapi.testclient import TestClient

import api
from auth import Authenticator


def _reload(monkeypatch, prefix):
    monkeypatch.setenv("SPIP_API_PREFIX", prefix)
    monkeypatch.setenv("SPIP_AUTH_ENABLED", "false")
    reloaded = importlib.reload(api)
    reloaded._authenticator = Authenticator(enabled=False, demo_tenant="tenant_a")
    return reloaded


def test_default_routes_have_no_prefix():
    assert api.PREFIX == ""
    client = TestClient(api.app)
    assert client.get("/health").status_code == 200


def test_prefix_switch_moves_business_routes_but_not_health(monkeypatch):
    reloaded = _reload(monkeypatch, "/api")
    try:
        client = TestClient(reloaded.app)
        assert client.get("/api/entities").status_code == 200
        assert client.get("/entities").status_code == 404
        # The ALB health check must keep working regardless of the gateway prefix.
        assert client.get("/health").status_code == 200
    finally:
        monkeypatch.delenv("SPIP_API_PREFIX", raising=False)
        monkeypatch.setenv("SPIP_AUTH_ENABLED", "false")
        restored = importlib.reload(api)
        restored._authenticator = Authenticator(enabled=False, demo_tenant="tenant_a")
