SPIP — Backend Section (Architecture, Evaluation, Code)

Version 0.6.3 · 2026-11-07 · Backend-owned parts of the Final report. 

1. Architecture and implementation

The service answers one question: how does this building compare with comparable buildings, and where should its owner act? For every disclosed metric it returns the peer median, the target's rank and empirical percentile, and a gap class — performance gap when a comparable value sits below the threshold, disclosure gap when the value is simply not reported. Lower-is-better metrics are reversed so 100 always means best.

The engine runs on real building-level data: 12,767 observations, 1,561 buildings, 2017–2020 and 2022–2025. 2021 is absent from the source and left absent rather than interpolated. Harmonisation splits asset from portfolio scope, converts only compatible units and refuses the rest — 196 combined-metering, 190 special-use, 6 anomaly-flagged, 2 boundary-mismatch and 316 incomplete rows never reach a benchmark — leaving 6,187 comparable and 5,870 unit-converted observations.

Peer selection is deterministic: at least five peers, target excluded, relaxed along a fixed ladder from property type plus region to the full pool, with scope, period, metric availability and canonical unit held fixed at every step. The cohort actually used is reported, so every benchmark is traceable. Percentiles include the target in the denominator and are normalised by n−1, which stops small groups from inflating scores.

The analytical core imports no AWS SDK, database driver or web framework, so it is testable in isolation; identity, storage and HTTP sit in a boundary layer. Cognito access tokens are verified against JWKS with an exact issuer match, and the tenant is derived server-side from the sub claim through tenant_membership — never from a request body or header. Foreign-tenant entities are filtered before analysis, so the API returns 404 rather than 403; PostgreSQL row-level security fails closed when the tenant context is unset.

Ingestion is asynchronous: `POST /uploads` issues a short-lived presigned S3 PUT, `POST /jobs` is idempotent on tenant plus request hash, and the worker advances a monotonic PENDING → QUEUED → RUNNING → SUCCEEDED | FAILED machine. The worker merges the upload with the caller's stored view — public baseline plus that tenant's rows — so a single uploaded building is benchmarked against a real cohort, not against itself. Results are written before the terminal state and the queue is acknowledged only after that write is durable, so redelivery cannot re-run completed work.

Scale is deferred, not ignored. Today: one API service, one worker, one queue:

| Component | Trigger | Lever | Cost |
|---|---|---|---|
| API | p95 latency, 5xx rate | more ECS tasks (stateless) | DB connections saturate before CPU |
| Worker | queue depth, job latency | more tasks, batch polling | bills by throughput |
| Data source | rows, tenants, p95 | peer selection in SQL, per-cohort precompute | storage vs freshness |
| Cache | hit rate falls with instances | shared tier | one more service |

The first real ceiling is `PostgresDataSource`, which reads the whole baseline plus tenant rows into memory on every cache expiry — irrelevant at 12,767 rows, first to change at millions. Computed reports are cached in-process (LRU plus TTL, keyed on frame identity, tenant, scope, entity, year): 0.003 ms on a hit against 760 ms to recompute.

2. Evaluation

The strongest evidence is a contract bug found and fixed. A too-small peer group used to be reported as "NONE" with the flag cleared, telling the frontend a building was fine when it had never been compared. It now returns null across benchmark, gap type and flag — and that behaviour was reproduced on the live pipeline, not just in tests.

- 157 of 157 pytest cases across 17 files pass locally; `scripts/verify_contract.py` passes 12 of 12 contract checks.
- Live: `/api/health` 200 and business routes 401 without a token. With a real Cognito token on 2026-10-30, a three-entity CSV below the minimum cohort ran end to end and returned null with `fallback_reason: insufficient_peers`, while undisclosed metrics came back as disclosure gaps.
- Real-data check: uploading only `SG_228218_LATEST_6` for 2024 yields cohort 239, median EUI 138.746, percentile 60.25, gap NONE.
- The manual correctness workbook (`evaluation/correctness_SG.xlsx`) is committed and recomputes the same quantities by hand. Page-level browser end-to-end testing is still absent, so no claim of a full user-flow evaluation is made here.

3. Assumptions and future work

One standardised format is accepted (nine required of twenty columns); customer exports reach it through a browser-side column mapper with human confirmation, not automatically. The 40th-percentile threshold is a placeholder; certification is loaded but not a peer criterion; period matching is exact. Uploaded rows are not written back — that path exists behind a flag but needs a database grant the deployment does not issue.

Next: unit inference with a proposed conversion, unmapped-metric reporting, and a shared cache tier. Automated collection of public data was evaluated and dropped: the BCA source was last updated in June 2024 and our baseline already covers 2025.

4. Code explanation

Repository: `spip-analytics/` (public URL to be added by the team). Core modules are flat files in `src/`: schemas, metrics, harmonisation, peers, benchmark, gap_analysis, plus the boundary modules contract, auth, datastore, jobs, worker, api, import_baseline. Config in `config/`, migrations in `migrations/001`–`004`, tests in `tests/`, baseline CSV in `data/cleaned/`.

```powershell
pip install -r requirements.txt
python -m pytest -q                 # 157 tests
python -m uvicorn api:app --app-dir src --port 8000
```

5. AI use

AI drafted modules, tests and this section; output was accepted only after verification against a test, a live response or a line of source. The analytical rules are configuration, not AI. The lesson: AI-generated work fails on edge cases and plausible prose, and the fix is measurement, not rewording. 
