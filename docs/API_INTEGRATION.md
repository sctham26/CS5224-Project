# Cloud API integration and operator handoff

Prepared 2026-10-25. Only cloud configuration, packaging and operator scripts are changed here. Application source is exported unchanged from backend commit `e8a9f65d377bf6d5b1ac59f5c58afbfdc63d6971`. Frontend branch `a463bfb` is owned by the frontend team; the old frontend copy in this branch is not the source for this integration.

**Automatic release update (2026-10-26):** [Backend GitHub releases](BACKEND_RELEASE.md) supersedes manual image pinning below for routine application releases. The backend branch now has an explicitly authorized workflow entrypoint; reusable deployment code stays in the cloud branch. Live CloudFormation image parameters and Actions artifacts identify the current application release; the commit/digests below are dated operator-run snapshots. Infrastructure-only CDK updates retain previous image parameters; manual image changes must explicitly set both digest parameters.

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

The synchronous development `/analyze` endpoint is not exposed by the gateway. Application request bodies and response JSON are owned by the backend; use the pinned [backend interface](https://github.com/sctham26/CS5224-Project/blob/e8a9f65d377bf6d5b1ac59f5c58afbfdc63d6971/INTERFACES.md) and `src/api.py`/`src/jobs.py`. The previous cloud contract v0.1 was a proposal, not proof that the backend implemented its `upload_id`/operation envelope. The current backend uses `upload_key` and its own job request fields.

**2026-11-01 frontend status:** integration `66dd626` now combines authenticated API requests, the real presigned upload/job flow, insufficient-peer rendering and error handling. Its [CI run](https://github.com/sctham26/CS5224-Project/actions/runs/41273174001) passed frontend lint/tests/build and infrastructure checks, with deployment skipped. [Frontend release instructions](FRONTEND_DEPLOYMENT.md) explains check-only runs and explicit integration publication. The UI still needs an intentional site release and browser-based AWS login/upload/result acceptance; CI success does not establish that live journey. The older checklist below describes the required final behavior.

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

### Provisioned team memberships — 2026-10-25

Alex invited the four Cognito accounts and approved the following assignments. Cloud operations verified their immutable Cognito subjects and explicitly provisioned active memberships:

| Account | Cognito group | Tenant ID |
| --- | --- | --- |
| Alex Jin | `spip-admin` | `spip-team` |
| Auxane Baptiste | `spip-admin` | `spip-team` |
| Song Sifan | `spip-backend` | `spip-songsifan` |
| Tham Sin Che | `spip-customer` | `spip-tham` |

Alex and Auxane share a tenant and therefore its tenant-scoped data. Song Sifan and Tham have separate tenants for integration/isolation testing. Do not derive assignments from email addresses or accept tenant overrides from the browser. Membership changes update access; they do not move previously stored tenant data.

**Role enforcement boundary:** Cognito groups were created and assigned through operator actions, outside the current CDK definitions. They record the intended application roles; they do not grant AWS IAM/console, database-owner or migration permissions. The deployed backend currently resolves only subject → active tenant and does not enforce `cognito:groups` as administrator/backend/customer capabilities. In particular, `spip-admin` does not bypass tenant isolation. The backend team must define and enforce any additional role-based actions; frontend visibility alone is insufficient. Obtain a fresh token after group changes.

All four membership tasks exited zero. A separate task using the actual application DB credentials and backend `DbMembershipStore.active_tenant` verified every mapping. It also verified that each subject can SELECT only its own active membership through RLS, and an unset subject sees none. This verifies membership resolution/self-isolation, not cross-tenant business API or upload E2E behavior. No passwords or access tokens are recorded here.

## Acceptance boundaries

Local tests cover API prefix removal, preserving Authorization/query/method, uncached routing, explicit auth settings, and real backend migrations/owner permissions in disposable PostgreSQL. The unchanged backend suite passes 107 tests in its Linux image, including the SigV4 presigning and insufficient-peer result regressions. Actual cloud deployment/test evidence is recorded separately below once confirmed. Frontend changes, real-user token acceptance and end-to-end uploaded-data processing must not be inferred solely from health/401 tests.


## Confirmed sandbox deployment — 2026-10-25

- `BackendDataStack`, `BackendOperationsStack`, `BackendRuntimeStack` deployed; `InfraStack` updated and CloudFront reports `Deployed`. Cognito uses the existing pool/client without recreating accounts.
- Gateway endpoint: `https://d7n96omm4j.execute-api.ap-southeast-1.amazonaws.com`. Browser API base remains `https://d10rc41o4pb0h.cloudfront.net/api`.
- Image: `825990809862.dkr.ecr.ap-southeast-1.amazonaws.com/spip-backend@sha256:56bdc19a2258e2151bf65d414e279878d5c3a924f63a982c0ca4bde6b76892f2`; backend `27cc9fb`, cloud-support hash `3656d9c835efcd1784bc93a1900dd1f8b2791deafc28efb223a3567afc4e56b8`.
- Database bootstrap, migration task, baseline dry run and baseline import exited zero. Logs confirm all four migrations and 12,767 upserted observations. A separate task using the actual application credentials confirmed the public row count, no public INSERT privilege, no tenant BYPASSRLS/table ownership, forced RLS on both tenant business tables, and no membership UPDATE privilege.
- API and worker services each have desired=1, running=1, pending=0. The database is PostgreSQL 18.6, single-AZ and not publicly accessible.
- Direct gateway and CloudFront `GET /health` / `GET /api/health` returned `200 {"status":"ok"}`. Protected `/entities` and `/api/entities` returned 401 with no token and with a deliberately invalid token. Re-run `python3 scripts/verify_api.py` to verify the public transport/negative-auth checks.
- Automated validation: 21 infrastructure tests, 6 disposable PostgreSQL tests (including actual backend migrations), and 105 unchanged backend tests passed. [Backend CI](https://github.com/sctham26/CS5224-Project/actions/runs/40181924831) passed; frontend publishing was skipped on cloud-config as intended.
- The four approved sandbox memberships and Cognito group assignments above were provisioned after infrastructure deployment and verified through the backend membership resolver/application credentials. Cognito invitations were sent by Alex. Real-user access-token acceptance, role-based backend enforcement, cross-tenant HTTP tests and upload-to-worker-result integration remain acceptance work. No frontend JavaScript was changed or published.

## Backend image refresh — SigV4 upload fix (2026-10-25)

The backend team supplied commit `60f12ae44571cbf714510c7ea9d7fecdde83b09b` on `backend-analysis`. Its `S3Uploader` now explicitly selects Signature V4 and virtual-hosted addressing; the previous default could produce SigV2 presigned PUT URLs, which S3 rejects for our KMS-encrypted tenant bucket. The change adds a regression test and a backend-owned PowerShell E2E script. No application source was edited in `cloud-config`.

- Release image: `825990809862.dkr.ecr.ap-southeast-1.amazonaws.com/spip-backend@sha256:b901b235279230cf21e90d670a12d67fd7d817255909fd9173dc33543e8335f6`; cloud-support hash remains `3656d9c835efcd1784bc93a1900dd1f8b2791deafc28efb223a3567afc4e56b8`.
- `infra/backend.sandbox.json` pins this digest for API/worker. Operator task definitions use the same image. Backend CI now checks migrations from the same backend source commit.
- All 106 backend tests passed inside the rebuilt Linux image (test code and fixture data mounted read-only); all 21 infrastructure tests passed. The CDK change set showed only image/task-definition updates and service task references. No SQL migration or baseline reimport is needed for this source change, and no membership update is part of this release.
- Rollback: restore the previous API/worker digest recorded in the initial deployment section, review the CDK diff with full runtime/operations context, and redeploy the affected stacks. Do not re-bootstrap the database to roll back an image.
- Live verification: a one-off task running API task definition revision 2 exited zero after asserting regional SigV4 (`AWS4-HMAC-SHA256`) presigned PUT generation using actual ECS task credentials. The signed URL/credentials were not logged, and no object was uploaded. CloudFront health=200 and missing/invalid-token rejection=401 also passed. This does not claim user-token upload/job E2E completion.

## Backend image refresh — insufficient-peer contract fix (2026-10-26)

Backend commit `e8a9f65d377bf6d5b1ac59f5c58afbfdc63d6971` changes the analysis contract for a disclosed/comparable metric whose peer cohort remains too small after fallback: `benchmark`, `gap_type` and `is_flagged` are all `null`. This means "not benchmarked", rather than the previous misleading `gap_type: "NONE"` / `is_flagged: false`. The backend team added a regression test; frontend owners should render this state as insufficient peer data. No application source was edited in `cloud-config`.

- Release image: `825990809862.dkr.ecr.ap-southeast-1.amazonaws.com/spip-backend@sha256:817e9a4eb9f48cd93d07bcee2601cd19acb4d384eca17833e632d5d339cf1e08`; cloud-support hash remains `3656d9c835efcd1784bc93a1900dd1f8b2791deafc28efb223a3567afc4e56b8`. API, worker and operator task definitions use this immutable image; CI's backend-source pin is the same commit.
- All 107 backend tests passed inside the rebuilt Linux image with tests/fixtures mounted read-only. No SQL, dependency, route, authentication or membership changes are required by this backend source update.
- The backend team's pinned README reports successful upload → S3 PUT → queued job → worker result, plus rejection of another tenant's upload key. These are teammate-reported results from the previous release, not a fresh cloud-module E2E run. Private entity isolation and group-based permissions remain separate acceptance items.
- To roll back this release, restore image `825990809862.dkr.ecr.ap-southeast-1.amazonaws.com/spip-backend@sha256:b901b235279230cf21e90d670a12d67fd7d817255909fd9173dc33543e8335f6` in the sandbox config, review the full-context CDK diff and deploy runtime/operations. No database bootstrap or baseline import is needed.
