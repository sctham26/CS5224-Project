import pytest
from pydantic import ValidationError

from schemas import (
    ESGRecord,
    MetricObservation,
    ReportingScope,
    MetricDirection,
)


def test_reporting_scope_is_asset_or_portfolio():
    assert ReportingScope.ASSET == "asset"
    assert ReportingScope.PORTFOLIO == "portfolio"


def test_metric_direction_values():
    assert MetricDirection.HIGHER_IS_BETTER == "higher_is_better"
    assert MetricDirection.LOWER_IS_BETTER == "lower_is_better"


def test_esg_record_valid_minimal():
    rec = ESGRecord(
        entity_id="A001",
        scope=ReportingScope.ASSET,
        reporting_period="2024",
        metrics={"energy_intensity": MetricObservation(value=120.0, unit="kWh/m2/year")},
    )
    assert rec.entity_id == "A001"
    assert rec.metrics["energy_intensity"].value == 120.0


def test_esg_record_rejects_negative_value():
    with pytest.raises(ValidationError):
        ESGRecord(
            entity_id="A001",
            scope=ReportingScope.ASSET,
            reporting_period="2024",
            metrics={"energy_intensity": MetricObservation(value=-1.0, unit="kWh/m2/year")},
        )


def test_esg_record_rejects_empty_period():
    with pytest.raises(ValidationError):
        ESGRecord(
            entity_id="A001",
            scope=ReportingScope.ASSET,
            reporting_period="",
            metrics={},
        )
