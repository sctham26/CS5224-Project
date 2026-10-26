# SPIP ESG Analytics Engine

Standalone, production-oriented Python engine for ESG harmonisation, rule-based peer
selection, empirical percentile benchmarking and gap analysis. No AWS, database,
frontend or AI-service dependencies.

## Install & Run

```powershell
pip install -r requirements.txt
python -m pytest -q                  # 103 tests (src/ resolved via pytest pythonpath)
python examples/run_example.py       # building-level benchmark -> examples/output.json
# HTTP API for the dashboard (team contract output):
python -m uvicorn api:app --app-dir src --port 8000
# Importer: public baseline CSV -> spip_public.observation (backend-owned)
python src/import_baseline.py --data data/cleaned/public_esg_baseline.csv --dry-run
```

## Architecture

| Stage | Module | Responsibility |
|---|---|---|
| Schema | [schemas.py](src/schemas.py) | Pydantic models, scope/direction enums |
| Registry | [metrics.py](src/metrics.py) | Direction, scope, unit → canonical conversion |
| Harmonisation | [harmonisation.py](src/harmonisation.py) | CSV load, scope partition, unit harmonisation |
| Peers | [peers.py](src/peers.py) | Deterministic fallback rules, min peer size 5 |
| Benchmark | [benchmark.py](src/benchmark.py) | Median, rank, empirical percentile |
| Gap analysis | [gap_analysis.py](src/gap_analysis.py) | Orchestration, JSON contract |
| Contract adapter | [contract.py](src/contract.py) | Team CSV in → engine → team output contract out |
| Auth | [auth.py](src/auth.py) | Cognito access-token checks, `sub` → tenant membership |
| Data source | [datastore.py](src/datastore.py) | Tenant-scoped CSV/PostgreSQL load with a TTL cache |
| Importer | [import_baseline.py](src/import_baseline.py) | Baseline CSV → `spip_public.observation`, idempotent upsert |
| HTTP API | [api.py](src/api.py) | FastAPI `GET /entities`, `GET /analysis/{id}`, `POST /analyze`, tenant-scoped CORS |

## Security and tenancy

The engine stays free of AWS/database dependencies; identity and storage live in the
two boundary modules above.

- **Token**: `Authorization: Bearer <Cognito access token>` on every protected route.
  Signature via JWKS, exact issuer, expiry, `token_use=access`, browser `client_id` and
  the `spip/access` scope. `401` for missing/invalid tokens, `403` for a valid account
  without an active tenant membership.
- **Tenant**: resolved from server-controlled `tenant_membership` by verified `sub`.
  Request bodies, headers, email and ID-token fields never decide the tenant. The API
  response `tenant_id` is stamped with the authenticated tenant.
- **Data**: a caller sees the public baseline plus its own private rows only. Another
  tenant's entity is invisible, so `/analysis/{id}` returns `404`, not `403`.
- **Database**: [migrations/001_public.sql](migrations/001_public.sql),
  [migrations/002_tenant.sql](migrations/002_tenant.sql),
  [migrations/003_jobs.sql](migrations/003_jobs.sql) and
  [migrations/004_observation_upsert_key.sql](migrations/004_observation_upsert_key.sql)
  create `observation`, `tenant_membership`, `ingestion_job` and the importer's upsert
  key; tenant tables use row-level security driven by `SET LOCAL app.tenant_id` /
  `app.user_sub`, and fail closed when the context is unset.
- **CORS** is limited to `SPIP_ALLOWED_ORIGINS` and allows the `Authorization` header.

**Role capabilities (deliberate boundary)**: `cognito:groups` is recorded but grants no
extra capability — `spip-admin` does not bypass tenant isolation, and every route is a
tenant-scoped data operation, so no group-based branch exists to abuse. When the first
genuinely privileged endpoint appears, add a static `group → allowed routes` table plus a
test for "wrong group 403 / right group 200" rather than scattering admin checks.

