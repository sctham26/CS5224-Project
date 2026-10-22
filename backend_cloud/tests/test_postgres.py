"""Test-only schemas exercise database grants and RLS; no business schema is defined."""
import json
import os
import sys
from pathlib import Path
import psycopg
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap as setup

pytestmark = pytest.mark.skipif(not os.environ.get("SPIP_TEST_POSTGRES_PASSWORD"), reason="Requires disposable TLS PostgreSQL (scripts/test_backend_postgres.sh)")


@pytest.fixture(scope="module")
def credentials():
    root_password = os.environ["SPIP_TEST_POSTGRES_PASSWORD"]
    args = dict(host="localhost", port=5432, sslmode="verify-full", sslrootcert=os.environ["PGSSLROOTCERT"])
    with psycopg.connect(**args, dbname="postgres", user="pg_admin", password=root_password, autocommit=True) as conn:
        # Exercise a CREATEDB/CREATEROLE administrator, rather than relying on a
        # PostgreSQL superuser to hide privilege mistakes in bootstrap SQL.
        conn.execute("CREATE ROLE spip_operator LOGIN CREATEDB CREATEROLE PASSWORD 'operator_test_only'")
    os.environ["SPIP_DB_HOST"] = "localhost"
    os.environ["SPIP_ADMIN_CREDENTIALS"] = json.dumps({"username":"spip_operator", "password":"operator_test_only"})
    passwords = {}
    for role, db in setup.ROLE_DATABASES.items():
        passwords[role] = f"test_only_{role}"
        os.environ[f"SPIP_{role.upper()}_CREDENTIALS"] = json.dumps({"username":f"spip_{role}","dbname":db,"password":passwords[role]})
    setup.bootstrap()
    setup.bootstrap()  # Re-running must not destroy databases or fail on roles.
    def connect(role, database):
        return psycopg.connect(**args, dbname=database, user=f"spip_{role}", password=passwords[role])
    return connect


def test_public_reader_cannot_write_or_connect_to_tenant_database(credentials):
    with credentials("public_migrator", "spip_public") as conn:
        conn.execute("CREATE TABLE app.public_probe (value text)")
        conn.execute("INSERT INTO app.public_probe VALUES ('baseline')")
    with credentials("public_reader", "spip_public") as conn:
        assert conn.execute("SELECT value FROM app.public_probe").fetchall() == [("baseline",)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO app.public_probe VALUES ('forbidden')")
    with pytest.raises(psycopg.Error, match="permission denied for database"):
        credentials("public_reader", "spip_tenant")
    with pytest.raises(psycopg.Error, match="permission denied for database"):
        credentials("tenant_app", "spip_public")


def test_non_owner_app_role_can_enforce_backend_rls_and_reset_context(credentials):
    with credentials("tenant_migrator", "spip_tenant") as conn:
        conn.execute("CREATE TABLE app.tenant_probe (tenant_id text, value text)")
        conn.execute("ALTER TABLE app.tenant_probe ENABLE ROW LEVEL SECURITY")
        conn.execute("CREATE POLICY tenant_only ON app.tenant_probe USING (tenant_id = current_setting('spip.tenant_id',true)) WITH CHECK (tenant_id = current_setting('spip.tenant_id',true))")
        conn.execute("INSERT INTO app.tenant_probe VALUES ('alpha','alpha private'), ('beta','beta private')")
    with credentials("tenant_app", "spip_tenant") as conn:
        conn.execute("SELECT set_config('spip.tenant_id','alpha',true)")
        assert conn.execute("SELECT value FROM app.tenant_probe").fetchall() == [("alpha private",)]
        conn.commit()
        assert conn.execute("SELECT value FROM app.tenant_probe").fetchall() == []
        conn.execute("SELECT set_config('spip.tenant_id','alpha',true)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO app.tenant_probe VALUES ('beta','forbidden')")
