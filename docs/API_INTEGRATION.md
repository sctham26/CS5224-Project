# Cloud API integration and operator handoff

Prepared 2026-10-25. Only cloud configuration, packaging and operator scripts are changed here. Application source is exported unchanged from backend commit `27cc9fb7c6d0b0ae21057e5ba1a4bfb8b90cbe2e`. Frontend branch `a463bfb` is owned by the frontend team; the old frontend copy in this branch is not the source for this integration.

## Public and backend paths

| Browser URL at the existing CloudFront site | Gateway / FastAPI path | Authentication |
| --- | --- | --- |
| `GET /api/health` | `GET /health` | Public, minimal liveness only |
| `GET /api/entities` | `GET /entities` | Cognito access token + active tenant membership |
| `GET /api/analysis/{entity_id}` | `GET /analysis/{entity_id}` | Cognito access token + ownership |
| `POST /api/uploads` | `POST /uploads` | Cognito access token + active tenant membership |
| `POST /api/jobs` | `POST /jobs` | Cognito access token + ownership/idempotency |
| `GET /api/jobs/{job_id}` | `GET /jobs/{job_id}` | Cognito access token + ownership |

CloudFront selects the HTTPS API Gateway origin for `api/*` (and bare `api`), removes exactly the leading `/api`, disables caching and forwards query parameters and Authorization. API Gateway forwards the original bearer header through its VPC link/internal ALB integration. FastAPI uses an empty `SPIP_API_PREFIX`. The ALB probes unprefixed `/health`.

The public `/api` prefix is a browser routing convention; the backend does not need to add it. An unauthenticated liveness response proves reachability only, not database readiness or authorization.

