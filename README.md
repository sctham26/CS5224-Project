# SPIP ESG Analytics Engine

Standalone, production-oriented Python engine for ESG harmonisation, rule-based peer
selection, empirical percentile benchmarking and gap analysis. No AWS, database,
frontend or AI-service dependencies.

## Install & Run

```powershell
pip install -r requirements.txt
python -m pytest -q                  # 58 tests (src/ resolved via pytest pythonpath)
python examples/run_example.py       # writes examples/output.json
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
| HTTP API | [api.py](src/api.py) | FastAPI `GET /analysis/{id}`, `POST /analyze`, CORS |

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
- **Determinism**: peer IDs are sorted; percentile uses target-inclusive ranks.
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
   team decision — see assumption 5 below.
2. **Peer-group fallback policy.** Specified in
   [config/peer_rules.yaml](config/peer_rules.yaml): minimum peer-group size is **5**
   (excluding the target). The relaxation order follows the team's output contract
   (PR #1): `property_type+region → region → property_type → all in scope` — region is
   relaxed first. If no rule meets the minimum the benchmark is `unavailable`.

**Naming/unit baseline**: metric codes, canonical units and direction now follow the
team's `docs/metric_dictionary.csv` (PR #1), e.g. `ENERGY_INTENSITY_EUI` / `kWh/m2/yr`.

## Assumptions requiring confirmation with real ESG datasets

1. ~~Metric list and canonical units are placeholders~~ — now aligned to the team's
   metric dictionary (PR #1); pending merge confirmation.
2. ~~Fallback order needs review~~ — aligned to the team's contract
   (`type+region → region → type → all`, region first).
3. Reporting-period compatibility is exact-string matching (`"2024"`); team CSV uses
   `reporting_year` (int) mapped to the same matcher. Confirm partial-period overlap.
4. Real team datasets (`public_esg_baseline.csv` etc.) not yet wired in; the adapter
   accepts their format, tests use fixtures in `tests/`.
5. Certification is loaded but not yet used in peer selection — confirm whether it is a
   peer dimension.
6. Dashboard/API: HTTP layer exists (`src/api.py`); the React dashboard still reads
   hardcoded data — wire it to `GET /analysis/{entity_id}`.
7. `gap_percentile_threshold: 40` per metric is a placeholder — confirm the agreed gap
   threshold (and whether it differs by metric or portfolio).
8. `source` provenance is a free-text field — confirm the required granularity
   (report/page/dataset) for the common schema.
