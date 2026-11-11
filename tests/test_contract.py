import pytest

from contract import (
    ContractInputError,
    EntityNotFound,
    analyse_to_contract,
)

THEIR_CSV = "tests/fixtures_their.csv"
UNKNOWN_CSV = "tests/fixtures_unknown_metric.csv"
METRICS = "config/metrics.yaml"
RULES = "config/peer_rules.yaml"
ENGINE_CSV = "data/synthetic_esg.csv"

REQUIRED_TOP = {"entity_id", "entity_name", "tenant_id", "reporting_year", "peer_cohort", "metrics"}
REQUIRED_ITEM = {"metric_code", "standardised_value", "canonical_unit", "comparability_status"}
ALLOWED_STATUS = {"COMPARABLE", "UNIT_CONVERTED", "BOUNDARY_MISMATCH", "INCOMPLETE_DATA", "ANOMALY_FLAGGED"}
ALLOWED_GAP = {"PERFORMANCE_GAP", "DISCLOSURE_GAP", "NONE"}


def run(**kw):
    kw.setdefault("metrics_path", METRICS)
    kw.setdefault("peer_rules_path", RULES)
    return analyse_to_contract(**kw)


@pytest.fixture(scope="module")
def contract():
    return run(data_path=THEIR_CSV, entity_id="TGT_BUILD", reporting_year=2025)


def test_top_level_contract(contract):
    assert REQUIRED_TOP <= set(contract)
    assert contract["entity_id"] == "TGT_BUILD"
    assert contract["entity_name"] == "Target Tower"
    assert contract["tenant_id"] == "tenant_alpha"
    assert contract["reporting_year"] == 2025 and isinstance(contract["reporting_year"], int)


def test_metric_item_contract(contract):
    eui = next(m for m in contract["metrics"] if m["metric_code"] == "ENERGY_INTENSITY_EUI")
    assert REQUIRED_ITEM <= set(eui)
    assert eui["comparability_status"] in ALLOWED_STATUS
    assert eui["performance_direction"] == "LOWER_IS_BETTER"
    assert eui["canonical_unit"] == "kWh/m2/yr"
    # Target reported GJ -> engine converted -> 182.5 kWh/m2/yr
    assert eui["standardised_value"] == pytest.approx(182.5)
    assert eui["comparability_status"] == "UNIT_CONVERTED"


def test_peer_cohort_block(contract):
    cohort = contract["peer_cohort"]
    assert {"property_type", "region", "sample_size_n", "fallback_applied"} <= set(cohort)
    assert cohort["property_type"] == "OFFICE" and cohort["region"] == "SG"
    assert cohort["sample_size_n"] >= 5
    assert cohort["fallback_applied"] is False
    assert cohort["fallback_reason"] is None


def test_benchmark_and_gap_blocks(contract):
    eui = next(m for m in contract["metrics"] if m["metric_code"] == "ENERGY_INTENSITY_EUI")
    bench = eui["benchmark"]
    assert {"peer_median", "relative_rank", "empirical_percentile"} <= set(bench)
    assert bench["peer_median"] == pytest.approx(160.0)
    assert bench["relative_rank"] >= 1
    gap = eui["gap_analysis"]
    assert {"gap_type", "is_flagged"} <= set(gap)
    assert gap["gap_type"] in ALLOWED_GAP
    # 182.5 vs median 160, lower_is_better -> percentile 20 < 40 threshold
    assert gap["gap_type"] == "PERFORMANCE_GAP"
    assert gap["is_flagged"] is True
    assert gap["threshold_percentile"] == pytest.approx(40.0)
    assert gap["delta_to_peer_median"] == pytest.approx(22.5)
    assert isinstance(gap["recommendation_signal"], str)


def test_boundary_mismatch_status(contract):
    carbon = next(m for m in contract["metrics"] if m["metric_code"] == "CARBON_INTENSITY_SCOPE2")
    assert carbon["standardised_value"] is None
    assert carbon["comparability_status"] == "BOUNDARY_MISMATCH"
    assert carbon["gap_analysis"]["gap_type"] == "DISCLOSURE_GAP"
    assert carbon["benchmark"] is None


def test_undisclosed_metric_is_incomplete_data(contract):
    water = next(m for m in contract["metrics"] if m["metric_code"] == "WATER_INTENSITY")
    assert water["standardised_value"] is None
    assert water["comparability_status"] == "INCOMPLETE_DATA"
    assert water["gap_analysis"]["gap_type"] == "DISCLOSURE_GAP"
    # Non-benchmarkable disclosure gaps are flagged for action (contract semantics).
    assert water["gap_analysis"]["is_flagged"] is True


def test_engine_format_input_still_supported():
    out = run(data_path=ENGINE_CSV, entity_id="A001")
    assert REQUIRED_TOP <= set(out)
    assert out["reporting_year"] == 2024
    assert out["tenant_id"] == "PUBLIC"  # engine CSV carries no tenant metadata
    assert out["entity_name"] == "A001"
    eui = next(m for m in out["metrics"] if m["metric_code"] == "ENERGY_INTENSITY_EUI")
    assert eui["standardised_value"] == pytest.approx(118.0)


def test_unknown_metric_code_rejected():
    with pytest.raises(ContractInputError, match="BOGUS_METRIC"):
        run(data_path=UNKNOWN_CSV, entity_id="BAD_1")


def test_missing_entity_raises_not_found():
    with pytest.raises(EntityNotFound):
        run(data_path=THEIR_CSV, entity_id="NOPE")


def test_insufficient_peers_yields_null_gap(tmp_path):
    # Target + 2 peers < min 5: disclosed, benchmarked nowhere.
    import pandas as pd

    cols = [
        "tenant_id", "entity_id", "entity_name", "property_type", "region",
        "reporting_scope", "reporting_year", "metric_code",
        "standardised_value", "canonical_unit", "comparability_status",
    ]
    rows = []
    for i, eid in enumerate(["TGT", "P1", "P2"]):
        rows.append({
            "tenant_id": "tenant_alpha" if eid == "TGT" else "PUBLIC",
            "entity_id": eid,
            "entity_name": f"Entity {eid}",
            "property_type": "OFFICE",
            "region": "SG",
            "reporting_scope": "ASSET",
            "reporting_year": 2025,
            "metric_code": "ENERGY_INTENSITY_EUI",
            "standardised_value": 100.0 + i,
            "canonical_unit": "kWh/m2/yr",
            "comparability_status": "COMPARABLE",
        })
    path = tmp_path / "few_peers.csv"
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)

    out = run(data_path=str(path), entity_id="TGT", reporting_year=2025)
    eui = next(m for m in out["metrics"] if m["metric_code"] == "ENERGY_INTENSITY_EUI")
    assert eui["standardised_value"] is not None
    assert eui["benchmark"] is None
    # Not benchmarked: neither "no gap" nor a flagged gap.
    assert eui["gap_analysis"]["gap_type"] is None
    assert eui["gap_analysis"]["is_flagged"] is None
