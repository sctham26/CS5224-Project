from pathlib import Path

import pytest

from harmonisation import (
    HarmonisedMetric,
    HarmonisedRecord,
    harmonise_records,
    load_records,
    partition_by_scope,
)
from metrics import MetricRegistry
from peers import PeerGroup, PeerSelector, load_peer_rules
from schemas import MetricDirection, ReportingScope

RULES = "config/peer_rules.yaml"
EUI = "ENERGY_INTENSITY_EUI"


@pytest.fixture(scope="module")
def selector():
    return PeerSelector(load_peer_rules(RULES))


@pytest.fixture(scope="module")
def assets(selector):
    registry = MetricRegistry.from_yaml("config/metrics.yaml")
    records = load_records("data/synthetic_esg.csv")
    return harmonise_records(
        partition_by_scope(records, ReportingScope.ASSET), registry
    )


def test_config_loads_min_size():
    rules = load_peer_rules(RULES)
    assert rules.min_peer_size == 5
    # Team contract (PR #1): region is relaxed first.
    assert rules.fallback_rules[0].name == "same_property_type_and_region"
    assert rules.fallback_rules[1].name == "same_region"


def test_peer_group_excludes_target_and_meets_min_size(selector, assets):
    target = next(r for r in assets if r.entity_id == "A001")
    group = selector.select(target, assets, EUI)
    assert target.entity_id not in group.peer_ids
    assert len(group.peer_ids) >= 5
    assert group.applied_rule == "same_property_type_and_region"
    assert group.compatibility == {
        "scope": "asset",
        "reporting_period": "2024",
        "unit": "kWh/m2/yr",
    }


def test_fallback_widens_when_strict_rule_too_small(selector, assets):
    # A007 is UK/retail — too few same-type peers, must fall back.
    target = next(r for r in assets if r.entity_id == "A007")
    group = selector.select(target, assets, EUI)
    assert group.applied_rule in {"same_region", "same_property_type", "same_scope_all"}
    assert len(group.peer_ids) >= 5


def test_metric_availability_filters_peers(selector, assets):
    # A005's renewable_share was dropped (unsupported unit) — cannot be a peer.
    target = next(r for r in assets if r.entity_id == "A001")
    group = selector.select(target, assets, "RENEWABLE_SHARE")
    assert "A005" not in group.peer_ids
    # UK office peers with valid renewable data = 4 < 5 → region relaxed first.
    assert group.applied_rule in {"same_region", "same_property_type", "same_scope_all"}


def test_insufficient_peers_reported(selector):
    registry = MetricRegistry.from_yaml("config/metrics.yaml")
    records = load_records("data/synthetic_esg.csv")
    portfolios = harmonise_records(
        partition_by_scope(records, ReportingScope.PORTFOLIO), registry
    )
    rules = load_peer_rules(RULES)
    sel = PeerSelector(rules)
    target = next(r for r in portfolios if r.entity_id == "P001")
    group = sel.select(target, portfolios, "RENEWABLE_SHARE")
    assert list(group.peer_ids) == []
    assert group.unavailable_reason == "insufficient_peers"


def test_selection_is_deterministic(selector, assets):
    target = next(r for r in assets if r.entity_id == "A007")
    g1 = selector.select(target, assets, EUI)
    g2 = selector.select(target, assets, EUI)
    assert g1.peer_ids == g2.peer_ids


def _rec(eid: str, period: str, ptype: str, region: str) -> HarmonisedRecord:
    return HarmonisedRecord(
        entity_id=eid,
        scope=ReportingScope.ASSET,
        reporting_period=period,
        region=region,
        property_type=ptype,
        certification=None,
        metrics={
            EUI: HarmonisedMetric(
                value=100.0,
                canonical_unit="kWh/m2/yr",
                direction=MetricDirection.LOWER_IS_BETTER,
                source_unit="kWh/m2/yr",
                conversion_factor=1.0,
            )
        },
        dropped={},
    )


def _target(selector, candidates):
    # target: asset / OFFICE / UK / 2024; never counted as its own peer.
    target = _rec("TGT", "2024", "OFFICE", "UK")
    return target, selector.select(target, candidates, EUI)


def test_other_years_never_rescue_small_cohort(selector):
    # Same type/region has only 3 peers in 2024; 10 exist in 2023.
    # Reporting-period compatibility is strict: 2023 data must not be borrowed.
    candidates = [_rec(f"E{i}", "2024", "OFFICE", "UK") for i in range(3)]
    candidates += [_rec(f"Y{i}", "2023", "OFFICE", "UK") for i in range(10)]
    target, group = _target(selector, candidates)
    assert group.unavailable_reason == "insufficient_peers"
    assert group.peer_ids == ()
    assert group.compatibility["reporting_period"] == "2024"


def test_region_relaxes_before_property_type(selector):
    # 4 same type+region (<5) but 10 in region -> same_region wins over type-only.
    candidates = [_rec(f"A{i}", "2024", "OFFICE", "UK") for i in range(4)]
    candidates += [_rec(f"B{i}", "2024", "RETAIL", "UK") for i in range(6)]
    _, group = _target(selector, candidates)
    assert group.applied_rule == "same_region"
    assert len(group.peer_ids) == 10


def test_property_type_rule_when_region_too_small(selector):
    # region cohort 4 <5 (loses to rule 2), type cohort across regions 5 -> rule 3.
    candidates = [_rec(f"A{i}", "2024", "OFFICE", "UK") for i in range(3)]
    candidates += [_rec("X0", "2024", "OFFICE", "US"), _rec("X1", "2024", "OFFICE", "US")]
    candidates += [_rec("B0", "2024", "RETAIL", "UK")]
    _, group = _target(selector, candidates)
    assert group.applied_rule == "same_property_type"
    assert len(group.peer_ids) == 5
