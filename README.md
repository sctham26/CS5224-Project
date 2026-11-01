# SPIP: Sustainable Property Intelligence Platform

CS5224 Cloud Computing, Group 5.

SPIP is a multi-tenant SaaS platform that harmonises real-estate ESG data,
benchmarks each property against a rule-based peer group, and flags performance and
disclosure gaps. It runs on AWS: a React frontend on CloudFront, a FastAPI analytics
backend on ECS Fargate, PostgreSQL on RDS, S3 + SQS for uploads, and Cognito for login.

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

```
Browser ──► CloudFront ──┬─► S3 (React build)
                         └─► /api/* ──► API Gateway (JWT check) ──► ALB ──► ECS Fargate: FastAPI
                                                                              │
          Cognito (login, access token)                                       ├─► RDS PostgreSQL (row-level security)
                                                                              └─► S3 uploads ─► SQS ─► Fargate worker
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

Response shapes: [INTERFACES.md](INTERFACES.md) and `schemas/analytics_output_contract.json`.

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

**Done:** frontend hosting, Cognito, backend/API infrastructure, migrations and baseline
import (12,767 observations), signed-in API acceptance, upload → worker → result flow,
upload-level tenant isolation, and the integrated frontend (dashboard UI + Cognito auth).

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
