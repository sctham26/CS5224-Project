# Interfaces

Two contracts:
1. **Outbound** — what this engine exposes for callers.
2. **Inbound** — what the engine needs supplied to it.

All paths are relative to `spip-analytics/`.

---

## 1. Outbound (callers)

### 1a. HTTP API (for the React dashboard)

```powershell
python -m uvicorn api:app --app-dir src --port 8000
```

All protected routes require `Authorization: Bearer <Cognito access token>`; the
verified `sub` resolves to one active tenant, and every read returns only the public
baseline plus that tenant's own rows.

| Method & path | Params | Purpose |
|---|---|---|
| `GET /health` | — | Liveness probe; unprotected (ALB) |
| `GET /entities` | optional `scope=asset\|portfolio` | Discovery: entities visible to this tenant with the reporting years present in the data |
| `GET /analysis/{entity_id}` | `scope=asset\|portfolio`, `reporting_year` | Serve `data/cleaned/public_esg_baseline.csv` (or `SPIP_DATA`), or PostgreSQL when `SPIP_PUBLIC_DATABASE_URL` is set |
| `POST /uploads` | — | Presigned `PUT` for `tenants/<tenant>/uploads/<uuid>.csv`; `201` with `upload_url`, `method`, `key`, `expires_in` |
| `POST /jobs` | `Idempotency-Key` header + `{upload_key, entity_id, reporting_year?, scope?}` | `202` with `job_id`, `status`, `status_url`; identical retry replays the same job (`Idempotent-Replay: true`) |
| `GET /jobs/{job_id}` | — | Ownership-checked state, `result` when `SUCCEEDED`, `error` when `FAILED` |
| `POST /analyze` | multipart `file`, `entity_id`, `reporting_year`, `scope` | Local synchronous upload (unique temp file); not a production upload path |

