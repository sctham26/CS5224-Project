"""Ingestion pipeline tests: presign, idempotency, tenancy, worker, DLQ (light)."""

import io
import json

import pytest
from fastapi.testclient import TestClient

import api
import jobs as jobs_mod
import worker
from auth import Authenticator
from jobs import (
    FAILED,
    QUEUED,
    SUCCEEDED,
    InMemoryJobStore,
    JobQueue,
    S3Uploader,
    envelope_for,
)

client = TestClient(api.app)
CSV = b"tenant_id,entity_id,entity_name,property_type,region,reporting_scope,reporting_year,metric_code,standardised_value,canonical_unit,comparability_status,source_reference\nPUBLIC,PUB_BUILD,Public Tower,OFFICE,SG,ASSET,2024,ENERGY_INTENSITY_EUI,100.0,kWh/m2/yr,COMPARABLE,test\n"


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.presigned = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned.append((operation, Params, ExpiresIn))
        return "https://s3.example.invalid/presigned-put"

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body


class FakeQueue:
    def __init__(self):
        self.sent = []

    def send(self, envelope):
        self.sent.append(envelope)


@pytest.fixture
def pipeline(monkeypatch):
    store, s3, queue = InMemoryJobStore(), FakeS3(), FakeQueue()
    monkeypatch.setattr(api, "_job_store", store)
    monkeypatch.setattr(api, "_uploader", S3Uploader("tenant-bucket", client=s3))
    monkeypatch.setattr(api, "_job_queue", queue)
    monkeypatch.setattr(api, "_authenticator", Authenticator(enabled=False, demo_tenant="tenant_a"))
    return store, s3, queue


def _create(c, key="idem-1", body=None):
    payload = body or {
        "upload_key": f"tenants/tenant_a/uploads/{key}.csv",
        "entity_id": "PUB_BUILD",
        "reporting_year": 2024,
    }
    return c.post("/jobs", json=payload, headers={"Idempotency-Key": key})


# --- presign ------------------------------------------------------------------


def test_uploads_presigns_into_own_tenant_prefix(pipeline):
    _, s3, _ = pipeline
    r = client.post("/uploads")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["method"] == "PUT" and body["content_type"] == "text/csv"
    assert body["key"].startswith("tenants/tenant_a/uploads/")
    operation, params, expires = s3.presigned[0]
    assert operation == "put_object" and expires == 300
    assert params["ContentType"] == "text/csv"


def test_pipeline_absent_returns_503(monkeypatch):
    monkeypatch.setattr(api, "_uploader", None)
    monkeypatch.setattr(api, "_job_queue", None)
    assert client.post("/uploads").status_code == 503


# --- idempotency --------------------------------------------------------------


def test_job_is_created_and_dispatched_once(pipeline):
    _, _, queue = pipeline
    r = _create(client)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == QUEUED and body["job_id"].startswith("job_")
    assert body["status_url"].endswith(body["job_id"])
    assert len(queue.sent) == 1 and queue.sent[0]["job_id"] == body["job_id"]


def test_identical_retry_replays_the_same_job(pipeline):
    _, _, queue = pipeline
    first = _create(client).json()
    again = _create(client)
    assert again.status_code == 202
    assert again.json()["job_id"] == first["job_id"]
    assert again.headers.get("idempotent-replay") == "true"
    assert len(queue.sent) == 2  # QUEUED replay repairs an uncertain dispatch
    assert queue.sent[0] == queue.sent[1]


def test_same_key_with_different_body_conflicts(pipeline):
    _create(client)
    changed = _create(
        client,
        body={"upload_key": "tenants/tenant_a/uploads/idem-1.csv", "entity_id": "OTHER", "reporting_year": 2024},
    )
    assert changed.status_code == 409


def test_missing_idempotency_key_is_rejected(pipeline):
    r = client.post(
        "/jobs",
        json={"upload_key": "tenants/tenant_a/uploads/x.csv", "entity_id": "PUB_BUILD"},
    )
    assert r.status_code == 422


def test_foreign_upload_key_is_not_found(pipeline):
    r = _create(
        client,
        body={"upload_key": "tenants/tenant_b/uploads/steal.csv", "entity_id": "PUB_BUILD"},
    )
    assert r.status_code == 404


def test_invalid_scope_is_rejected(pipeline):
    r = _create(
        client,
        body={"upload_key": "tenants/tenant_a/uploads/s.csv", "entity_id": "PUB_BUILD", "scope": "planet"},
    )
    assert r.status_code == 422


# --- job reads ------------------------------------------------------------------


def test_job_read_is_tenant_scoped(pipeline):
    job_id = _create(client).json()["job_id"]
    assert client.get(f"/jobs/{job_id}").status_code == 200
    assert client.get("/jobs/job_does_not_exist").status_code == 404


def test_state_machine_never_moves_backwards():
    store = InMemoryJobStore()
    job, _ = store.create_or_get("tenant_a", "k", "hash", entity_id="E", upload_key="tenants/tenant_a/uploads/k.csv")
    claimed = store.claim(job.job_id, "tenant_a", 900)
    assert claimed.status is not None and claimed.status == "RUNNING"
    assert store.claim(job.job_id, "tenant_a", 900) is None  # lease held
    store.finish(claimed, SUCCEEDED, result={"ok": True}, error=None)
    assert store.claim(job.job_id, "tenant_a", 900) is None  # terminal
    assert store.get("tenant_a", job.job_id).status == SUCCEEDED


