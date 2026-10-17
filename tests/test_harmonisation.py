import pytest

from harmonisation import (
    harmonise_records,
    load_records,
    partition_by_scope,
)
from metrics import MetricRegistry
from schemas import ReportingScope

DATA = "data/synthetic_esg.csv"
EUI = "ENERGY_INTENSITY_EUI"
CARBON = "CARBON_INTENSITY_SCOPE2"
RENEW = "RENEWABLE_SHARE"
WASTE = "WASTE_DIVERSION_RATE"


@pytest.fixture(scope="module")
def registry():
    return MetricRegistry.from_yaml("config/metrics.yaml")


@pytest.fixture(scope="module")
def records():
    return load_records(DATA)


def test_load_records_parses_long_format(records):
    assert len(records) == 18
    ids = {r.entity_id for r in records}
    assert {"A001", "P001"} <= ids


def test_load_records_is_deterministic():
    assert [r.model_dump() for r in load_records(DATA)] == [
        r.model_dump() for r in load_records(DATA)
    ]


def test_partition_by_scope_never_mixes(records):
    assets = partition_by_scope(records, ReportingScope.ASSET)
    portfolios = partition_by_scope(records, ReportingScope.PORTFOLIO)
    assert all(r.scope == ReportingScope.ASSET for r in assets)
    assert all(r.scope == ReportingScope.PORTFOLIO for r in portfolios)
    assert len(assets) + len(portfolios) == len(records)


def test_harmonisation_converts_mixed_units(records, registry):
    h = harmonise_records(records, registry)
    a001 = next(r for r in h if r.entity_id == "A001")
    a004 = next(r for r in h if r.entity_id == "A004" and r.reporting_period == "2024")
    # A004 reported energy in MWh -> 0.125 * 1000 = 125 kWh
    assert a004.metrics[EUI].value == pytest.approx(125.0)
    assert a004.metrics[EUI].source_unit == "MWh/m2/year"
    assert a004.metrics[EUI].conversion_factor == pytest.approx(1000.0)
    # A004 emissions in tonnes -> kg
    assert a004.metrics[CARBON].value == pytest.approx(24.5)
    # A001 reported fraction waste -> percent
    assert a001.metrics[WASTE].value == pytest.approx(62.0)


def test_harmonisation_records_unsupported_unit(registry):
    h = harmonise_records(load_records(DATA), registry)
    a005 = next(r for r in h if r.entity_id == "A005")
    assert RENEW not in a005.metrics
    assert a005.dropped[RENEW] == "unsupported_unit"


def test_harmonisation_carries_direction_and_unit(records, registry):
    h = harmonise_records(records, registry)
    a001 = next(r for r in h if r.entity_id == "A001")
    m = a001.metrics[RENEW]
    assert m.direction == "higher_is_better"
    assert m.canonical_unit == "percent"


def test_harmonisation_carries_source(records, registry):
    h = harmonise_records(records, registry)
    a001 = next(r for r in h if r.entity_id == "A001")
    assert a001.metrics[EUI].source == "synthetic-dataset"
    a003_2023 = next(
        r for r in h if r.entity_id == "A003" and r.reporting_period == "2023"
    )
    assert a003_2023.metrics[EUI].source == "manual-curation"