Errors: `401` missing/invalid/expired token, `403` valid account without tenant
membership, `404` entity / upload key / job not visible to this tenant, `409`
idempotency key reused with a different request, `422` bad scope / unknown `metric_code` /
missing `entity_id` / invalid job envelope, `503` upload pipeline not configured. CORS is
restricted to `SPIP_ALLOWED_ORIGINS` and allows `Authorization`, `Content-Type` and
`Idempotency-Key`. `/health` is never prefixed; set `SPIP_API_PREFIX=/api` only if the
gateway keeps the browser-facing segment instead of stripping it. Response body always matches
`schemas/analytics_output_contract.json` (PR #1): `entity_id`, `entity_name`,
`tenant_id`, `reporting_year` (int), `peer_cohort{property_type, region, sample_size_n,
fallback_applied, fallback_reason}`, `metrics[]` with `comparability_status` ∈
`COMPARABLE / UNIT_CONVERTED / BOUNDARY_MISMATCH / INCOMPLETE_DATA`, `benchmark{peer_median,
relative_rank, empirical_percentile}`, `gap_analysis{gap_type, is_flagged,
threshold_percentile, delta_to_peer_median?, recommendation_signal}`.

### 1b. `analyse_to_contract(...)` (same output, as a library)

```python
from contract import analyse_to_contract   # src/ must be on sys.path

out = analyse_to_contract(
    data_path="tests/fixtures_their.csv",   # team CSV (metric_code/...) or engine CSV
    entity_id="TGT_BUILD",
    metrics_path="config/metrics.yaml",
    peer_rules_path="config/peer_rules.yaml",
    reporting_year=2025,                    # optional; int or str
    scope="asset",                          # asset (default) | portfolio
)
```

Raises `ContractInputError` (unknown `metric_code`) and `EntityNotFound` (no such
entity/period/scope). Pure boundary adapter — it delegates to `run_gap_analysis` and
projects the result onto the team's contract.

### 1c. `run_gap_analysis(...)` (engine-internal contract)

End-to-end: load CSV → partition by scope → harmonise units → select peers → percentile
benchmark → return JSON.

```python
from gap_analysis import run_gap_analysis   # src/ must be on sys.path

result: dict = run_gap_analysis(
    data_path="data/synthetic_esg.csv",        # required: long-format ESG CSV
    metrics_path="config/metrics.yaml",        # required: metric dictionary
    peer_rules_path="config/peer_rules.yaml",  # required: peer fallback rules
    entity_id="A001",                          # required: target entity
    reporting_period="2024",                   # optional; defaults to the latest period
    scope=ReportingScope.ASSET,                # optional: asset (default) | portfolio
)
```

| Param | Type | Required | Notes |
|---|---|---|---|
| `data_path` | `str \| Path` | yes | Long-format CSV, see §2.1 |
| `metrics_path` | `str \| Path` | yes | YAML, see §2.2 |
| `peer_rules_path` | `str \| Path` | yes | YAML, see §2.3 |
| `entity_id` | `str` | yes | Target entity ID |
| `reporting_period` | `str \| None` | no | Omitted = entity's latest period analysed |
| `scope` | `ReportingScope` | no | `ASSET` (default) or `PORTFOLIO` |

Raises `ValueError` if the entity is absent from that scope.

**Return contract:**

```jsonc
{
  "engine_version": "0.1.0",
  "entity_id": "A001",
  "scope": "asset",
  "reporting_period": "2024",
  "provenance": {              // reproducibility
    "data_source": "...", "metrics_config": "...", "peer_rules": "...",
    "min_peer_size": 5, "fallback_rules": ["same_property_type_and_region", "..."],
    "gap_percentile_threshold_source": "config/metrics.yaml"
  },
  "summary": {
    "performance_gaps": ["RENEWABLE_SHARE"],     // comparable metric below threshold
    "disclosure_gaps":  ["WATER_INTENSITY"]      // not disclosed / incomparable
  },
  "metrics": [ /* one object per metric, one of three shapes below */ ]
}
```

`metrics[]` shapes:

| Shape | Discriminator | Key fields |
|---|---|---|
| **Comparable** | `status: "available"` | `value`, `unit`, `source_unit`, `conversion_factor`, `source`, `direction`, `peer_count`, `applied_fallback_rule`, `peer_ids`, `benchmark{count,median,mean,min,max}`, `rank`, `percentile`, `gap_percentile_threshold`, `gap_to_median`, `gap_flag`, `gap_type` |
| **Not disclosed / incomparable** | `status: "unavailable"` + `reason: "not_disclosed" \| "incomparable_unit"` | `comparability_status` (`missing`/`incompatible`), `gap_type: "disclosure_gap"`, `gap_flag: null` |
| **Insufficient peers** | `status: "unavailable"` + `reason: "insufficient_peers"` | `gap_type: null`, `gap_flag: null`, `peer_count` |

Semantics:
- `gap_to_median > 0` = improvement needed to reach median; `<= 0` = at or better.
- `percentile` is direction-aware, **100 = best**; `gap_flag = percentile < gap_percentile_threshold`.
- Every comparable entry carries `compatibility{scope, reporting_period, unit}`.

### Stage-level API (for standalone reuse)

| Module | Function / class | Purpose |
|---|---|---|
| `harmonisation` | `load_records(path)` | CSV → `list[ESGRecord]` |
| | `partition_by_scope(records, scope)` | Split by scope |
| | `harmonise_records(records, registry)` | → `list[HarmonisedRecord]` (canonical units) |
| `metrics` | `MetricRegistry.from_yaml(path)` | Load metric dictionary |
| | `registry.spec(name)` / `registry.convert(name, value, unit)` | Spec / unit conversion; raises `UnknownMetricError`, `IncompatibleUnitError` |
| `peers` | `load_peer_rules(path)` → `PeerRules` | Load rules |
| | `PeerSelector(rules).select(target, candidates, metric)` → `PeerGroup` | Select peers; non-empty `unavailable_reason` means benchmark unavailable |
| `benchmark` | `summarize(values)` / `rank_in_group(...)` / `empirical_percentile(...)` | Stats / rank / percentile |
| `schemas` | `ReportingScope`, `MetricDirection`, `ComparabilityStatus`, `MetricObservation`, `ESGRecord` | Enums and Pydantic models |

---

## 2. Inbound (inputs others must provide)

### 2.1 Data: long-format ESG CSV (one row = entity/period/metric)

Two accepted inputs — **their format** (auto-detected when `metric_code`,
`reporting_year`, `standardised_value`, `reporting_scope` columns all exist) is
converted internally to the engine format below:

| Their column (team CSV) | Maps to engine column | Notes |
|---|---|---|
| `entity_id` | `entity_id` | |
| `reporting_scope` (`ASSET`/`PORTFOLIO`) | `scope` (lowercased) | |
| `reporting_year` (int) | `reporting_period` (str) | exact match, `"2025"` |
| `metric_code` | `metric` | must be in `metrics.yaml`, else `422` |
| `standardised_value` + `canonical_unit` | `value` + `unit` | already converted upstream |
| `comparability_status` | — | `BOUNDARY_MISMATCH`/`ANOMALY_FLAGGED`/null value → excluded (reported as disclosure gap); `UNIT_CONVERTED` → status `UNIT_CONVERTED` |
| `property_type`, `region`, `entity_name`, `tenant_id`, `source_reference` | + carry-over | drive `peer_cohort` / identity fields |

Engine format (also accepted directly):

| Column | Required | Type | Notes |
|---|---|---|---|
| `entity_id` | yes | str | Unique entity ID |
| `scope` | yes | `asset` \| `portfolio` | Reporting granularity; never mixed |
| `reporting_period` | yes | str | **Exact string match** (e.g. `"2024"`) |
| `region` | yes* | str | Peer dimension; may be empty |
| `property_type` | yes* | str | Peer dimension; may be empty |
| `certification` | yes* | str | Loaded but not yet a peer dimension |
| `metric` | yes | str | Must match a metric name in `metrics.yaml` |
| `value` | yes | float | ≥ 0 |
| `unit` | yes | str | Must be declared in that metric's `factors` |
| `source` | no | str | Provenance (report / dataset / curation) |

*Column must exist; cell value may be empty. See `data/synthetic_esg.csv`.

### 2.2 Config: `config/metrics.yaml` — metric dictionary

**Business must supply**: metric names, canonical units, direction, applicable scopes,
accepted units and conversion factors, gap threshold.

```yaml
metrics:
  ENERGY_INTENSITY_EUI:
    canonical_unit: kWh/m2/yr
    direction: lower_is_better        # lower_is_better | higher_is_better
    scopes: [asset, portfolio]
    gap_percentile_threshold: 40      # below this percentile -> performance_gap
    factors:                          # multiplier: reported unit -> canonical
      kWh/m2/yr: 1.0
      MWh/m2/yr: 1000.0
```

Metric codes follow the team's `docs/metric_dictionary.csv` (PR #1): nine declared
metrics (`ENERGY_INTENSITY_EUI`, `CARBON_INTENSITY_SCOPE2`, `WATER_INTENSITY`,
`GREEN_CERT_LEVEL`, `SCOPE_1_EMISSIONS`, `SCOPE_2_EMISSIONS`,
`CARBON_INTENSITY_SCOPE1_2`, `ENERGY_INTENSITY_REPORTED_TOTAL`,
`TOTAL_ENERGY_INTENSITY`) plus `WASTE_DIVERSION_RATE` / `RENEWABLE_SHARE` from the
synthetic dataset. An unknown code in an uploaded CSV → `422 ContractInputError`.

### 2.3 Config: `config/peer_rules.yaml` — peer rules

**Business must confirm**: minimum peer-group size and fallback relaxation order
(first rule to meet the minimum wins, top to bottom).

```yaml
min_peer_size: 5                      # excluding the target itself
fallback_rules:                       # top to bottom; region relaxed first (team PR #1)
  - name: same_property_type_and_region
    match: [property_type, region]    # fields: property_type / region / certification
  - name: same_region
    match: [region]
  - name: same_property_type
    match: [property_type]
  - name: same_scope_all
    match: []                         # fallback: all in scope
```

### 2.4 Compatibility prerequisites (auto-enforced)

A peer candidate must **simultaneously** match the target on: scope, `reporting_period`,
metric availability, and unit convertible to canonical. Otherwise it is excluded.

---

## 3. Integration boundary

- HTTP layer: `src/api.py` (FastAPI) — the only process a caller runs; CORS open for
  the Vite dashboard (`GET /analysis/{entity_id}`).
- Library layer: `analyse_to_contract` (team contract) or `run_gap_analysis` (engine
  contract, richer provenance).
- Integration artefacts: team-shaped response from the API; contract example in
  `examples/output.json` (generated from the public baseline).
- Not integrated: the React dashboard still on hardcoded data, AI assistant.
