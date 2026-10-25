# Cloud module handoff and branch integration

Prepared 2026-10-23 for the SPIP team. Source branch: `cloud-config`; PR target: `main`. This document covers the whole cloud branch, including the frontend snapshot already imported into it.

**2026-10-25 update:** [Login module and auth contract](AUTH_CONTRACT.md) supersedes the authentication status below: Cognito is deployed and frontend login/logout/token integration is implemented. Tenant membership and backend authorization remain pending. The cloud frontend now also includes the CSV demo components from frontend branch `f0fe860`. The original branch table below is a dated snapshot. Backend SQL/image CI passed after the test-admin rename in `478fe17`.

**Current API update:** the [API integration guide](API_INTEGRATION.md) supersedes older backend deployment status and routing/migration placeholders in this dated handoff.

## 1. What is delivered

| Component | Implemented | Verification / deployment |
| --- | --- | --- |
| Frontend hosting | Python CDK: private versioned S3, CloudFront OAC/HTTPS/SPA routing | Deployed in account `825990809862`, `ap-southeast-1`; website below |
| Frontend CI/CD | GitHub Actions lint/build/checks, scoped GitHub OIDC role, upload/invalidation/release verification | Successful release of `7a814f2`: [Actions evidence](https://github.com/sctham26/CS5224-Project/actions/runs/39814724648) |
| Data foundation | Private PostgreSQL, public/tenant S3 buckets, SQS/DLQ, network boundaries, secrets and logs | CDK templates implemented; **not deployed** |
| Database bootstrap | Two logical DBs, separate restricted app/import/migration roles, schema namespace and grants | Utility implemented; must be run explicitly after foundation deployment; no business tables |
| API/worker hosting | Opt-in Fargate services, internal ALB, HTTP API JWT routes, optional CloudFront API routing | Templates implemented; **not deployed**; requires real application images and identity configuration |
| Application/cloud bridge | Secret-to-DSN entrypoint, runtime environment and proposed upload/job contract | Available for backend adoption; does not implement storage access or business processing |
| Authentication and tenant isolation | JWT configuration hooks, restricted DB roles and private network | Cognito/login, membership resolution, business RLS and end-to-end isolation still required |

Development website: [SPIP frontend](https://d10rc41o4pb0h.cloudfront.net). Rendering and static delivery work; analytics/upload/login are not a completed cloud user journey.

The two PostgreSQL databases are `spip_public` and `spip_tenant` **inside one RDS instance**. “Public” means shared application data, not anonymous network access. Tenant A/B isolation still needs backend ownership checks and row policies inside the tenant database.

Original S3 uploads remain versioned source files after processing. PostgreSQL stores whichever structured records the backend chooses. Cloud configuration neither assumes an ESG file schema nor automatically converts/deletes originals.

## 2. Where to look

| Path | Responsibility |
| --- | --- |
| `infra/infra/infra_stack.py` | Existing frontend resources and publishing role |
| `infra/infra/backend_data_stack.py` | Network, storage, queue, RDS, credentials and bootstrap task definition |
| `infra/infra/backend_runtime_stack.py` | API/worker services and API Gateway routes |
| `infra/app.py`, `infra/infra/backend_config.py` | Explicit enable flags and configuration validation |
| `backend_cloud/` | One-off DB bootstrap, container entrypoint and tests; not the analytics backend |
| `frontend/src/api.js` | Shared build-time API base URL |
| `.github/workflows/frontend.yml` | Frontend checks and deployment |
| `.github/workflows/backend.yml` | Backend infrastructure checks only; no AWS deployment |
| `scripts/` | Frontend publishing/verification, bootstrap launcher and disposable PostgreSQL tests |

Use the [backend interface contract](BACKEND_CLOUD_CONTRACT.md) for request/message examples, [backend deployment guide](BACKEND_DEPLOYMENT.md) for deployment commands and image requirements, and [frontend deployment guide](FRONTEND_DEPLOYMENT.md) for resource IDs, repository variables and recovery.

## 3. Branches and merge procedure

Fresh remote fetch for this handoff found:

| Branch / PR | Snapshot | Integration notes |
| --- | --- | --- |
| `cloud-config` | Backend configuration through `2e41f41`, plus this handoff and CI correction | Includes frontend source, infrastructure, workflows and docs; does not contain backend `src/` or data preparation implementation |
| `feature/frontend-dashboard` | `a0975a9` | This frontend snapshot is already copied into `cloud-config`, with API-base and lint adjustments; Git does not record that copy as a branch merge |
| `backend-analysis` | `721d3ab` | Existing local-file FastAPI and analysis engine; cloud upload/job/DB integrations still to implement |
| Data [PR #1](https://github.com/sctham26/CS5224-Project/pull/1), fork branch `set-up` | `22c8d70` | Preparation script, public baseline, synthetic private samples and data handoff; review and merge through that PR |
| `integration` | `55fcb29` | Already merges the frontend and backend snapshots; contains no cloud integration by that fact alone |
| `main` | `b2b38e9` | Final shared delivery target |

Recommended integration:

1. Review and merge the cloud PR into `main`. This enables the checked frontend release workflow on `main`; it does not deploy the backend templates.
2. Update `integration` from `main`, resolving the duplicate frontend addition carefully. Its existing history already contains the frontend/backend branches; do not re-copy their directories or merge them with unrelated-history overrides.
3. Bring data PR #1 into the agreed shared branch through review. If it lands on `main`, merge updated `main` into `integration`; otherwise have the PR retargeted to `integration` with the maintainer. Keep the data team's preparation and schema documentation authoritative for data semantics.
4. Implement backend, frontend and auth changes in their feature branches, bringing in current `main` first. Open PRs into `integration` for a joint synthetic-data test. The current cloud workflows target `main`/`cloud-config`; add `integration` to check-only triggers if the team adopts it as a permanent review target. It currently has no publishing permission.
5. Open the tested `integration` → `main` PR. Re-run tests against the actual merged tree. That merge publishes the frontend when its relevant paths change; backend provisioning remains a separate reviewed operator action.

For step 2, from a clean checkout of `integration` (use its existing worktree if Git reports that it is already checked out):

```bash
git fetch ccproj
git switch integration
git merge ccproj/main
# Resolve conflicts, then git add the resolved files and git commit.
# Run the checks below before pushing integration.
```

Run this only after the cloud PR has landed. Do not discard uncommitted work to switch branches. A merge conflict should be resolved by combining intent, not by choosing all files from one side:

- `README.md` and shared docs: retain the delivery status, module boundaries and links while preserving backend/data setup instructions.
- `frontend/src/App.jsx` and `PropertyComparison.jsx`: retain frontend feature work and the shared `API_BASE_URL` import. Preserve cloud lint fixes unless the incoming feature replaces the affected code.
- `frontend/src/api.js`: keep a single API configuration point; remove hard-coded cloud URLs/localhost URLs from production call sites.
- `infra/`, `backend_cloud/`, cloud workflows and publishing scripts: preserve the cloud module; backend feature work belongs in the application's source/image, not inside bootstrap.
- Data/configuration files: resolve overlapping metric definitions with the backend/data owners. Do not silently change measurement units to make a merge pass.

## 4. How each module connects

### Backend / analytics team

Keep `analyse_to_contract(...)` and its successful analysis result shape. Add storage/DB adapters and API/worker orchestration around it:

- Implement `POST /uploads`, `POST /jobs`, `GET /jobs/{job_id}` and authorised `GET /analysis/{entity_id}`. See the [contract](BACKEND_CLOUD_CONTRACT.md) for full envelopes/status/error rules.
- Resolve trusted tenant membership from the access token. Never accept a browser-selected tenant, bucket/key or database as authority.
- API reserves an upload and returns a short-lived S3 PUT URL. Browser uploads directly; explicit job submission pins the uploaded object version and durably records dispatch. There is no automatic S3-created job trigger.
- Implement durable job state/outbox, an SQS consumer, job idempotency/leases, retry heartbeat and DLQ reconciliation. Replace the existing shared `data/_upload.csv` with per-job working storage.
- Consume `SPIP_PUBLIC_DATABASE_URL`, `SPIP_TENANT_DATABASE_URL`, `SPIP_PUBLIC_DATA_BUCKET`, `SPIP_TENANT_DATA_BUCKET` and `SPIP_JOB_QUEUE_URL`. AWS access comes from the task role. Keep `SPIP_DATA`/`SPIP_METRICS`/`SPIP_RULES` for local compatibility.
- Add public/tenant migrations under the corresponding migration role, and tenant RLS with transaction-scoped trusted context. App connections use non-owner restricted roles. Agree a one-off VPC migration task with the cloud team.
- Publish real API/worker ECR images by immutable digest. Include `/opt/spip-cloud/entrypoint.py` and `/opt/spip-cloud/rds-ca.pem`; provide the real worker command. The default API command expects `api:app` in `src/` on port 8000 and an internal `/health` probe.

The old synchronous `POST /analyze` is local compatibility only; it is not a reserved cloud route. Current backend code must not be treated as private-data ready just because it starts in a container.

### Data team

Own source provenance, preparation/validation, metric definitions and public baseline releases. The cloud module provides a private public-data bucket and separate DB writer role for a dedicated importer; normal tenant API/worker roles cannot write the public database.

Keep source snapshots with release/version metadata. Agree business tables and importer behavior with the backend team. Private sample tenant labels demonstrate a fixture, not access control. The current 20-column output is not an infrastructure-imposed upload format.

Known compatibility issue to resolve jointly: `GREEN_CERT_LEVEL` uses `ORDINAL_0_4` in the data contract while the existing backend metric registry accepts `rating`; verify the canonical unit and conversion rather than masking the mismatch.

### Frontend / authentication team

Use the shared `API_BASE_URL`: local development defaults to `http://localhost:8000`; production defaults to `/api`. `VITE_API_BASE_URL` is a public build-time override; changing it requires a rebuild. Never put secrets in Vite variables.

Implement login/token handling, send `Authorization: Bearer <access-token>`, follow reserve → direct PUT → submit job → poll result, and send `Idempotency-Key` on job submission. Send the exact headers returned with a signed upload URL. CloudFront strips the leading `/api` once runtime is explicitly enabled.

The identity owner must supply the actual issuer, audience, scopes and membership rules; the cloud team supplies matching gateway config and approved browser origins. Cognito itself is not created by the current templates.

## 5. Release and deployment boundaries

- Relevant pushes to `cloud-config` or `main` build and publish to **one shared development website**. PRs run checks only. A push to another feature branch does not automatically import or deploy it.
- Publishing uses temporary GitHub OIDC credentials with a frontend-only role; no permanent AWS keys. Repository variables are `FRONTEND_BUCKET_NAME`, `CLOUDFRONT_DISTRIBUTION_ID`, `FRONTEND_URL` and `FRONTEND_DEPLOY_ROLE_ARN`.
- Backend CI has no AWS credentials/deploy step. SDK region is pinned to Singapore and synthesis uses committed lookup context with `--no-lookups`; missing context must fail rather than prompt for credentials.
- The default CDK app includes only `InfraStack`. See the [operator sequence](BACKEND_DEPLOYMENT.md#deployment-sequence-operator-run-not-automatic): deploy foundation → run bootstrap → backend migrations/isolation tests → provide real images/JWT → deploy runtime and frontend API routing.
- The second logical DB exists only after successful bootstrap. Starting services before tenant migrations is not an isolation test.
- After enabling the API route, future `InfraStack` deployments must use the same reviewed backend/runtime context. A context-free infrastructure deployment would remove that route. Frontend file publishing does not run CDK.
- Backend deployment incurs RDS (Multi-AZ by default), ALB, two continuously running Fargate services and related storage/network/security charges. Review cost before deployment. Retained buckets/keys/secrets and DB snapshots mean stack deletion is not a full cleanup.

## 6. Verification and remaining acceptance

Local checks available from the repository root:

```bash
(cd infra && uv sync --locked && uv run --locked pytest -q)
python3 -m unittest discover -s tests -v
uv run --locked --project backend_cloud pytest -q backend_cloud/tests
(cd frontend && npm ci && npm run lint && npm run build)
# Requires a running Docker daemon; uses disposable synthetic data only:
bash scripts/test_backend_postgres.sh
```

The earlier local run passed 13 infrastructure tests, 8 frontend publishing tests and 3 entrypoint tests; 2 PostgreSQL tests were skipped without Docker. Default/data/full synthesis passed locally, but an earlier CI run exposed a region-dependent lookup: setting only `CDK_DEFAULT_REGION` did not pin the CLI's AWS SDK region. This handoff update pins both AWS region variables and makes backend CI synthesis explicitly offline. The previous failed [run](https://github.com/sctham26/CS5224-Project/actions/runs/39815553436) is not a passing database/image test. Inspect the latest PR checks before merge; the local Docker daemon was unavailable, so image build and SQL integration require CI evidence.

Before declaring the combined system complete, verify on the merged source and deployed backend:

1. Login and token validation, including invalid/expired token rejection.
2. Upload → durable job → worker → persistent result → dashboard using synthetic data.
3. Retry/duplicate delivery safety, invalid file errors and DLQ reconciliation.
4. Tenant A cannot read/change tenant B's IDs, objects, results or DB rows; repeat using pooled connections and forged tenant fields.
5. Public data remains read-only to normal app roles; sources survive processing; secrets stay out of client bundles/logs.
6. Repeated deployment preserves resources/data, frontend release metadata matches the intended commit, and a recovery/retention owner is assigned.

Open operational work also includes DLQ alert notification routing, application-role credential rotation and a reviewed migration/public-import task. These remain separate from the delivered configuration templates.
