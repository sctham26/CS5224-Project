import json
from pathlib import Path

import pytest

from gap_analysis import run_gap_analysis

DATA = "data/synthetic_esg.csv"
METRICS = "config/metrics.yaml"
RULES = "config/peer_rules.yaml"


@pytest.fixture(scope="module")
def result():
    return run_gap_analysis(
        data_path=DATA, metrics_path=METRICS, peer_rules_path=RULES, entity_id="A001"
    )


def test_result_has_provenance(result):
    assert result["engine_version"]
    assert result["provenance"]["data_source"] == DATA
    assert result["provenance"]["min_peer_size"] == 5
    assert result["provenance"]["peer_rules"] == RULES


def test_asset_and_portfolio_not_mixed(result):
    assert result["scope"] == "asset"
    assert all("portfolio" not in json.dumps(m) for m in result["metrics"])


def test_energy_gap_computes_against_peers(result):
    entry = next(m for m in result["metrics"] if m["metric"] == "energy_intensity")
    assert entry["peer_count"] >= 5
    assert entry["applied_fallback_rule"]
    assert entry["value"] == pytest.approx(118.0)
    # lower_is_better: 118 < peer median 125 -> negative gap (already better)
    assert entry["gap_to_median"] < 0
    assert entry["unit"] == "kWh/m2/year"


def test_higher_is_better_gap_sign(result):
    entry = next(m for m in result["metrics"] if m["metric"] == "renewable_share")
    # renewable_share = 18%, median around 25% -> need +gap to reach median
    assert entry["gap_to_median"] > 0


def test_json_serialisable(result):
    assert json.dumps(result)


def test_output_contract_matches_example(result, tmp_path):
    out = tmp_path / "out.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert set(parsed) == {
        "engine_version",
        "entity_id",
        "scope",
        "reporting_period",
        "provenance",
        "summary",
        "metrics",
    }


def test_gap_summary_flags_performance_gap(result):
    # A001 renewable_share = 18% -> ~14th percentile (< 40 threshold) -> gap.
    assert "renewable_share" in result["summary"]["performance_gaps"]
    assert result["summary"]["disclosure_gaps"] == []


def test_performance_gap_entry_fields(result):
    entry = next(m for m in result["metrics"] if m["metric"] == "renewable_share")
    assert entry["percentile"] < entry["gap_percentile_threshold"]
    assert entry["gap_flag"] is True
    assert entry["gap_type"] == "performance_gap"
    assert entry["comparability_status"] == "comparable"


def test_no_gap_flag_when_above_threshold(result):
    entry = next(m for m in result["metrics"] if m["metric"] == "energy_intensity")
    assert entry["gap_flag"] is False
    assert entry["gap_type"] is None


def test_source_carried_into_output(result):
    entry = next(m for m in result["metrics"] if m["metric"] == "energy_intensity")
    assert entry["source"] == "synthetic-dataset"


def test_incomparable_metric_is_disclosure_gap():
    # A005 reported renewable_share in an unsupported unit -> not comparable.
    result = run_gap_analysis(
        data_path=DATA, metrics_path=METRICS, peer_rules_path=RULES, entity_id="A005"
    )
    entry = next(m for m in result["metrics"] if m["metric"] == "renewable_share")
    assert entry["status"] == "unavailable"
    assert entry["comparability_status"] == "incompatible"
    assert entry["reason"] == "incomparable_unit"
    assert entry["gap_type"] == "disclosure_gap"
    assert "renewable_share" in result["summary"]["disclosure_gaps"]


def test_undisclosed_metric_is_disclosure_gap():
    # A003 (2023) discloses only 3 of 5 declared metrics -> rest are not_disclosed.
    result = run_gap_analysis(
        data_path=DATA,
        metrics_path=METRICS,
        peer_rules_path=RULES,
        entity_id="A003",
        reporting_period="2023",
    )
    missing = [m for m in result["metrics"] if m["reason"] == "not_disclosed"]
    assert missing and all(m["gap_type"] == "disclosure_gap" for m in missing)
    assert all(m["comparability_status"] == "missing" for m in missing)