**Ownership (confirmed with Jin, 2026-10-25)**: the cloud team owns authentication plus
the authorisation *contract* and writes `tenant_membership`; the backend enforces
authorisation (per-request tenant scoping + RLS context) and owns **data import**. The
public baseline is imported exactly like any other dataset — only its `tenant_id`
(`PUBLIC`) and visibility rules differ — via
[import_baseline.py](src/import_baseline.py), which upserts on
`(tenant_id, entity_id, reporting_year, reporting_scope, metric_code)` so re-runs correct
rows instead of duplicating them.

Runtime settings use the names the `cloud-config` deployment injects:

| Runtime setting | Purpose |
|---|---|
| `SPIP_AUTH_ENABLED` | Optional override; defaults to "auth on when `SPIP_JWT_ISSUER` is set" |
| `SPIP_JWT_ISSUER` / `SPIP_JWT_AUDIENCE` | Cognito pool issuer and accepted audiences (`client_id`/`aud`) |
| `SPIP_AUTH_SCOPE` | Required access-token scope (`spip/access`); set empty to skip the check |
| `SPIP_DEMO_TENANT` | Tenant used when auth is disabled locally |
| `SPIP_PUBLIC_DATABASE_URL` / `SPIP_TENANT_DATABASE_URL` | PostgreSQL sources (built by `cloud-config/backend_cloud/entrypoint.py`); absent → local CSV |
| `SPIP_TENANT_DATA_BUCKET` | Tenant S3 bucket for uploads and job results |
| `SPIP_JOB_QUEUE_URL` / `SPIP_JOB_DLQ_URL` | Ingestion queue and dead-letter queue |
| `SPIP_UPLOAD_URL_TTL_SECONDS` | Presigned PUT lifetime (default 300) |
| `SPIP_JOB_LEASE_SECONDS` | Worker lease on a claimed job (should match queue visibility) |
| `SPIP_DATA` | CSV path for the local source (defaults to the public baseline) |
| `SPIP_CACHE_TTL_SECONDS` | Cache lifetime for a tenant's loaded records |
| `SPIP_ALLOWED_ORIGINS` | Allowed browser origins for CORS |
| `SPIP_API_PREFIX` | Insurance switch: keep business routes unprefixed (default) or under `/api`; `/health` is always unprefixed |

## Ingestion pipeline

Routes match the `cloud-config` gateway: `POST /uploads`, `POST /jobs`, `GET /jobs/{job_id}`.

1. `POST /uploads` returns a short-lived presigned PUT for
   `tenants/<tenant>/uploads/<uuid>.csv`. File bytes never pass through the API.
2. `POST /jobs` requires `Idempotency-Key`, validated per tenant + endpoint + request
   hash: an identical retry returns the same job (`202`, `Idempotent-Replay: true`), a
   changed body under the same key is `409`. A key outside the caller's upload prefix is
   `404`.
3. States are `PENDING → QUEUED → RUNNING → SUCCEEDED | FAILED` and never move backwards;
   `ingestion_job` enforces this with a trigger as well as the store.
