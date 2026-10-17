import pytest

from metrics import MetricRegistry, UnknownMetricError, IncompatibleUnitError


@pytest.fixture(scope="module")
def registry():
    return MetricRegistry.from_yaml("config/metrics.yaml")


def test_registry_loads_declared_metrics(registry):
    assert "energy_intensity" in registry.metrics
    assert "emissions_intensity" in registry.metrics


def test_unit_conversion_to_canonical(registry):
    # 2 MWh/m2/year -> 2000 kWh/m2/year
    assert registry.convert("energy_intensity", 2.0, "MWh/m2/year") == pytest.approx(2000.0)
    # 3.5 tCO2e/m2/year -> 3500 kgCO2e/m2/year
    assert registry.convert("emissions_intensity", 3.5, "tCO2e/m2/year") == pytest.approx(3500.0)


def test_canonical_unit_passthrough(registry):
    assert registry.convert("energy_intensity", 95.5, "kWh/m2/year") == pytest.approx(95.5)


def test_unknown_metric_raises(registry):
    with pytest.raises(UnknownMetricError):
        registry.convert("not_a_metric", 1.0, "kWh/m2/year")


def test_incompatible_unit_raises(registry):
    with pytest.raises(IncompatibleUnitError):
        registry.convert("energy_intensity", 1.0, "kgCO2e/m2/year")


def test_direction_and_scope_metadata(registry):
    spec = registry.spec("energy_intensity")
    assert spec.direction == "lower_is_better"
    assert "asset" in spec.scopes and "portfolio" in spec.scopes
