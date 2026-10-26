import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entrypoint import configure_environment, database_url


def test_dsn_escapes_credentials_and_verifies_tls():
    url = database_url("db.example", json.dumps({"username": "user@name", "password": "a:/?#@&", "dbname": "spip_tenant"}), "/opt/ca.pem")
    parsed = urlsplit(url)
    assert unquote(parsed.username) == "user@name"
    assert unquote(parsed.password) == "a:/?#@&"
    assert parse_qs(parsed.query) == {"sslmode": ["verify-full"], "sslrootcert": ["/opt/ca.pem"]}


def test_runtime_only_gets_two_application_dsns():
    env = {"SPIP_DB_HOST": "db.example", "PGSSLROOTCERT": "/opt/ca.pem"}
    for label, db in [("PUBLIC", "spip_public"), ("TENANT", "spip_tenant")]:
        env[f"SPIP_{label}_DB_CREDENTIALS"] = json.dumps({"username": label, "password": "secret", "dbname": db})
    configure_environment(env)
    assert "SPIP_PUBLIC_DATABASE_URL" in env and "SPIP_TENANT_DATABASE_URL" in env
    assert not any(name.endswith("DB_CREDENTIALS") for name in env)


def test_unsupported_database_is_rejected():
    with pytest.raises(ValueError):
        database_url("db.example", json.dumps({"username":"u", "password":"p", "dbname":"postgres"}), "/ca")
