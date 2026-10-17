from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_get_analysis_default_dataset():
    r = client.get("/analysis/A001", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    body = r.json()
    assert {"entity_id", "entity_name", "tenant_id", "reporting_year", "peer_cohort", "metrics"} <= set(body)
    assert body["entity_id"] == "A001"
    assert isinstance(body["reporting_year"], int)
    # CORS for the Vite dev server
    assert r.headers.get("access-control-allow-origin")


def test_get_analysis_entity_not_found():
    assert client.get("/analysis/NOPE").status_code == 404


def test_get_analysis_rejects_bad_scope():
    assert client.get("/analysis/A001", params={"scope": "planet"}).status_code == 422


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