# --- worker ---------------------------------------------------------------------


def test_envelope_rejects_cross_tenant_upload_key():
    with pytest.raises(worker.InvalidEnvelope):
        worker.parse_envelope(
            {"job_id": "j", "tenant_id": "tenant_a", "upload_key": "tenants/tenant_b/uploads/x.csv", "entity_id": "E"}
        )


def test_worker_processes_job_and_persists_result(pipeline):
    store, s3, _ = pipeline
    body = _create(client).json()
    job = store.get("tenant_a", body["job_id"])
    s3.objects[job.upload_key] = CSV

    assert worker.process_job(envelope_for(job), store, S3Uploader("tenant-bucket", client=s3)) == SUCCEEDED
    done = store.get("tenant_a", job.job_id)
    assert done.status == SUCCEEDED
    assert done.result["entity_id"] == "PUB_BUILD" and done.result["tenant_id"] == "tenant_a"
    # Result object written under the tenant's job prefix.
    assert f"tenants/tenant_a/jobs/{job.job_id}/result.json" in s3.objects


def test_worker_reports_unreadable_upload_as_failed(pipeline):
    store, s3, _ = pipeline
    body = _create(client).json()
    job = store.get("tenant_a", body["job_id"])
    s3.objects[job.upload_key] = b"not,a,valid,csv\n"

    assert worker.process_job(envelope_for(job), store, S3Uploader("tenant-bucket", client=s3)) == FAILED
    assert store.get("tenant_a", job.job_id).error


def test_dlq_reconciliation_retains_nonterminal_job(pipeline):
    store, s3, _ = pipeline
    body = _create(client).json()
    job = store.get("tenant_a", body["job_id"])

    class FakeSQS:
        def __init__(self):
            self.deleted = []

        def receive_message(self, QueueUrl, MaxNumberOfMessages, WaitTimeSeconds):
            return {"Messages": [{"Body": json.dumps(envelope_for(job)), "ReceiptHandle": "rh-1"}]} if not self.deleted else {}

        def delete_message(self, QueueUrl, ReceiptHandle):
            self.deleted.append(ReceiptHandle)

    client_sqs = FakeSQS()
    assert worker.reconcile_dlq("dlq", store, client=client_sqs) == 0
    assert store.get("tenant_a", job.job_id).status == job.status
    assert client_sqs.deleted == []


def test_job_queue_sends_envelope_when_client_injected():
    sent = []

    class FakeClient:
        def send_message(self, QueueUrl, MessageBody):
            sent.append((QueueUrl, json.loads(MessageBody)))

    queue = JobQueue("https://queue.invalid", client=FakeClient())
    queue.send({"job_id": "j1"})
    assert sent == [("https://queue.invalid", {"job_id": "j1"})]


def test_replay_after_terminal_state_does_not_redispatch(pipeline):
    store, _, queue = pipeline
    job_id = _create(client).json()["job_id"]
    store.finish(store.get("tenant_a", job_id), SUCCEEDED, result={"ok": True}, error=None)

    _create(client)
    assert len(queue.sent) == 1  # already finished: nothing to re-send


class _ScriptedCursor:
    """Cursor whose fetchone() returns the value scripted for the last execute()."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append(sql)
        self.result = self.script.pop(0) if self.script else None

    def fetchone(self):
        return self.result


class _ScriptedConnection:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self.cur


def _store_scripted(cursor):
    store = jobs_mod.PostgresJobStore("postgresql://unused")
    store._connect = lambda: _ScriptedConnection(cursor)
    return store


def _winner_row(request_hash):
    return (
        "job_x", "tenant_a", QUEUED, "PUB_BUILD", "tenants/tenant_a/uploads/k.csv",
        request_hash, "asset", 2024, None, None, 0, None, "t0", "t0",
    )


def test_concurrent_identical_insert_returns_the_winner():
    # set_config, SELECT (miss), INSERT (loses the race), SELECT (winner).
    cur = _ScriptedCursor([None, None, None, _winner_row("hash")])
    job, replayed = _store_scripted(cur).create_or_get(
        "tenant_a", "k", "hash",
        entity_id="PUB_BUILD", upload_key="tenants/tenant_a/uploads/k.csv",
        scope="asset", reporting_year=2024,
    )
    assert replayed is True and job.job_id == "job_x"
    assert any("ON CONFLICT" in sql for sql in cur.calls)


def test_concurrent_insert_with_a_different_hash_conflicts():
    cur = _ScriptedCursor([None, None, None, _winner_row("other-hash")])
    with pytest.raises(jobs_mod.IdempotencyConflict):
        _store_scripted(cur).create_or_get(
            "tenant_a", "k", "hash",
            entity_id="PUB_BUILD", upload_key="tenants/tenant_a/uploads/k.csv",
            scope="asset", reporting_year=2024,
        )