4. The worker (`python -m worker`, the deployment's `worker_command`) claims each job with
   a lease, analyses the uploaded CSV and writes the result to
   `tenants/<tenant>/jobs/<job>/result.json` before marking it terminal. It acknowledges
   SQS only after that durable write, so transient failures stay retryable and duplicate
   deliveries cannot re-run a finished job.
5. Unreadable uploads fail asynchronously (`FAILED` + error), not as an HTTP error on the
   earlier `202`. `python -m worker --reconcile-dlq` turns exhausted messages into visible
   `FAILED` jobs instead of leaving them `RUNNING` forever.

Locally (no bucket/queue configured) these routes answer `503`; `POST /analyze` remains a
synchronous local convenience and is not a production upload path.

## Interfaces

Public callable API and the inputs this engine needs from others:
[INTERFACES.md](INTERFACES.md).

Post-deployment acceptance (stdlib only, no app install needed):

```powershell
python scripts/verify_contract.py --base-url https://<cloudfront-domain>/api --token <access-token>
```

It checks `/health`, token enforcement, `/entities` fields, one `/analysis` payload,
unknown-entity `404`, and `POST /jobs` header validation; exits non-zero on failure.

## Design guarantees

- **Scope isolation**: asset and portfolio records are partitioned before analysis; a
  portfolio record is never a peer for an asset target.
- **Compatibility**: peers must match scope, reporting period, metric availability and
  canonical unit. Incompatible units are dropped with reason `unsupported_unit`.
- **Common schema** (design §1.1): each observation carries `source`; each analysed
  metric carries `comparability_status` (`comparable` / `incompatible` / `missing`).
  Missing and incompatible observations are retained as unavailable, never forced into
  a comparison.
- **Determinism**: peer IDs are sorted; percentile uses target-inclusive ranks. When no
  reporting period is specified, the entity's latest period is analysed.
- **Gap sign**: `gap_to_median > 0` means improvement is needed to reach the peer
  median; `<= 0` means already at or better than median.
- **Gap flagging** (design §1.3): `percentile` is direction-aware (100 = best), so a
  comparable metric is flagged (`gap_flag: true`, `gap_type: performance_gap`) when its
  percentile falls below the per-metric `gap_percentile_threshold`. Missing or
  non-comparable metrics are reported as `gap_type: disclosure_gap` with reason
  `not_disclosed` or `incomparable_unit`. When no peer group can be formed the
  benchmark is `unavailable` (`insufficient_peers`) and no gap is asserted.
- **Outputs are decision-support signals**, not financing decisions.

## Configuration

- [config/metrics.yaml](config/metrics.yaml) —
  metrics, canonical units, direction, conversion factors, `gap_percentile_threshold`.
- [config/peer_rules.yaml](config/peer_rules.yaml) —
  `min_peer_size: 5` and ordered fallback rules.

## Design review points (addressed, pending team confirmation)

The preliminary-design review raised two clarifications; the engine implements a
concrete, configurable position while leaving the business choice open:

1. **Benchmarking unit.** Analysis is at the **asset/property** level: peer criteria are
   asset characteristics (`property_type`, `region`), not company type or portfolio
   characteristics. Asset and portfolio records are partitioned and never mixed. Whether
   the final peer taxonomy should also include company/certification dimensions is a
   team decision — see assumption 3 below.
2. **Peer-group fallback policy.** Specified in
   [config/peer_rules.yaml](config/peer_rules.yaml): minimum peer-group size is **5**
   (excluding the target). The relaxation order follows the team's output contract
   (PR #1): `property_type+region → region → property_type → all in scope` — region is
   relaxed first. If no rule meets the minimum the benchmark is `unavailable`.

**Naming/unit baseline**: metric codes, canonical units and direction now follow the
team's `docs/metric_dictionary.csv` (PR #1), e.g. `ENERGY_INTENSITY_EUI` / `kWh/m2/yr`.

## Assumptions requiring confirmation with real ESG datasets

1. Reporting-period compatibility is exact-string matching (`"2024"`); team CSV uses
   `reporting_year` (int) mapped to the same matcher. Confirm partial-period overlap.
2. Real team data is wired in: `data/cleaned/public_esg_baseline.csv` (BCA building-level
   EUI, 2017-2025) is the API default and is read through the adapter; the synthetic
   dataset stays for tests. Entity IDs encode their source vintage
   (`SG_307591_2020_0` for the 2017-2020 listing, `SG_129907_LATEST_0` for 2022-2025), so
   peers never mix buildings from different vintages in one cohort.
3. Certification is loaded but not yet used in peer selection — confirm whether it is a
   peer dimension.
4. Dashboard/API: the HTTP layer (`src/api.py`) is protected and tenant-scoped, and
   `GET /entities` supplies the entity/year options. The React dashboard still reads
   hardcoded entities — switch it to `GET /entities` + `GET /analysis/{entity_id}`.
5. `gap_percentile_threshold: 40` per metric is a placeholder — confirm the agreed gap
   threshold (and whether it differs by metric or portfolio).
6. `source` provenance is a free-text field — confirm the required granularity
   (report/page/dataset) for the common schema.

## Public baseline facts (data/cleaned/public_esg_baseline.csv)

- **Version-specific entity IDs**: the 2017–2020 listing uses `SG_307591_2020_0`, the
  2022–2025 workbook uses `SG_129907_LATEST_0`. The same physical building therefore has a
  different ID per source vintage — join on `postal_code` / `entity_name`, never on
  `entity_id` alone.
- **Non-consecutive years**: only 2017–2020 and 2022–2025 exist; 2021 is absent. When
  `reporting_year` is omitted, the entity's latest period (2025) is analysed. Clients must
  read the available years from `GET /entities` instead of assuming a fixed range.
- **Comparability distribution**: `COMPARABLE` 6187 / `UNIT_CONVERTED` 5870, plus
  `COMBINED_METERING` 196, `ANOMALY_FLAGGED` 6 and `BOUNDARY_MISMATCH` 2. The last three
  are excluded by the adapter, so they surface as disclosure gaps, not comparisons.

## Needed from the team

- @Michael: does PR #2 change the analytics request/response shape? Also please confirm the frontend handles`sample_size_n < 5` ,`INCOMPLETE_DATA` and`BOUNDARY_MISMATCH` , and switches its dropdowns to`GET /entities` .

- @Jin — answers received (2026-10-25): authentication is implemented; authorisation is
  still an agreed interface only; `tenant_membership` is managed on the cloud side;
  baseline import belongs to the backend. Two follow-ups remain:
  1. Since authorisation is not implemented yet, the backend is currently the only
     enforcement point (tenant scoping on every read + RLS `SET LOCAL app.tenant_id`).
     Confirm nothing in the gateway overrides `Authorization` before the ALB, and that
     the app DB roles cannot `BYPASSRLS`.
  2. Migration ownership: the app must not own `observation` / `ingestion_job`, otherwise
     `FORCE ROW LEVEL SECURITY` is bypassed. Confirm who runs
     `migrations/001–004` and grants `SELECT` / `INSERT` / `UPDATE` to the app roles.

- @Auxane / @Jin: worker `worker_command` = `python src/worker.py` (or `python -m worker`
  with `src` on `PYTHONPATH`); keep queue visibility aligned with
  `SPIP_JOB_LEASE_SECONDS`. DLQ reconciliation can run as a scheduled ECS task with
  `python src/worker.py --reconcile-dlq`.

- **Resolved (2026-10-25)**: CloudFront keeps the browser-facing `/api` prefix and strips
  it, the gateway routes are unprefixed, and ECS passes `SPIP_API_PREFIX=""`. The API
  reads that variable ([api.py](src/api.py#L61)) and `/health` stays unprefixed for the
  ALB probe. Deployed migrations `001`–`004` and the baseline import (12,767
  observations) exited zero.
- **Real signed-in acceptance passed (2026-10-25)**: with a Cognito access token from the
  hosted UI, `GET /api/entities?scope=asset` returned 200 with the imported baseline
  (real `SG_...` IDs, years 2022–2025) and `GET /api/analysis/SG_228218_LATEST_6?scope=
  asset&reporting_year=2024` returned 200 — proving prefix stripping, JWKS signature
  validation, `sub` → tenant resolution and the PostgreSQL read path in one call.
- **Upload path defect found by live acceptance (2026-10-25, fixed)**: the presigned PUT was
  generated with Signature V2, and the tenant bucket is SSE-KMS, so S3 returned
  `400 InvalidArgument — Requests specifying Server Side Encryption with AWS KMS managed
  keys require AWS Signature Version 4`. [jobs.py](src/jobs.py#L351-L366) now builds the
  presign client with `s3v4` + virtual addressing, and
  [test_presign_sigv4.py](tests/test_presign_sigv4.py) locks it. **This needs an image
  rebuild before `/uploads` can succeed in the sandbox**; `POST /uploads` itself already
  returns 201 and writes the expected `tenants/<tenant>/uploads/<uuid>.csv` key.
- **Upload → worker → result closed (2026-10-25)**: `POST /api/uploads` 201 → presigned `PUT`
  200 (URL now carries `X-Amz-Algorithm=AWS4-HMAC-SHA256`) → `POST /api/jobs` 202
  (`QUEUED`) → `GET /api/jobs/{id}` `SUCCEEDED` in ~2 s with the full analysis payload
  inline (11 metrics, `peer_cohort` OFFICE/SG n=239, 3 benchmarks, 8 disclosure gaps).
- **Tenant isolation proven at HTTP level (2026-10-25)**: submitting another tenant's
  `upload_key` (`tenants/spip-tham/...`) returns `404 {"detail":"upload_key not found"}`
  instead of leaking its existence. Entity-level isolation still needs private rows in a
  second tenant before a `/analysis/{id}` 404 can be demonstrated.
- **Still open**: the `cognito:groups` decision below (currently a written boundary, no
  group-based code path).
# SPIP - Cloud Deployment

Deployment plan for `cloud-config` (Alex and Auxane)

**Status:** frontend hosting, Cognito and the sandbox backend/API infrastructure are deployed. The backend migrations and public baseline import have run; real-user tenant acceptance and the active frontend branch’s API/auth integration remain pending. See [current API integration](docs/API_INTEGRATION.md) and the dated [team handoff](docs/CLOUD_HANDOFF.md).

## 1. Before provisioning

- Confirm the AWS account, region, available permissions, lease expiry, remaining budget, and existing resources.
- Choose the infrastructure-as-code tool, shared configuration/state, resource names, and responsibility for each change.
- Agree the application source versions, runtime configuration, and storage/API integration boundaries with Song and Sin Che.
- Estimate the chosen stack's running costs, including database and networking charges.

## 2. Deployment tasks

The table records the original scope and acceptance criteria. Current delivery status is maintained in the [handoff](docs/CLOUD_HANDOFF.md).

| Area | Work to implement | Completion check |
| --- | --- | --- |
| Infrastructure and permissions | Define VPC/subnets, security groups, service roles, protected secrets, and reproducible infrastructure configuration. | Required connections work; database access is private; roles have the intended permissions. |
| Backend runtime | Add a Dockerfile, publish a versioned image to ECR, and configure the ECS Fargate service, startup command, data/configuration paths, and health checks. | The identified image serves the agreed synthetic analysis and produces logs. |
| API access | Configure API Gateway and its actual backend integration; a private route may use a VPC link and internal load balancer. Configure browser origins. | The deployed API URL reaches Fargate through the documented route. |
| Authentication | Configure Cognito, token validation, trusted organisation membership, and frontend login settings. | Valid users connect; invalid tokens and unauthorised organisation access are rejected. |
| Database | Provision private RDS PostgreSQL; add schema migrations, data-access integration, and Row-Level Security using a restricted application role. | Data survives restarts; two organisations cannot read or modify each other's private rows. |
| File storage | Configure private S3 storage, organisation-scoped access policies, authorised upload URLs, ownership records, and retention. | Users can upload permitted files and cannot access or replace another organisation's files. |
| Background processing | Use explicit job submission and a backend dispatcher to SQS; add a Fargate worker, retries, duplicate protection, failed-message handling, and persistent job status. Reuse Song's engine with authorised inputs. | An upload produces stored results; concurrent files stay separate and retries create no duplicate records. |
| Frontend hosting | Build the frontend; upload the output to private S3 and serve it through CloudFront with origin access control and HTTPS. Supply deployed API/login configuration. | The website works without a local backend and displays the uploaded data's results. |
| Monitoring and costs | Configure CloudWatch logs, retention, failure/backlog monitoring, cost tracking, and cleanup procedures. | A failed upload can be diagnosed; resource consumption and shutdown/retention choices are documented. |
| Deployment automation | Add GitHub Actions for checks, builds, and releases after verifying AWS authentication support. Define triggers, release coordination, and recovery. | A known commit can be released repeatedly; its deployed version and recovery procedure are recorded. |

The existing API reads local files. S3/PostgreSQL adapters and the queued worker still need implementation; deploying the current code does not add them automatically. Coordinate those interfaces with Song and the cloud API/login/upload integration with Sin Che.

## 3. Implementation order

1. Confirm permissions, interfaces, costs, and a working local baseline.
2. Prepare infrastructure and packaging; deploy a synthetic-data website/API demonstration.
3. Complete authentication, tenant isolation, durable storage, and queued ingestion before accepting private organisation data.
4. Verify the complete upload-to-dashboard journey, record operational evidence, and automate the verified release path.

AI infrastructure is outside scope. Add EventBridge only if scheduled public-data refreshes are agreed.

## 4. Deployment handover

Record the account/region, resource names, infrastructure and application versions, website/API URLs, non-secret settings, secret locations, deployment triggers, verification results, running costs, recovery steps, and cleanup/data-retention procedure.

Keep **planned**, **implemented**, **tested**, and **deployed** statuses separate.

Application walkthroughs and technical explanations are in the [Project and Architecture Guide](docs/PROJECT_GUIDE.md).

## 5. Component delivery boundaries

Alex proposed implementing these components individually before connecting them through an end-to-end test:

1. Authentication and authorisation.
2. Frontend distribution and storage (CloudFront + S3).
3. Backend runtime deployment and input/output integration.
4. Database deployment and multi-tenant isolation validation.
5. File upload and asynchronous processing.

## 6. Frontend delivery

Python CDK (`infra/`, managed by uv) defines private S3, CloudFront OAC, and a scoped GitHub OIDC publishing role. The [workflow](.github/workflows/frontend.yml) builds and checks PRs, and publishes relevant pushes to `cloud-config`/`main` to one development site. See [setup, branch coordination, API limitations, and recovery](docs/FRONTEND_DEPLOYMENT.md).

Development website: https://d10rc41o4pb0h.cloudfront.net. The frontend renders, but analytics requires the separately planned backend integration.

## 7. Proposed backend integration contract

The [backend–cloud contract draft](docs/BACKEND_CLOUD_CONTRACT.md) reserves upload/job/result interfaces, worker message envelopes, storage and secret configuration, and responsibility boundaries. It is a proposal for backend-team review; it does not define ESG columns or business tables and is not deployed.

## 8. Backend cloud configuration

[Backend deployment](docs/BACKEND_DEPLOYMENT.md) describes the opt-in data/runtime CDK stacks, PostgreSQL logical-database bootstrap, application-role permissions, reserved JWT-protected API routes and worker configuration. The backend [interface draft](docs/BACKEND_CLOUD_CONTRACT.md) remains included. Current deployment evidence is in the API integration guide; application schema and processing code remain backend-owned.

## 9. Login and authorization integration

[Login module and auth contract](docs/AUTH_CONTRACT.md) documents the independently deployed Cognito stack, invite-only accounts, frontend login/logout and authenticated requests, public build settings, local demo mode and backend tenant-authorization responsibilities. The active frontend branch still needs to connect its upload UI to the deployed backend API. Cognito login does not establish tenant membership or complete backend isolation.

## 10. API integration

[Current cloud API integration](docs/API_INTEGRATION.md) defines CloudFront `/api` prefix removal, Cognito-protected business routes, public health, pinned backend packaging and separate migration/import operations. Frontend JavaScript remains owned by the frontend branch; cloud-config pushes no longer publish its old frontend copy.
