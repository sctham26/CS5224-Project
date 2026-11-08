# SPIP: Sustainable Property Intelligence Platform

CS5224 Cloud Computing, Group 5.

SPIP is a multi-tenant SaaS platform that harmonises real-estate ESG data,
benchmarks each property against a rule-based peer group, and flags performance and
disclosure gaps. It runs on AWS: a React frontend on CloudFront, a FastAPI analytics
backend on ECS Fargate, PostgreSQL on RDS, S3 + SQS for uploads, and Cognito for login.

<<<<<<< HEAD
Outputs are decision-support signals, not financing decisions.

- **Development site:** https://d10rc41o4pb0h.cloudfront.net (invite-only Cognito login)
- **Current status and open items:** [Status](#status-and-open-items) below

---

## Repository layout

| Path | What it contains | Owner |
|---|---|---|
| `src/` | Analytics engine and FastAPI app (harmonisation, peers, benchmark, gap analysis, auth, jobs, worker) | Song |
| `tests/` | Backend pytest suite, plus the frontend deploy-script tests | Song / Alex |
| `config/` | `metrics.yaml` (metrics, units, direction, gap threshold), `peer_rules.yaml` (min peer size, fallback order) | Song |
| `migrations/` | PostgreSQL schema and row-level security (`001`–`004`) | Song |
| `frontend/` | React + Vite dashboard, comparison tool, CSV upload, Cognito login | Sin Che (UI) / Alex (auth) |
| `infra/` | AWS CDK stacks (Python, managed by uv): hosting, Cognito, data, runtime, operations | Alex / Auxane |
| `backend_cloud/` | Container entrypoints and database bootstrap for the cloud runtime | Alex / Auxane |
| `scripts/` | Deploy, image build, operator tasks, contract verification | Alex / Auxane |
| `.github/workflows/` | CI/CD for frontend and backend cloud stacks | Alex / Auxane |
| `data/` | Raw sources, `cleaned/public_esg_baseline.csv` (BCA, SGX, grid factors), samples, test fixtures | Nasya |
| `prepare_data.py`, `schemas/` | Builds the public baseline CSV; analytics output contract | Nasya |
| `docs/` | Detailed design, deployment and integration documents (see [Documentation](#documentation)) | All |

## Branches

| Branch | Purpose |
|---|---|
| `feature/frontend-dashboard` | Frontend UI work (Sin Che) |
| `backend-analysis` | Analytics engine and API (Song) |
| `cloud-config` | AWS infrastructure, Cognito, CI/CD (Alex, Auxane) |
| `integration` | The three branches above merged and tested together (Michael) |
| `main` | Released version; CI/CD runs on `main` and `cloud-config` only |

---

## Run locally

Requirements: Python 3.12 (3.10+ works), Node.js 22+.

**Backend** (from the repository root):

```bash
python -m venv .venv
source .venv/bin/activate            # Windows Git Bash: source .venv/Scripts/activate
python -m pip install -r requirements.txt
=======
```powershell
pip install -r requirements.txt
python -m pytest -q                  # 116 tests (src/ resolved via pytest pythonpath)
python examples/run_example.py       # building-level benchmark -> examples/output.json
# HTTP API for the dashboard (team contract output):
>>>>>>> origin/backend-analysis
python -m uvicorn api:app --app-dir src --port 8000
```

Locally, authentication is off and data is read from `data/cleaned/public_esg_baseline.csv`
(set `SPIP_DATA` to use another CSV). Interactive API docs: http://localhost:8000/docs.

**Frontend** (second terminal):

```bash
cd frontend
cp .env.example .env.local           # VITE_AUTH_MODE=demo: skips login for local use
npm install
npm run dev                          # http://localhost:5173
```

In development the frontend calls `http://localhost:8000`; production builds call `/api`.
Both come from `frontend/src/api.js`, overridable with `VITE_API_BASE_URL`.

## Prepare the public data

After installing the Python requirements above, run from the repository root:

```bash
python prepare_data.py
```

The script reads the local BCA files, curated SGX values, grid factors and
`docs/metric_dictionary.csv`. It rebuilds `data/cleaned/public_esg_baseline.csv`
(12,765 BCA observations and two SGX portfolio disclosures) and checks the format
of `data/samples/private_esg_sample.csv`. Raw sources and samples are unchanged.
Rebuilding the CSV does not update data already imported into the database.

- `data/samples/private_esg_sample.csv` contains 34 synthetic records in the public
  dataset's 20-column format. `utility_calculation_examples.csv` in the same folder
  contains three calculation examples with expected results. These are test data,
  not public benchmark peers.
- The two SGX disclosures have different measurement boundaries from BCA buildings
  and are marked `BOUNDARY_MISMATCH`. Do not pool them with building-level EUI.
- Derived carbon values are electricity CO2 estimates; the 2025 grid factor is
  provisional. Public water peers and verified 2030 targets are not supplied.

Sources, cleaning rules, reproduction checks and the older upload-fixture formats
are explained in [docs/data_handoff.md](docs/data_handoff.md).

## Test

```bash
python -m pytest -q                                          # backend
python -m unittest discover -s tests -p "test_*_frontend.py" # deploy-script tests (CI step)
cd frontend && npm run lint && npm test && npm run build     # frontend
cd infra && uv run --locked pytest -q                        # infrastructure
```

After a deployment, `scripts/verify_contract.py --base-url https://<site>/api --token <access-token>`
checks health, token enforcement, `/entities`, `/analysis` and job validation.

---

## Architecture

<<<<<<< HEAD
```
Browser ──► CloudFront ──┬─► S3 (React build)
                         └─► /api/* ──► API Gateway (JWT check) ──► ALB ──► ECS Fargate: FastAPI
                                                                              │
          Cognito (login, access token)                                       ├─► RDS PostgreSQL (row-level security)
                                                                              └─► S3 uploads ─► SQS ─► Fargate worker
=======
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
| Jobs | [jobs.py](src/jobs.py) | Presigned S3 upload, SQS enqueue, idempotent job store (memory / PostgreSQL) |
| Worker | [worker.py](src/worker.py) | SQS consume: lease → S3 fetch → analysis → result write, ack only after terminal state; DLQ reconciliation |
| HTTP API | [api.py](src/api.py) | FastAPI `GET /entities`, `GET /analysis/{id}`, `POST /uploads`, `POST /jobs`, `GET /jobs/{id}`, local `POST /analyze`, tenant-scoped CORS |

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
| `SPIP_PERSIST_UPLOADS` | `1` upserts each upload into the tenant's own observations after analysis (requires an `INSERT`/`UPDATE` grant); default off, and RLS keeps those rows private to that tenant |
| `SPIP_UPLOAD_URL_TTL_SECONDS` | Presigned PUT lifetime (default 300) |
| `SPIP_JOB_LEASE_SECONDS` | Worker lease on a claimed job (should match queue visibility) |
| `SPIP_DATA` | CSV path for the local source (defaults to the public baseline) |
| `SPIP_CACHE_TTL_SECONDS` | Cache lifetime for a tenant's loaded records |
| `SPIP_ANALYSIS_CACHE_TTL_SECONDS` | Lifetime of a computed report in memory (default 60, `0` disables); a datasource reload always misses |
| `SPIP_ANALYSIS_CACHE_MAX` | Maximum cached reports per process (default 128, oldest evicted first) |
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
   a lease, merges the uploaded rows with the tenant-visible stored dataset (public
   baseline plus the tenant's own rows) and writes the result to
   `tenants/<tenant>/jobs/<job>/result.json` before marking it terminal. The upload
   supplies the target; the stored data supplies the peer cohort, so a file holding one
   building is still benchmarked against the full baseline. Overlapping rows are resolved
   on the importer's upsert key, so a re-uploaded building replaces its stored
   observation instead of appearing twice. It acknowledges SQS only after that durable
   write, so transient failures stay retryable and duplicate deliveries cannot re-run a
   finished job.
5. Unreadable uploads fail asynchronously (`FAILED` + error), not as an HTTP error on the
   earlier `202`. `python -m worker --reconcile-dlq` turns exhausted messages into visible
   `FAILED` jobs instead of leaving them `RUNNING` forever.
6. With `SPIP_PERSIST_UPLOADS=1` the worker also upserts the uploaded rows into the
   tenant's own observations, on the importer's upsert key and stamped with the
   authenticated tenant — a CSV cannot claim another tenant. RLS keeps those rows invisible
   to everyone else, so this makes a report re-runnable and gives the tenant a multi-year
   trail; it does **not** add rows to another tenant's cohort.

Locally (no bucket/queue configured) these routes answer `503`; `POST /analyze` remains a
synchronous local convenience and is not a production upload path.

## Input format (prototype scope)

An upload must already be in the team's long CSV. The prototype does not translate a
customer's own export: headers, units and identifiers are assumed to match the contract,
and a file that does not is rejected as `FAILED` at the job's terminal state (the HTTP
call still returns `202`). Nothing is coerced or guessed.

Required columns — the rest of the 20-column header may be empty: `entity_id`,
`reporting_scope`, `reporting_year`, `metric_code`, `standardised_value`,
`canonical_unit`, `comparability_status`, `property_type`, `region`. `metric_code` must
be one of the 11 declared in [config/metrics.yaml](config/metrics.yaml),
`comparability_status` must be one of `COMPARABLE`, `UNIT_CONVERTED`,
`BOUNDARY_MISMATCH`, `ANOMALY_FLAGGED`, and an empty `standardised_value` means "not
disclosed", which is not the same as `0`.

A downloadable template fixes the expected shape, and the frontend now maps a customer
export onto it in the browser: header synonyms with a human confirmation step
(`feature/csv-column-mapping`, 34 frontend tests, not yet merged into `integration`).
Unit inference, unmapped-metric reporting and fuzzy `postal_code` / `entity_name`
matching remain future work, so the honest claim is "one supported format with assisted
mapping", not universal ingestion.

## Scaling

The deployment is one API service and one worker behind one queue, sized for the
prototype. Nothing below is implemented; it describes the growth path and what each step
costs.

| Component | Growth trigger | Lever | Trade-off |
|---|---|---|---|
| API | ALB p95 latency, 5xx rate, CPU | raise the ECS desired count — stateless, so this scales roughly linearly | the database connection pool saturates before CPU does, and each instance warms its own TTL cache |
| Worker | `ApproximateNumberOfMessagesVisible` sustained above a threshold, or job latency | more worker tasks; receive a batch instead of `MaxNumberOfMessages=1` | SQS polling and database writes are paid per unit of throughput; the queue already absorbs ingest bursts, so spikes should not force API scaling |
| Data source | observation count, tenant count, `/analysis` p95 | move peer selection into SQL (indexed on scope/region/property_type/reporting_year/metric_code), or precompute per-cohort aggregates | precomputation trades staleness and storage for latency, and new data or a new tenant invalidates the snapshot |
| Cache | frames and reports are cached per process, so each instance recomputes its own and a restart drops them | shared cache (ElastiCache), or S3-backed report objects | one more service to run and pay for |

The expensive component is not the API tier. It is `PostgresDataSource`: every worker job
and every API cache miss loads the public baseline plus the tenant's rows as one frame and
hands all of it to the engine. That is fine at 12,767 observations and is the first
thing to change at millions. The worker is capped less by compute than by one message per
poll; the queue is the shock absorber, so an ingest spike costs queue latency rather than
API availability.

Cost is dominated by ECS task hours, the database instance and storage, S3 storage and
requests, and CloudFront; the queue is the cheapest line item and should not drive
design.

## Interfaces

Public callable API and the inputs this engine needs from others:
[INTERFACES.md](INTERFACES.md).

Post-deployment acceptance (stdlib only, no app install needed):

```powershell
python scripts/verify_contract.py --base-url https://<cloudfront-domain>/api --token <access-token>
>>>>>>> origin/backend-analysis
```

CloudFront strips the `/api` prefix; backend routes are unprefixed (`SPIP_API_PREFIX=""`).

### Analytics pipeline

1. **Harmonisation**: map raw rows to a common schema and convert units to canonical ones.
   Missing or unusable values are kept as unavailable, never forced into a comparison.
2. **Peer selection**: same scope and reporting year; fallback order
   `property_type + region → region → property_type → all`, minimum **5** peers.
3. **Benchmark**: peer median, rank, and empirical percentile (100 = best; direction-aware,
   e.g. lower energy intensity is better).
4. **Gap analysis**: a *performance gap* when the percentile is below the threshold
   (currently 40); a *disclosure/data gap* when a metric is missing or not comparable.

### API

| Route | Purpose | Auth |
|---|---|---|
| `GET /health` | Liveness | Public |
| `GET /entities?scope=asset` | Buildings and their available reporting years | Token + tenant |
| `GET /analysis/{entity_id}?scope=&reporting_year=` | Metrics, peer cohort, benchmarks, gaps | Token + tenant |
| `POST /uploads` | Presigned S3 PUT URL for a CSV upload | Token + tenant |
| `POST /jobs` | Start processing an upload (`Idempotency-Key` required) | Token + tenant |
| `GET /jobs/{job_id}` | Job status and result | Token + tenant |
| `POST /analyze` | Synchronous local-only upload (not exposed in the cloud) | Local only |

Current response details: [INTERFACES.md](INTERFACES.md).
`schemas/analytics_output_contract.json` is an earlier draft; align it with the
current API before using it to validate responses, including insufficient-peer results.

### Security and tenancy

- Every protected request carries a Cognito **access token**; missing/invalid → `401`,
  no tenant membership → `403`.
- The tenant comes only from the server-side `tenant_membership` table (via the token's `sub`),
  never from the browser.
- Users see the public baseline plus their own tenant's rows. Another tenant's data is
  invisible (`404`). PostgreSQL row-level security enforces this in the database too.
- Cognito groups (`spip-admin`, `spip-backend`, `spip-customer`) are recorded but do not yet
  grant extra permissions.

---

## Status and open items

<<<<<<< HEAD
**Done:** frontend hosting, Cognito, backend/API infrastructure, migrations and baseline
import (12,767 observations), signed-in API acceptance, upload → worker → result flow,
upload-level tenant isolation, and the integrated frontend (dashboard UI + Cognito auth).
=======
1. Reporting-period compatibility is exact-string matching (`"2024"`); team CSV uses
   `reporting_year` (int) mapped to the same matcher. Confirm partial-period overlap.
2. Real team data is wired in: `data/cleaned/public_esg_baseline.csv` (BCA building-level
   EUI, 2017-2025) is the API default and is read through the adapter; the synthetic
   dataset stays for tests. Entity IDs encode their source vintage
   (`SG_307591_2020_0` for the 2017-2020 listing, `SG_129907_LATEST_0` for 2022-2025), so
   peers never mix buildings from different vintages in one cohort.
3. Certification is loaded but not yet used in peer selection — confirm whether it is a
   peer dimension.
4. Dashboard/API: the HTTP layer (`src/api.py`) is protected and tenant-scoped.
   The React frontend has switched to `AuthGate` + `GET /entities` for entity/year
   options and `VITE_API_BASE_URL` for the base URL (integration `779b7f0`). The
   "peer sample insufficient" rendering (`feature/insufficient-peer-display`, `c5dde1a`)
   and the real upload chain (`feature/real-csv-upload`, `e554763`) merged into
   `integration` via `217a184` and are live on the test site at `66dd626` (2026-11-01).
5. `gap_percentile_threshold: 40` per metric is a placeholder — confirm the agreed gap
   threshold (and whether it differs by metric or portfolio).
6. `source` provenance is a free-text field — confirm the required granularity
   (report/page/dataset) for the common schema.
>>>>>>> origin/backend-analysis

**Open:**
- Frontend: show "insufficient peer sample" when a cohort has fewer than 5 peers
  (currently "N/A"), and treat `INCOMPLETE_DATA` / `BOUNDARY_MISMATCH` as data gaps.
- Frontend: wire the real upload flow (`/uploads` → S3 PUT → `/jobs` → poll); the page is a demo.
- Backend: `/entities` lists some entity-years that `/analysis` returns `404` for (all values
  unusable, e.g. `COMBINED_METERING`). Either list only analysable years, or return them as data gaps.
- Backend: pending `gap_type → null` change for insufficient peers.
- CI does not run on `integration`; merge `integration` → `main` via pull request to run it.
- Evaluation: frontend end-to-end tests with a real login, the Excel baseline on SG buildings, and the user study.

Detailed per-component status: [docs/CLOUD_HANDOFF.md](docs/CLOUD_HANDOFF.md) and
[docs/ANALYTICS_ENGINE.md](docs/ANALYTICS_ENGINE.md#needed-from-the-team).

---

<<<<<<< HEAD
## Documentation

| Document | Contents |
|---|---|
| [docs/ANALYTICS_ENGINE.md](docs/ANALYTICS_ENGINE.md) | Engine modules, tenancy, ingestion pipeline, runtime settings, design guarantees, assumptions, baseline data facts |
| [docs/DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md) | AWS deployment plan, tasks and acceptance criteria |
| [docs/API_INTEGRATION.md](docs/API_INTEGRATION.md) | Cloud `/api` routing, operator steps, provisioned tenant memberships |
| [docs/AUTH_CONTRACT.md](docs/AUTH_CONTRACT.md) | Cognito login and frontend/backend auth contract |
| [docs/FRONTEND_DEPLOYMENT.md](docs/FRONTEND_DEPLOYMENT.md) | Frontend hosting, CI/CD and recovery |
| [docs/BACKEND_DEPLOYMENT.md](docs/BACKEND_DEPLOYMENT.md) | Backend CDK stacks and database bootstrap |
| [docs/BACKEND_RELEASE.md](docs/BACKEND_RELEASE.md) | Releasing backend application changes through GitHub Actions |
| [docs/BACKEND_CLOUD_CONTRACT.md](docs/BACKEND_CLOUD_CONTRACT.md) | Earlier backend–cloud interface proposal |
| [docs/CLOUD_HANDOFF.md](docs/CLOUD_HANDOFF.md) | Dated cloud handoff and branch integration notes |
| [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md) | Project and architecture walkthrough |
| [docs/data_handoff.md](docs/data_handoff.md), [docs/metric_dictionary.csv](docs/metric_dictionary.csv) | Data sources, metric definitions and units |
| [INTERFACES.md](INTERFACES.md) | Engine's public functions and API response shapes |
| [frontend/README.md](frontend/README.md) | Frontend features, local setup, API and login integration |
=======
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
  `SPIP_JOB_LEASE_SECONDS`. The worker now benchmarks uploads against the stored
  dataset, so it needs `SPIP_PUBLIC_DATABASE_URL` (and `SPIP_TENANT_DATABASE_URL` for
  tenant rows) in its task definition — without it the job still runs, but a
  single-entity upload has no peer cohort. For write-back (`SPIP_PERSIST_UPLOADS=1`)
  the tenant role also needs `INSERT`/`UPDATE` on `observation` — it currently has
  `SELECT` only ([002_tenant.sql](migrations/002_tenant.sql)); no policy change is
  required, because the `ALL` policy's `USING` clause doubles as the `INSERT` check.
  DLQ reconciliation can run as a scheduled
  ECS task with `python src/worker.py --reconcile-dlq`.

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
- **Presigned PUT (2026-10-25)**: the tenant bucket is SSE-KMS, so the URL must use
  Signature V4; [jobs.py](src/jobs.py#L351-L366) builds the presign client with `s3v4` +
  virtual addressing, locked by [test_presign_sigv4.py](tests/test_presign_sigv4.py).
- **Tenant isolation proven at HTTP level (2026-10-25)**: submitting another tenant's
  `upload_key` (`tenants/spip-tham/...`) returns `404 {"detail":"upload_key not found"}`
  instead of leaking its existence. Entity-level isolation still needs private rows in a
  second tenant before a `/analysis/{id}` 404 can be demonstrated.
- **Cloud release of the null-gap contract (2026-10-26)**: backend `e8a9f65` ships as the immutable
  image `spip-backend@sha256:817e9a4…` shared by the API, worker and operator task definitions;
  107/107 tests pass inside that Linux image. CloudFront `/api/health` returned 200 and
  unauthenticated `/api/entities` / `/api/analysis/...` returned 401 when re-checked on 2026-10-26.
  Authenticated `gap_type: null` behaviour was verified live on 2026-10-30 (below).
- **Backend release CI (2026-10-26, verified 2026-10-30)**: `.github/workflows/backend-deploy.yml` on
  `backend-analysis` calls `cloud-config`'s reusable `backend-release.yml@4210aa6` (build+test before
  credentials → OIDC → ECR push → release → `verify_api.py` → provenance artifact). Repeated
  push and manual-dispatch runs passed end to end; the live image is `sha256:b608bb66…` at
  commit `c76e547`, rollback chain `54bb8ee3…` → `499e2b28…` → `817e9a4…`. Manual dispatch
  works only when the branch selector targets `backend-analysis` — the caller's guard job
  fails other branches explicitly instead of silently skipping. It still does not cover
  `integration` or `main`.
- **Authenticated null-gap E2E (2026-10-30)**: with a real Cognito access token (tenant
  `spip-songsifan`), a purpose-built n=3 CSV closed the full pipeline live — the public baseline
  cannot trigger the path naturally because every asset pool holds ≥5 comparable entities, so the
  cohort (target + 2 peers) was uploaded and the worker analysed the file itself (since
  2026-11-07 it merges stored data, so a single-entity upload now gets the full cohort):
  `POST /api/uploads`
  201 → presigned PUT 200 → `POST /api/jobs` 202 → `SUCCEEDED` in ~1.3 s. The one disclosed metric
  returned `benchmark`/`gap_type`/`is_flagged` all `null` with `sample_size_n=0` and
  `fallback_reason=insufficient_peers`; the other ten metrics came back
  `DISCLOSURE_GAP`/`INCOMPLETE_DATA`. Undisclosed vs small-cohort are observably distinct on the
  live system.
- **Frontend merged and deployed (2026-11-01)**: `integration` consolidated backend `e6eb5c0`,
  cloud-config `83813f7` and `feature/frontend-error-handling` `217a184` (which carries both
  `feature/insufficient-peer-display` and `feature/real-csv-upload`) at `66dd626`; frontend CI
  run `#27` passed (26 tests, lint, build) and the build was published to the shared test site by
  run `#30` (`release.json` commit `66dd626`, bundle `index-CygRjUnp.js`). Verified after deploy:
  `/api/health` 200, `/api/entities` 401 unauthenticated, and the bundle carries both
  "Insufficient peer sample" and the `Idempotency-Key` upload path.
- **Frontend deploy triggers (as configured)**: pushes to `integration` run checks and the build
  only; the deploy job is gated to `push` on `main`, or a manual `workflow_dispatch` from
  `cloud-config` (or `main`) with `frontend_source_ref: integration` and `deploy: true`.
  A push to `integration` therefore never publishes by itself — publishing needs either the
  `integration → main` merge or an explicit dispatch.
- **Source synced, image status to confirm (2026-11-07)**: the merge, write-back and cache
  work above is on `backend-analysis` at `db3f8c5`, and a push there runs
  `.github/workflows/backend-deploy.yml` (build + release). The last digest recorded here
  is `sha256:b608bb66…` (`c76e547`), so check the Actions run before claiming the new code
  is live. Frontend: the 503 detail passthrough is in `integration` at `32a448c`, column
  mapping sits on `feature/csv-column-mapping` (`b80627e`, 34 frontend tests green, not
  merged), and the manual correctness workbook is `evaluation/correctness_SG.xlsx`
  (`6b5cfca`). Page-level browser E2E is still absent from the repository.
>>>>>>> origin/backend-analysis
