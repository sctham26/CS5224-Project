"""Build backend DSNs from ECS-injected secrets, then replace this process."""
import json
import os
import sys
from urllib.parse import quote, urlencode


def database_url(host, credentials, ca_file):
    data = json.loads(credentials)
    if data["dbname"] not in ("spip_public", "spip_tenant"):
        raise ValueError("Unexpected logical database")
    if not host or any(char in host for char in "/:@?#") or not ca_file:
        raise ValueError("A database host and CA file are required")
    return (
        f"postgresql://{quote(data['username'], safe='')}:{quote(data['password'], safe='')}"
        f"@{host}:5432/{data['dbname']}?" + urlencode({"sslmode": "verify-full", "sslrootcert": ca_file})
    )


def configure_environment(environment):
    host = environment["SPIP_DB_HOST"]
    ca_file = environment["PGSSLROOTCERT"]
    for label in ("PUBLIC", "TENANT"):
        secret = environment.pop(f"SPIP_{label}_DB_CREDENTIALS")
        environment[f"SPIP_{label}_DATABASE_URL"] = database_url(host, secret, ca_file)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Provide a backend command after the cloud entrypoint")
    configure_environment(os.environ)
    os.execvp(sys.argv[1], sys.argv[1:])
