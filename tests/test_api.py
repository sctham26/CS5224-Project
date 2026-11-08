from fastapi.testclient import TestClient
import pandas as pd

import api
from api import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_get_analysis_default_dataset():
    # API default is the team's public baseline (building-level, team CSV format).
    r = client.get("/analysis/SG_228218_LATEST_6", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    body = r.json()
    assert {"entity_id", "entity_name", "tenant_id", "reporting_year", "peer_cohort", "metrics"} <= set(body)
    assert body["entity_id"] == "SG_228218_LATEST_6"
    assert isinstance(body["reporting_year"], int)
    assert body["peer_cohort"]["property_type"] == "OFFICE"
    # CORS for the Vite dev server
    assert r.headers.get("access-control-allow-origin")


def test_get_analysis_entity_not_found():
    assert client.get("/analysis/NOPE").status_code == 404


def test_get_analysis_rejects_bad_scope():
    assert (
        client.get("/analysis/SG_228218_LATEST_6", params={"scope": "planet"}).status_code == 422
    )


def test_post_upload_their_format():
    with open("tests/fixtures_their.csv", "rb") as fh:
        r = client.post(
            "/analyze",
            params={"entity_id": "TGT_BUILD", "reporting_year": 2025},
            files={"file": ("their.csv", fh, "text/csv")},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_id"] == "TGT_BUILD"
    assert body["peer_cohort"]["sample_size_n"] >= 5


def test_post_upload_unknown_metric_rejected():
    with open("tests/fixtures_unknown_metric.csv", "rb") as fh:
        r = client.post(
            "/analyze",
            params={"entity_id": "BAD_1"},
            files={"file": ("bad.csv", fh, "text/csv")},
        )
    assert r.status_code == 422
    assert "BOGUS_METRIC" in r.json()["detail"]


def test_post_upload_entity_not_found():
    with open("tests/fixtures_their.csv", "rb") as fh:
        r = client.post(
            "/analyze",
            params={"entity_id": "NOPE"},
            files={"file": ("their.csv", fh, "text/csv")},
        )
    assert r.status_code == 404


def test_entities_lists_reporting_years_from_the_data():
    """Discovery endpoint: years are whatever exists, so gaps are never offered."""
    body = client.get("/entities").json()
    assert body["count"] > 0
    entry = next(
        e for e in body["entities"] if e["entity_id"] == "SG_228218_LATEST_6"
    )
    # Baseline has 2017-2020 and 2022-2025; 2021 must not appear.
    assert 2021 not in entry["reporting_years"]
    assert entry["latest_reporting_year"] == entry["reporting_years"][0] == 2025
    assert entry["scope"] == "asset" and entry["property_type"] == "OFFICE"


def test_entities_can_be_filtered_by_scope():
    body = client.get("/entities", params={"scope": "asset"}).json()
    assert {e["scope"] for e in body["entities"]} == {"asset"}
    assert client.get("/entities", params={"scope": "planet"}).status_code == 422


def test_analysis_result_is_cached(monkeypatch):
    calls = []
    real = api._analyse
    monkeypatch.setattr(api, "_analyse", lambda *a, **k: calls.append(1) or real(*a, **k))
    api._analysis_cache.clear()

    params = {"reporting_year": 2024}
    first = client.get("/analysis/SG_228218_LATEST_6", params=params)
    second = client.get("/analysis/SG_228218_LATEST_6", params=params)

    assert first.status_code == second.status_code == 200
    assert len(calls) == 1
    assert first.json() == second.json()


def test_cache_misses_after_a_datasource_reload(monkeypatch):
    """A reloaded frame is a new object, so the old result is never served."""
    calls = []
    monkeypatch.setattr(api, "_analyse", lambda *a, **k: calls.append(1) or {"ok": True})
    api._analysis_cache.clear()

    api._cached_analysis(pd.DataFrame({"entity_id": ["A"]}), "A", 2024, "asset", "t")
    api._cached_analysis(pd.DataFrame({"entity_id": ["A"]}), "A", 2024, "asset", "t")

    assert len(calls) == 2
