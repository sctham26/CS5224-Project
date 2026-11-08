"""Worker merge: the upload supplies the target, stored data supplies the peers."""

from __future__ import annotations

import pandas as pd
import pytest

import worker

TEAM = [
    "entity_id",
    "reporting_scope",
    "reporting_year",
    "region",
    "property_type",
    "metric_code",
    "standardised_value",
    "canonical_unit",
    "comparability_status",
]


def _rows(entity_id: str, values, year: int = 2024) -> list[dict]:
    return [
        {
            "entity_id": entity_id,
            "reporting_scope": "ASSET",
            "reporting_year": year,
            "region": "SG",
            "property_type": "OFFICE",
            "metric_code": "ENERGY_INTENSITY_EUI",
            "standardised_value": value,
            "canonical_unit": "kWh/m2/yr",
            "comparability_status": "COMPARABLE",
        }
        for value in values
    ]


def _csv(rows) -> bytes:
    return pd.DataFrame(rows, columns=TEAM).to_csv(index=False).encode()


def _frame(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=TEAM)


class FakeUploader:
    def __init__(self, body: bytes):
        self.body = body
        self.written: dict[str, bytes] = {}

    def read(self, key: str) -> bytes:
        return self.body

    def write_json(self, key: str, payload: bytes) -> None:
        self.written[key] = payload


class FakeStore:
    def __init__(self) -> None:
        self.status = None
        self.result = None
        self.error = None

    def claim(self, job_id, tenant_id, lease_seconds):
        return object()

    def finish(self, job, status, *, result, error):
        self.status, self.result, self.error = status, result, error


class FakeSource:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def load(self, tenant_id: str) -> pd.DataFrame:
        return self.frame


def _envelope(entity_id: str = "TGT") -> dict:
    return {
        "job_id": "job_test",
        "tenant_id": "t1",
        "upload_key": "tenants/t1/uploads/a.csv",
        "entity_id": entity_id,
        "reporting_year": 2024,
        "scope": "asset",
    }


def _run(monkeypatch, uploaded: list[dict], stored) -> FakeStore:
    monkeypatch.setattr(worker, "_datasource", stored)
    monkeypatch.delenv("SPIP_PERSIST_UPLOADS", raising=False)
    store = FakeStore()
    worker.process_job(_envelope(), store, FakeUploader(_csv(uploaded)))
    return store


def _eui(result: dict) -> dict:
    return next(m for m in result["metrics"] if m["metric_code"] == "ENERGY_INTENSITY_EUI")


def test_upload_is_benchmarked_against_stored_cohort(monkeypatch):
    stored = FakeSource(_frame([r for i in range(6) for r in _rows(f"P{i}", [120 + i])]))
    store = _run(monkeypatch, _rows("TGT", [150]), stored)

    assert store.status == "SUCCEEDED"
    eui = _eui(store.result)
    assert eui["benchmark"] is not None
    assert store.result["peer_cohort"]["sample_size_n"] == 6


def test_without_stored_data_the_upload_is_analysed_alone(monkeypatch):
    monkeypatch.delenv("SPIP_PUBLIC_DATABASE_URL", raising=False)
    monkeypatch.setenv("SPIP_DATA", "tests/no-such-baseline.csv")
    store = _run(monkeypatch, _rows("TGT", [150]), None)

    assert store.status == "SUCCEEDED"
    eui = _eui(store.result)
    assert eui["benchmark"] is None
    assert eui["gap_analysis"]["gap_type"] is None
    assert eui["gap_analysis"]["is_flagged"] is None


def test_uploaded_row_replaces_the_stored_one(monkeypatch):
    stored = FakeSource(
        _frame(_rows("TGT", [999]) + [r for i in range(5) for r in _rows(f"P{i}", [120 + i])])
    )
    keep = worker.merge_upload(stored.load("t1"), _frame(_rows("TGT", [150])))

    target = keep[keep["entity_id"] == "TGT"]
    assert len(keep) == 6 and len(target) == 1
    assert target["standardised_value"].iloc[0] == 150


def test_upload_without_the_target_fails(monkeypatch):
    stored = FakeSource(_frame([r for i in range(6) for r in _rows(f"P{i}", [120 + i])]))
    store = _run(monkeypatch, _rows("OTHER", [150]), stored)

    assert store.status == "FAILED"
    assert "not in the uploaded file" in store.error


def test_persistence_is_off_by_default(monkeypatch):
    monkeypatch.delenv("SPIP_PERSIST_UPLOADS", raising=False)
    called = []
    monkeypatch.setattr(worker, "load_observations", lambda *a, **k: called.append(a))

    assert worker.persist_upload(_frame(_rows("TGT", [150])), "t1") == 0
    assert called == []


def test_persistence_stamps_the_caller_tenant(monkeypatch):
    monkeypatch.setenv("SPIP_PERSIST_UPLOADS", "1")
    monkeypatch.setenv("SPIP_TENANT_DATABASE_URL", "postgresql:///spip_tenant")
    seen: dict = {}
    monkeypatch.setattr(
        worker,
        "load_observations",
        lambda rows, url, tenant_id=None: seen.update(rows=rows, url=url, tenant=tenant_id)
        or len(rows),
    )
    rows = _rows("TGT", [150])
    rows[0]["tenant_id"] = "someone-else"
    rows[0]["visibility"] = "public"

    assert worker.persist_upload(_frame(rows), "t1") == 1
    assert seen["url"] == "postgresql:///spip_tenant" and seen["tenant"] == "t1"
    assert {row[0] for row in seen["rows"]} == {"t1"}  # tenant_id column wins


def test_persistence_skips_engine_format(monkeypatch):
    monkeypatch.setenv("SPIP_PERSIST_UPLOADS", "1")
    monkeypatch.setenv("SPIP_TENANT_DATABASE_URL", "postgresql:///spip_tenant")
    monkeypatch.setattr(worker, "load_observations", lambda *a, **k: pytest.fail("must not write"))

    engine_style = pd.DataFrame([{"entity_id": "TGT", "scope": "asset", "metric": "EUI"}])
    assert worker.persist_upload(engine_style, "t1") == 0
