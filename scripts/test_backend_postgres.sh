#!/usr/bin/env bash
# Disposable local/CI database only. Requires Docker, OpenSSL and uv.
set -euo pipefail
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
test_dir=$(mktemp -d)
container="spip-postgres-test-$$"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$test_dir"
}
trap cleanup EXIT
chmod 755 "$test_dir"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost' -keyout "$test_dir/server.key" \
  -out "$test_dir/server.crt" >/dev/null 2>&1
chmod 644 "$test_dir/server.crt"
export SPIP_TEST_POSTGRES_PASSWORD
SPIP_TEST_POSTGRES_PASSWORD=$(openssl rand -hex 24)
docker run -d --name "$container" -e POSTGRES_USER=test_admin \
  -e POSTGRES_PASSWORD="$SPIP_TEST_POSTGRES_PASSWORD" -p 127.0.0.1:5432:5432 \
  --mount "type=bind,src=$test_dir,dst=/tls,readonly" --entrypoint sh postgres:18-alpine -c \
  'cp /tls/server.key /tmp/server.key && chown postgres:postgres /tmp/server.key && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tls/server.crt -c ssl_key_file=/tmp/server.key' >/dev/null
ready=false
for attempt in {1..30}; do
  if docker exec "$container" pg_isready -h 127.0.0.1 -U test_admin >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != true ]; then
  docker logs "$container"
  exit 1
fi
export PGSSLROOTCERT="$test_dir/server.crt"
uv run --locked --project "$repo_dir/backend_cloud" pytest -q "$repo_dir/backend_cloud/tests"