The synchronous development `/analyze` endpoint is not exposed by the gateway. Application request bodies and response JSON are owned by the backend; use the pinned [backend interface](https://github.com/sctham26/CS5224-Project/blob/27cc9fb7c6d0b0ae21057e5ba1a4bfb8b90cbe2e/INTERFACES.md) and `src/api.py`/`src/jobs.py`. The previous cloud contract v0.1 was a proposal, not proof that the backend implemented its `upload_id`/operation envelope. The current backend uses `upload_key` and its own job request fields.

## Frontend team's required changes

1. Production requests must use `/api`; `localhost:8000` is local development only. Setting a Vite variable has no effect unless the frontend reads it.
2. Integrate the existing Cognito pool/client with authorization code + PKCE and send an **access token** in `Authorization: Bearer ...` on protected requests. See [auth contract](AUTH_CONTRACT.md).
3. Use the agreed backend request/result shapes; send `Idempotency-Key` on job submission. Use ordinary PUT to the returned presigned S3 URL without a Cognito Authorization header.
4. Handle `401` (invalid/missing credentials), `403` (no tenant membership) and `404` (missing/inaccessible resource).

No frontend JS is rewritten by this cloud change. Automatic publishing from `cloud-config` is disabled so infrastructure commits cannot redeploy its obsolete frontend copy. The existing main-branch publishing path remains; merge the team's actual frontend and complete its auth/API integration before using that path.

## Runtime settings

ECS explicitly sets `SPIP_AUTH_ENABLED=true`, `SPIP_AUTH_SCOPE=spip/access`, `SPIP_API_PREFIX=""`, issuer/audience and the two database credential injections. The latest backend reads `SPIP_JWT_ISSUER`/`SPIP_JWT_AUDIENCE`; `SPIP_AUTH_ISSUER`/`SPIP_AUTH_CLIENT_ID` aliases are also supplied for compatibility. These values match the existing Cognito user pool and public browser client.

The worker command is `python src/worker.py`. Its DB lease is 840 seconds, versus 900 seconds of SQS visibility, leaving time for lease expiry before redelivery. Processing duration/retry behavior still needs workload testing; these numbers do not guarantee arbitrary job duration. DLQ alarms are defined, but an alert destination and scheduled DLQ reconciliation remain operational follow-ups.

## Pinned images and deployment order

`backend_cloud/runtime.Dockerfile` packages the team's source, a hash-locked dependency set, the RDS CA and cloud entrypoints. No backend source is edited. The ECR tag includes the backend commit and cloud-support hash, and deployment uses the resulting immutable image digest. Record both when releasing.

`infra/backend.sandbox.json` selects **single-AZ** private RDS for this development deployment; the general template still defaults to Multi-AZ. It also starts one API and one worker task. RDS, ALB, Fargate, public IPv4, storage, KMS and Secrets Manager incur ongoing charges.

Run from the repository root with Python 3.12 through uv where needed. Verify the sandbox principal/account `825990809862` and region `ap-southeast-1` first.

1. Deploy `BackendDataStack` using the reviewed sandbox config and save `infra/backend-outputs.json`.
2. Build/push the backend snapshot using `scripts/build_backend_image.py --ref <commit> --repository <ECR URI>`; run it with `uv run --project backend_cloud --locked python`. The script saves public image provenance in ignored `infra/backend-image.json`. Put its digest URI into both image fields of the sandbox config.
3. Run `scripts/run_database_bootstrap.py infra/backend-outputs.json` with `AWS_PROFILE=sandbox`. This creates the two logical databases and restricted roles, not business tables.
4. Once real images are configured, synthesize the full assembly with `enable_backend=true`, `enable_backend_operations=true`, `enable_backend_runtime=true` and the same config. Deploy `BackendDataStack --exclusively` **from that full assembly** first: this adds the cross-stack outputs consumed by operations/runtime without starting services or replacing RDS. Then deploy `BackendOperationsStack --exclusively` from the same assembly and save `infra/operations-outputs.json`. Do not omit runtime/operations flags when later updating the foundation; otherwise referenced weak outputs can disappear.
5. Use `scripts/run_backend_task.py` with the Migration task ARN, container `Migration`, and JSON command `["migrate"]`. It applies public `001/004` and tenant `002/003` as their corresponding migration owners, in schema `app`; applied-file hashes prevent silently changing executed migrations.
6. Use the PublicImport task ARN and container `PublicImport` with `["import-baseline","--dry-run"]`, then `["import-baseline"]`. It runs the backend team's importer with only public-writer credentials. The source CSV contains 12,767 prepared observations.
7. Deploy `BackendRuntimeStack` and `InfraStack` with `enable_backend=true`, `enable_backend_runtime=true` and the same config. Never deploy the context-free frontend template after enabling API routing, because it would remove the behavior.
8. Verify the public CloudFront health endpoint, invalid/no-token rejection and then a real signed-in user with an explicitly provisioned membership.

All operator tasks use the existing cluster/public task subnets and bootstrap SG (outbound access only), while RDS is isolated. Migration, import and application execution roles are separate. Normal API/worker tasks do not receive master or migration credentials. The migration task grants app roles only the intended business-table permissions; `tenant_membership` is SELECT-only to the app role.

## Provisioning tenant membership

A Cognito invitation creates an identity, not a tenant assignment. An operator first verifies the invited user's actual `sub` through Cognito and agrees the tenant with the project owner. Then run the Migration task/container using the explicit command:

```json
["membership", "--sub", "<verified Cognito UUID>", "--tenant", "<approved tenant ID>"]
```

The supplied UUID/tenant are validated and SQL values are parameterized. The task uses the migration owner under the table's existing RLS context, not an application endpoint or a browser-selected tenant. Updating an existing membership changes its assignment; review the subject/tenant carefully before running it. No users or memberships are created automatically.

## Acceptance boundaries

Local tests cover API prefix removal, preserving Authorization/query/method, uncached routing, explicit auth settings, and real backend migrations/owner permissions in disposable PostgreSQL. The unchanged backend suite passes 105 tests in its Linux image. Actual cloud deployment/test evidence is recorded separately below once confirmed. Frontend changes, real-user token acceptance and end-to-end uploaded-data processing must not be inferred solely from health/401 tests.
