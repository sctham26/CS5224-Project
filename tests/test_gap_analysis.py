import json
from pathlib import Path

import pytest

from gap_analysis import run_gap_analysis

DATA = "data/synthetic_esg.csv"
METRICS = "config/metrics.yaml"
RULES = "config/peer_rules.yaml"
EUI = "ENERGY_INTENSITY_EUI"
RENEW = "RENEWABLE_SHARE"


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
    entry = next(m for m in result["metrics"] if m["metric"] == EUI)
    assert entry["peer_count"] >= 5
    assert entry["applied_fallback_rule"]
    assert entry["value"] == pytest.approx(118.0)
    # lower_is_better: 118 < peer median -> negative gap (already better)
    assert entry["gap_to_median"] < 0
    assert entry["unit"] == "kWh/m2/yr"


def test_higher_is_better_gap_sign():
    # A007 renewable_share = 5%, peer median = 18% -> needs +13 to reach median.
    result = run_gap_analysis(
        data_path=DATA, metrics_path=METRICS, peer_rules_path=RULES, entity_id="A007"
    )
    entry = next(m for m in result["metrics"] if m["metric"] == RENEW)
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


def test_gap_summary_flags_performance_gap():
    # A007 underperforms peers on renewable_share (14th percentile < 40 threshold).
    result = run_gap_analysis(
        data_path=DATA, metrics_path=METRICS, peer_rules_path=RULES, entity_id="A007"
    )
    assert RENEW in result["summary"]["performance_gaps"]
    # The dictionary declares more metrics than A007 discloses -> disclosure gaps.
    assert all(
        g in result["summary"]["disclosure_gaps"] for g in ("SCOPE_1_EMISSIONS", "GREEN_CERT_LEVEL")
    )


def test_performance_gap_entry_fields():
    result = run_gap_analysis(
        data_path=DATA, metrics_path=METRICS, peer_rules_path=RULES, entity_id="A007"
    )
    entry = next(m for m in result["metrics"] if m["metric"] == RENEW)
    assert entry["percentile"] < entry["gap_percentile_threshold"]
    assert entry["gap_flag"] is True
    assert entry["gap_type"] == "performance_gap"
    assert entry["comparability_status"] == "comparable"


def test_no_gap_flag_when_above_threshold(result):
    entry = next(m for m in result["metrics"] if m["metric"] == EUI)
    assert entry["gap_flag"] is False
    assert entry["gap_type"] is None


def test_source_carried_into_output(result):
    entry = next(m for m in result["metrics"] if m["metric"] == EUI)
    assert entry["source"] == "synthetic-dataset"


def test_incomparable_metric_is_disclosure_gap():
    # A005 reported renewable_share in an unsupported unit -> not comparable.
    result = run_gap_analysis(
        data_path=DATA, metrics_path=METRICS, peer_rules_path=RULES, entity_id="A005"
    )
    entry = next(m for m in result["metrics"] if m["metric"] == RENEW)
    assert entry["status"] == "unavailable"
    assert entry["comparability_status"] == "incompatible"
    assert entry["reason"] == "incomparable_unit"
    assert entry["gap_type"] == "disclosure_gap"
    assert RENEW in result["summary"]["disclosure_gaps"]


def test_undisclosed_metric_is_disclosure_gap():
    # A003 (2023) discloses only a subset of declared metrics -> rest not_disclosed.
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
