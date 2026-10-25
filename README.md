# SPIP ESG Analytics Engine

Standalone, production-oriented Python engine for ESG harmonisation, rule-based peer
selection, empirical percentile benchmarking and gap analysis. No AWS, database,
frontend or AI-service dependencies.

## Install & Run

```powershell
pip install -r requirements.txt
python -m pytest -q                  # 80 tests (src/ resolved via pytest pythonpath)
python examples/run_example.py       # building-level benchmark -> examples/output.json
# HTTP API for the dashboard (team contract output):
python -m uvicorn api:app --app-dir src --port 8000
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
- **Database**: [migrations/001_public.sql](migrations/001_public.sql) and
  [migrations/002_tenant.sql](migrations/002_tenant.sql) create `observation` and
  `tenant_membership`; tenant tables use row-level security driven by
  `SET LOCAL app.tenant_id` / `app.user_sub`, and fail closed when the context is unset.
- **CORS** is limited to `SPIP_ALLOWED_ORIGINS` and allows the `Authorization` header.

| Runtime setting | Purpose |
|---|---|
| `SPIP_AUTH_ENABLED` | `true` in deployments; `false` (default) keeps local development open |
| `SPIP_AUTH_ISSUER` / `SPIP_AUTH_CLIENT_ID` / `SPIP_AUTH_SCOPE` | Cognito pool, browser client, required scope |
| `SPIP_DEMO_TENANT` | Tenant used when auth is disabled locally |
| `SPIP_PUBLIC_DATABASE_URL` / `SPIP_TENANT_DATABASE_URL` | PostgreSQL sources; absent → local CSV |
| `SPIP_DATA` | CSV path for the local source (defaults to the public baseline) |
| `SPIP_CACHE_TTL_SECONDS` | Cache lifetime for a tenant's loaded records |
| `SPIP_ALLOWED_ORIGINS` | Allowed browser origins for CORS |

**Deliberately not implemented yet**: the asynchronous upload/job pipeline
(`POST /uploads`, `POST /jobs`, `GET /jobs/{id}`, worker, SQS). The synchronous
`POST /analyze` remains for local use only; it is not a production upload path.

## Interfaces

Public callable API and the inputs this engine needs from others:
[INTERFACES.md](INTERFACES.md).

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

- @Auxane / @Jin: (1) who writes`tenant_membership` after an invitation? (2) does the ECS task definition pass`SPIP_AUTH_ENABLED` ,`SPIP_AUTH_ISSUER` ,`SPIP_AUTH_CLIENT_ID` ? (3) who imports the baseline into`observation` , and are the migrations applied by the migration owner?