# Interfaces

Two contracts:
1. **Outbound** — what this engine exposes for callers.
2. **Inbound** — what the engine needs supplied to it.

All paths are relative to `spip-analytics/`.

---

## 1. Outbound (callers)

### `run_gap_analysis(...)`

End-to-end: load CSV → partition by scope → harmonise units → select peers → percentile
benchmark → return JSON.

```python
from gap_analysis import run_gap_analysis   # src/ must be on sys.path

result: dict = run_gap_analysis(
    data_path="data/synthetic_esg.csv",        # required: long-format ESG CSV
    metrics_path="config/metrics.yaml",        # required: metric dictionary
    peer_rules_path="config/peer_rules.yaml",  # required: peer fallback rules
    entity_id="A001",                          # required: target entity
    reporting_period="2024",                   # optional: defaults to first record
    scope=ReportingScope.ASSET,                # optional: asset (default) | portfolio
)
```

| Param | Type | Required | Notes |
|---|---|---|---|
| `data_path` | `str \| Path` | yes | Long-format CSV, see §2.1 |
| `metrics_path` | `str \| Path` | yes | YAML, see §2.2 |
| `peer_rules_path` | `str \| Path` | yes | YAML, see §2.3 |
| `entity_id` | `str` | yes | Target entity ID |
| `reporting_period` | `str \| None` | no | Required when an entity has multiple periods |
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
    "performance_gaps": ["renewable_share"],   // comparable metric below threshold
    "disclosure_gaps":  ["water_intensity"]    // not disclosed / incomparable
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
  energy_intensity:
    canonical_unit: kWh/m2/year
    direction: lower_is_better        # lower_is_better | higher_is_better
    scopes: [asset, portfolio]
    gap_percentile_threshold: 40      # below this percentile -> performance_gap
    factors:                          # multiplier: reported unit -> canonical
      kWh/m2/year: 1.0
      MWh/m2/year: 1000.0
```

### 2.3 Config: `config/peer_rules.yaml` — peer rules

**Business must confirm**: minimum peer-group size and fallback relaxation order
(first rule to meet the minimum wins, top to bottom).

```yaml
min_peer_size: 5                      # excluding the target itself
fallback_rules:
  - name: same_property_type_and_region
    match: [property_type, region]    # fields: property_type / region / certification
  - name: same_property_type
    match: [property_type]
  - name: same_region
    match: [region]
  - name: same_scope_all
    match: []                         # fallback: all in scope
```

### 2.4 Compatibility prerequisites (auto-enforced)

A peer candidate must **simultaneously** match the target on: scope, `reporting_period`,
metric availability, and unit convertible to canonical. Otherwise it is excluded.

---

## 3. Integration boundary

- Pure library, no HTTP/CLI service; callers import `run_gap_analysis` directly.
- Integration artefact is the JSON contract in §1 (example: `examples/output.json`).
- Not integrated: real benchmark data, dashboard/API, AI assistant.
