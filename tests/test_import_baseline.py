"""Baseline importer tests: validation, normalisation, upsert safety (light)."""

import pandas as pd
import pytest

from import_baseline import COLUMNS, UPSERT_KEY, ImportError_, main, prepare_rows


def _frame(**overrides):
    data = {
        "entity_id": ["SG_1"],
        "entity_name": ["One Raffles"],
        "property_type": ["OFFICE"],
        "region": ["SG"],
        "reporting_scope": ["ASSET"],
        "reporting_year": [2024],
        "metric_code": ["ENERGY_INTENSITY_EUI"],
        "standardised_value": [123.4],
        "canonical_unit": ["kWh/m2/yr"],
        "comparability_status": ["COMPARABLE"],
        "source_reference": ["bca-2024"],
    }
    data.update(overrides)
    return pd.DataFrame(data)


def test_rows_are_normalised_to_the_observation_schema():
    rows = prepare_rows(_frame())
    assert len(rows) == 1
    record = dict(zip(COLUMNS, rows[0]))
    assert record["tenant_id"] == "PUBLIC"
    assert record["reporting_scope"] == "asset"  # lower-case like the engine
    assert isinstance(record["reporting_year"], int)
    assert record["standardised_value"] == pytest.approx(123.4)


def test_missing_standardised_value_becomes_null():
    rows = prepare_rows(_frame(standardised_value=[None]))
    record = dict(zip(COLUMNS, rows[0]))
    assert record["standardised_value"] is None


def test_duplicate_upsert_keys_collapse_to_one_row():
    # Same building/metric/year twice must not fail the batch as a duplicate.
    df = pd.concat([_frame(), _frame(standardised_value=[999.0])], ignore_index=True)
    rows = prepare_rows(df)
    assert len(rows) == 1
    record = dict(zip(COLUMNS, rows[0]))
    assert record["standardised_value"] == pytest.approx(999.0)  # last writer wins


def test_missing_required_column_fails_before_writing():
    df = _frame().drop(columns=["metric_code"])
    with pytest.raises(ImportError_, match="metric_code"):
        prepare_rows(df)


def test_non_numeric_reporting_year_is_rejected():
    with pytest.raises(ImportError_, match="reporting_year"):
        prepare_rows(_frame(reporting_year=["FY24"]))


def test_upsert_key_covers_every_observation_dimension():
    assert set(UPSERT_KEY) == {
        "tenant_id",
        "entity_id",
        "reporting_year",
        "reporting_scope",
        "metric_code",
    }


def test_dry_run_writes_nothing_without_a_database(monkeypatch, tmp_path):
    path = tmp_path / "baseline.csv"
    _frame().to_csv(path, index=False)
    monkeypatch.delenv("SPIP_PUBLIC_DATABASE_URL", raising=False)
    assert main(["--data", str(path), "--dry-run"]) == 0


def test_without_database_url_and_without_dry_run_fails(monkeypatch, tmp_path):
    path = tmp_path / "baseline.csv"
    _frame().to_csv(path, index=False)
    monkeypatch.delenv("SPIP_PUBLIC_DATABASE_URL", raising=False)
    assert main(["--data", str(path)]) == 2
