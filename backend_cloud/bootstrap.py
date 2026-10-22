"""One-off PostgreSQL database/role setup. No business tables or data processing."""
import json
import os
import psycopg
from psycopg import sql

ROLE_DATABASES = {
    "public_reader": "spip_public", "public_writer": "spip_public",
    "public_migrator": "spip_public", "tenant_app": "spip_tenant",
    "tenant_migrator": "spip_tenant",
}


def connect(database, admin):
    return psycopg.connect(host=os.environ["SPIP_DB_HOST"], port=5432, dbname=database,
                           user=admin["username"], password=admin["password"],
                           sslmode="verify-full", sslrootcert=os.environ["PGSSLROOTCERT"], autocommit=True)


def bootstrap():
    admin = json.loads(os.environ["SPIP_ADMIN_CREDENTIALS"])
    credentials = {role: json.loads(os.environ[f"SPIP_{role.upper()}_CREDENTIALS"])
                   for role in ROLE_DATABASES}
    for role, database in ROLE_DATABASES.items():
        data = credentials[role]
        if data["username"] != f"spip_{role}" or data["dbname"] != database:
            raise ValueError("Bootstrap secret does not match its reserved role/database")
    with connect("postgres", admin) as conn:
        # Serialize bootstrap executions across jobs without creating an app table.
        conn.execute("SELECT pg_advisory_lock(5224, 1)")
        for role, data in credentials.items():
            name = sql.Identifier(data["username"])
            existing = conn.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
                (data["username"],),
            ).fetchone()
            if existing is None:
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(name))
            elif any(existing):
                raise ValueError("Reserved role has unexpected elevated privileges; refusing to take it over")
            conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(name, sql.Literal(data["password"])))
        # PostgreSQL requires membership to create schemas/default grants for
        # another owner; only the infrastructure administrator receives it.
        for role in ("public_migrator", "tenant_migrator"):
            conn.execute(sql.SQL("GRANT {} TO {} WITH SET TRUE, INHERIT TRUE")
                         .format(sql.Identifier(f"spip_{role}"), sql.Identifier(admin["username"])))
        for database in ("spip_public", "spip_tenant"):
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
            for role, expected in ROLE_DATABASES.items():
                # Revoke explicit wrong-database grants as well as PUBLIC defaults.
                conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}")
                             .format(sql.Identifier(database), sql.Identifier(f"spip_{role}")))
                if expected == database:
                    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}")
                                 .format(sql.Identifier(database), sql.Identifier(f"spip_{role}")))
        for database in ("spip_public", "spip_tenant"):
            is_public = database == "spip_public"
            migrator = "spip_public_migrator" if is_public else "spip_tenant_migrator"
            readers = ["spip_public_reader", "spip_public_writer"] if is_public else ["spip_tenant_app"]
            with connect(database, admin) as db:
                db.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
                db.execute(sql.SQL("GRANT CREATE ON DATABASE {} TO {}")
                           .format(sql.Identifier(database), sql.Identifier(migrator)))
                db.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION {}")
                           .format(sql.Identifier(migrator)))
                owner = db.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='app'").fetchone()[0]
                if owner != migrator:
                    raise ValueError("Existing app schema has an unexpected owner; refusing to take it over")
                for role in [migrator, *readers]:
                    db.execute(sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path = app, public")
                               .format(sql.Identifier(role), sql.Identifier(database)))
                    db.execute(sql.SQL("GRANT USAGE ON SCHEMA app TO {}").format(sql.Identifier(role)))
                for role in readers:
                    actions = sql.SQL("SELECT") if role == "spip_public_reader" else sql.SQL("SELECT, INSERT, UPDATE, DELETE")
                    db.execute(sql.SQL("GRANT {} ON ALL TABLES IN SCHEMA app TO {}")
                               .format(actions, sql.Identifier(role)))
                    db.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA app GRANT {} ON TABLES TO {}")
                               .format(sql.Identifier(migrator), actions, sql.Identifier(role)))
                    if role != "spip_public_reader":
                        db.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {}")
                                   .format(sql.Identifier(role)))
                        db.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO {}")
                                   .format(sql.Identifier(migrator), sql.Identifier(role)))
        conn.execute("SELECT pg_advisory_unlock(5224, 1)")
    print("Logical databases and restricted roles ready; business migrations and tenant RLS are still required.")


if __name__ == "__main__":
    bootstrap()
