"""Operator-only migration/import/membership entrypoint; never an HTTP endpoint."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import psycopg
from entrypoint import database_url


def apply_migrations(public_url, tenant_url, directory):
    directory = Path(directory)
    for url, filenames in [
        (public_url, ["001_public.sql", "004_observation_upsert_key.sql"]),
        (tenant_url, ["002_tenant.sql", "003_jobs.sql", "004_observation_upsert_key.sql"]),
    ]:
        with psycopg.connect(url) as conn:
            conn.execute("SET LOCAL search_path TO app, public")
            conn.execute("SELECT pg_advisory_xact_lock(5224, 2)")
            conn.execute("CREATE TABLE IF NOT EXISTS app._cloud_migrations (name text PRIMARY KEY, sha256 text NOT NULL)")
            for filename in filenames:
                source = (directory / filename).read_bytes()
                digest = hashlib.sha256(source).hexdigest()
                previous = conn.execute("SELECT sha256 FROM app._cloud_migrations WHERE name=%s", (filename,)).fetchone()
                if previous:
                    if previous[0] != digest:
                        raise ValueError("Applied migration changed: " + filename)
                    continue
                conn.execute(source.decode())
                conn.execute("INSERT INTO app._cloud_migrations VALUES (%s,%s)", (filename, digest))
                print("Applied", filename, flush=True)
            if filenames[0] == "002_tenant.sql":
                conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA app FROM spip_tenant_app")
                conn.execute("GRANT SELECT, INSERT, UPDATE ON app.observation, app.ingestion_job TO spip_tenant_app")
                conn.execute("GRANT SELECT ON app.tenant_membership TO spip_tenant_app")
            else:
                conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA app FROM spip_public_reader, spip_public_writer")
                conn.execute("GRANT SELECT ON app.observation TO spip_public_reader")
                conn.execute("GRANT SELECT, INSERT, UPDATE ON app.observation TO spip_public_writer")
    print("Migrations and application grants ready.", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["migrate", "import-baseline", "membership"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sub")
    parser.add_argument("--tenant")
    args = parser.parse_args()
    for label in ("PUBLIC", "TENANT"):
        key = f"SPIP_{label}_DB_CREDENTIALS"
        if key in os.environ:
            os.environ[f"SPIP_{label}_DATABASE_URL"] = database_url(
                os.environ["SPIP_DB_HOST"], os.environ.pop(key), os.environ["PGSSLROOTCERT"])
    if args.operation == "migrate":
        apply_migrations(os.environ["SPIP_PUBLIC_DATABASE_URL"], os.environ["SPIP_TENANT_DATABASE_URL"], "migrations")
    elif args.operation == "import-baseline":
        command = [sys.executable, "src/import_baseline.py", "--data", "data/cleaned/public_esg_baseline.csv"]
        if args.dry_run:
            command.append("--dry-run")
        subprocess.run(command, check=True)
    else:
        uuid.UUID(args.sub or "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.tenant or ""):
            raise ValueError("Provide an explicit reviewed tenant ID")
        with psycopg.connect(os.environ["SPIP_TENANT_DATABASE_URL"]) as conn:
            conn.execute("SELECT set_config('app.user_sub',%s,true)", (args.sub,))
            conn.execute("INSERT INTO app.tenant_membership(user_sub,tenant_id,active) VALUES (%s,%s,true) "
                         "ON CONFLICT(user_sub) DO UPDATE SET tenant_id=excluded.tenant_id,active=true",
                         (args.sub, args.tenant))
        print("Membership assigned to the explicitly selected subject and tenant.", flush=True)


if __name__ == "__main__":
    main()
