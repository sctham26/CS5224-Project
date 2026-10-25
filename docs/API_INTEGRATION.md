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


## Confirmed sandbox deployment — 2026-10-25

- `BackendDataStack`, `BackendOperationsStack`, `BackendRuntimeStack` deployed; `InfraStack` updated and CloudFront reports `Deployed`. Cognito uses the existing pool/client without recreating accounts.
- Gateway endpoint: `https://d7n96omm4j.execute-api.ap-southeast-1.amazonaws.com`. Browser API base remains `https://d10rc41o4pb0h.cloudfront.net/api`.
- Image: `825990809862.dkr.ecr.ap-southeast-1.amazonaws.com/spip-backend@sha256:56bdc19a2258e2151bf65d414e279878d5c3a924f63a982c0ca4bde6b76892f2`; backend `27cc9fb`, cloud-support hash `3656d9c835efcd1784bc93a1900dd1f8b2791deafc28efb223a3567afc4e56b8`.
- Database bootstrap, migration task, baseline dry run and baseline import exited zero. Logs confirm all four migrations and 12,767 upserted observations. A separate task using the actual application credentials confirmed the public row count, no public INSERT privilege, no tenant BYPASSRLS/table ownership, forced RLS on both tenant business tables, and no membership UPDATE privilege.
- API and worker services each have desired=1, running=1, pending=0. The database is PostgreSQL 18.6, single-AZ and not publicly accessible.
- Direct gateway and CloudFront `GET /health` / `GET /api/health` returned `200 {"status":"ok"}`. Protected `/entities` and `/api/entities` returned 401 with no token and with a deliberately invalid token. Re-run `python3 scripts/verify_api.py` to verify the public transport/negative-auth checks.
- Automated validation: 21 infrastructure tests, 6 disposable PostgreSQL tests (including actual backend migrations), and 105 unchanged backend tests passed. [Backend CI](https://github.com/sctham26/CS5224-Project/actions/runs/40181924831) passed; frontend publishing was skipped on cloud-config as intended.
- Real-user access-token acceptance, membership provisioning for actual people, cross-tenant HTTP tests and upload-to-worker-result integration remain acceptance work. No production user or membership was created during deployment. No frontend JavaScript was changed or published.
