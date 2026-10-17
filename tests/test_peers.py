from pathlib import Path

import pytest

from harmonisation import (
    harmonise_records,
    load_records,
    partition_by_scope,
)
from metrics import MetricRegistry
from peers import PeerGroup, PeerSelector, load_peer_rules
from schemas import ReportingScope

RULES = "config/peer_rules.yaml"


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
    assert rules.fallback_rules[0].name == "same_property_type_and_region"


def test_peer_group_excludes_target_and_meets_min_size(selector, assets):
    target = next(r for r in assets if r.entity_id == "A001")
    group = selector.select(target, assets, "energy_intensity")
    assert target.entity_id not in group.peer_ids
    assert len(group.peer_ids) >= 5
    assert group.applied_rule == "same_property_type_and_region"
    assert group.compatibility == {
        "scope": "asset",
        "reporting_period": "2024",
        "unit": "kWh/m2/year",
    }


def test_fallback_widens_when_strict_rule_too_small(selector, assets):
    # A007 is UK/retail — only 2 same-type peers, must fall back to region.
    target = next(r for r in assets if r.entity_id == "A007")
    group = selector.select(target, assets, "energy_intensity")
    assert group.applied_rule == "same_region"
    assert len(group.peer_ids) >= 5


def test_metric_availability_filters_peers(selector, assets):
    # A005's renewable_share was dropped (unsupported unit) — cannot be a peer.
    target = next(r for r in assets if r.entity_id == "A001")
    group = selector.select(target, assets, "renewable_share")
    assert "A005" not in group.peer_ids
    # UK office peers with valid data = 4 < 5, falls back to same_property_type.
    assert group.applied_rule == "same_property_type"


def test_insufficient_peers_reported(selector):
    registry = MetricRegistry.from_yaml("config/metrics.yaml")
    records = load_records("data/synthetic_esg.csv")
    portfolios = harmonise_records(
        partition_by_scope(records, ReportingScope.PORTFOLIO), registry
    )
    rules = load_peer_rules(RULES)
    sel = PeerSelector(rules)
    target = next(r for r in portfolios if r.entity_id == "P001")
    group = sel.select(target, portfolios, "renewable_share")
    assert list(group.peer_ids) == []
    assert group.unavailable_reason == "insufficient_peers"


def test_selection_is_deterministic(selector, assets):
    target = next(r for r in assets if r.entity_id == "A007")
    g1 = selector.select(target, assets, "energy_intensity")
    g2 = selector.select(target, assets, "energy_intensity")
    assert g1.peer_ids == g2.peer_ids
