"""Ingestion job model, idempotency store and S3/SQS adapters.

Implements the backend half of ``docs/BACKEND_CLOUD_CONTRACT.md`` without touching
the analytics core:

* ``POST /uploads`` returns a short-lived presigned PUT for
  ``tenants/<tenant>/uploads/<uuid>.csv``; bytes never pass through the API.
* ``POST /jobs`` is idempotent per tenant + endpoint + request hash and returns the
  same job for an identical retry (``409`` when the hash changes).
* ``GET /jobs/{job_id}`` only ever resolves jobs owned by the caller's tenant.
* States move ``PENDING -> QUEUED -> RUNNING -> SUCCEEDED|FAILED`` and never
  backwards. Only the worker claims a job, and only with a lease.

Boto3 and psycopg are imported lazily so local runs need neither.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

PENDING = "PENDING"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"

#: Terminal rank; a job may only move to a strictly greater rank.
_RANK = {PENDING: 0, QUEUED: 1, RUNNING: 2, SUCCEEDED: 3, FAILED: 3}
TERMINAL = {SUCCEEDED, FAILED}

UPLOAD_PREFIX = "tenants/{tenant_id}/uploads/"
JOB_PREFIX = "tenants/{tenant_id}/jobs/"


def upload_key(tenant_id: str) -> str:
    return f"{UPLOAD_PREFIX.format(tenant_id=tenant_id)}{uuid.uuid4().hex}.csv"


def result_key(tenant_id: str, job_id: str) -> str:
    return f"{JOB_PREFIX.format(tenant_id=tenant_id)}{job_id}/result.json"


def owns_upload_key(tenant_id: str, key: str) -> bool:
    """Reject keys outside the caller's own upload prefix (cross-tenant reads)."""
    return bool(key) and key.startswith(UPLOAD_PREFIX.format(tenant_id=tenant_id)) and ".." not in key


class JobError(Exception):
    """Base class for job-layer failures."""


class IdempotencyConflict(JobError):
    """Same key reused with a different request body -> 409."""


class UploadNotConfigured(JobError):
    """No S3/queue configuration in this environment -> 503."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Job:
    job_id: str
    tenant_id: str
    status: str
    entity_id: str
    upload_key: str
    request_hash: str
    scope: str = "asset"
    reporting_year: Optional[int] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    attempts: int = 0
    lease_expires_at: Optional[str] = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def public(self) -> dict:
        """Tenant-visible metadata; never exposes raw S3 paths."""
        body: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status,
            "status_url": f"/api/jobs/{self.job_id}",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.reporting_year is not None:
            body["reporting_year"] = self.reporting_year
        if self.status == SUCCEEDED and self.result is not None:
            body["result"] = self.result
        if self.status == FAILED and self.error:
            body["error"] = self.error
        return body


class JobStore(Protocol):
    """Persistence for jobs; every method is tenant-scoped."""

    def create_or_get(
        self, tenant_id: str, idempotency_key: str, request_hash: str, **fields
    ) -> tuple[Job, bool]: ...

    def get(self, tenant_id: str, job_id: str) -> Optional[Job]: ...

    def claim(self, job_id: str, tenant_id: str, lease_seconds: int) -> Optional[Job]: ...

    def finish(self, job: Job, status: str, *, result: Optional[dict], error: Optional[str]) -> Job: ...


class InMemoryJobStore:
    """Local development and tests."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._keys: dict[tuple[str, str, str], str] = {}
        self._lock = threading.Lock()

    def create_or_get(
        self, tenant_id: str, idempotency_key: str, request_hash: str, **fields
    ) -> tuple[Job, bool]:
        key = (tenant_id, "POST /jobs", idempotency_key)
        with self._lock:
            existing = self._keys.get(key)
            if existing:
                job = self._jobs[existing]
                if job.request_hash != request_hash:
                    raise IdempotencyConflict("idempotency key reused with a different request")
                return job, True
            job = Job(
                job_id=f"job_{uuid.uuid4().hex}",
                tenant_id=tenant_id,
                status=QUEUED,
                request_hash=request_hash,
                **fields,
            )
            self._jobs[job.job_id] = job
            self._keys[key] = job.job_id
            return job, False

    def get(self, tenant_id: str, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job if job and job.tenant_id == tenant_id else None

    def claim(self, job_id: str, tenant_id: str, lease_seconds: int) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.tenant_id != tenant_id or job.status in TERMINAL:
                return None
            if job.status == RUNNING:  # another attempt still holds a live lease
                return None
            claimed = replace(
                job,
                status=RUNNING,
                attempts=job.attempts + 1,
                lease_expires_at=_now(),
                updated_at=_now(),
            )
            self._jobs[job_id] = claimed
            return claimed

    def finish(
        self, job: Job, status: str, *, result: Optional[dict], error: Optional[str]
    ) -> Job:
        with self._lock:
            current = self._jobs[job.job_id]
            if status not in TERMINAL:
                raise JobError("finish() requires a terminal status")
            if current.status in TERMINAL and current.status != status:
                return current  # never move a terminal job
            done = replace(
                current,
                status=status,
                result=result,
                error=error,
                lease_expires_at=None,
                updated_at=_now(),
            )
            self._jobs[job.job_id] = done
            return done


_JOB_TABLE = "ingestion_job"


class PostgresJobStore:
    """Durable jobs in ``spip_tenant``; row-level security keyed on tenant."""

    def __init__(self, tenant_url: str):
        self.tenant_url = tenant_url
        self._columns = (
            "job_id, tenant_id, status, entity_id, upload_key, request_hash, scope, "
            "reporting_year, result, error, attempts, lease_expires_at::text, "
            "created_at::text, updated_at::text"
        )

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - configuration error
            raise JobError("psycopg is required for the job store") from exc
        return psycopg.connect(self.tenant_url)

    @staticmethod
    def _row(row) -> Job:
        (job_id, tenant_id, status, entity_id, key, request_hash, scope, year,
         result, error, attempts, lease, created, updated) = row
        return Job(
            job_id=job_id,
            tenant_id=tenant_id,
            status=status,
            entity_id=entity_id,
            upload_key=key,
            request_hash=request_hash,
            scope=scope,
            reporting_year=year,
            result=result,
            error=error,
            attempts=attempts,
            lease_expires_at=lease,
            created_at=created,
            updated_at=updated,
        )

    def create_or_get(
        self, tenant_id: str, idempotency_key: str, request_hash: str, **fields
    ) -> tuple[Job, bool]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                cur.execute(
                    f"SELECT {self._columns} FROM {_JOB_TABLE} "
                    "WHERE tenant_id = %s AND endpoint = %s AND idempotency_key = %s",
                    (tenant_id, "POST /jobs", idempotency_key),
                )
                existing = cur.fetchone()
                if existing:
                    job = self._row(existing)
                    if job.request_hash != request_hash:
                        raise IdempotencyConflict(
                            "idempotency key reused with a different request"
                        )
                    return job, True

                job_id = f"job_{uuid.uuid4().hex}"
                cur.execute(
                    f"INSERT INTO {_JOB_TABLE} (job_id, tenant_id, endpoint, idempotency_key,"
                    " status, entity_id, upload_key, request_hash, scope, reporting_year)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING "
                    + self._columns,
                    (
                        job_id,
                        tenant_id,
                        "POST /jobs",
                        idempotency_key,
                        QUEUED,
                        fields["entity_id"],
                        fields["upload_key"],
                        request_hash,
                        fields.get("scope", "asset"),
                        fields.get("reporting_year"),
                    ),
                )
                return self._row(cur.fetchone()), False

    def get(self, tenant_id: str, job_id: str) -> Optional[Job]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                cur.execute(
                    f"SELECT {self._columns} FROM {_JOB_TABLE} WHERE tenant_id = %s AND job_id = %s",
                    (tenant_id, job_id),
                )
                row = cur.fetchone()
        return self._row(row) if row else None

    def claim(self, job_id: str, tenant_id: str, lease_seconds: int) -> Optional[Job]:
        """Atomically take the job; re-claims only after the lease expired."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                cur.execute(
                    f"UPDATE {_JOB_TABLE} SET status = %s, attempts = attempts + 1,"
                    " lease_expires_at = now() + make_interval(secs => %s)::interval,"
                    " updated_at = now() WHERE job_id = %s AND tenant_id = %s AND ("
                    "status = %s OR (status = %s AND lease_expires_at < now()))"
                    f" RETURNING {self._columns}",
                    (RUNNING, lease_seconds, job_id, tenant_id, QUEUED, RUNNING),
                )
                row = cur.fetchone()
        return self._row(row) if row else None

    def finish(
        self, job: Job, status: str, *, result: Optional[dict], error: Optional[str]
    ) -> Job:
        import json

        if status not in TERMINAL:
            raise JobError("finish() requires a terminal status")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, true)", (job.tenant_id,))
                cur.execute(
                    f"UPDATE {_JOB_TABLE} SET status = %s, result = %s, error = %s,"
                    " lease_expires_at = NULL, updated_at = now()"
                    " WHERE job_id = %s AND tenant_id = %s AND status = %s"
                    f" RETURNING {self._columns}",
                    (
                        status,
                        json.dumps(result) if result is not None else None,
                        error,
                        job.job_id,
                        job.tenant_id,
                        RUNNING,
                    ),
                )
                row = cur.fetchone()
                if row is None:  # already terminal or never claimed
                    cur.execute("SELECT set_config('app.tenant_id', %s, true)", (job.tenant_id,))
                    cur.execute(
                        f"SELECT {self._columns} FROM {_JOB_TABLE} WHERE job_id = %s AND tenant_id = %s",
                        (job.job_id, job.tenant_id),
                    )
                    row = cur.fetchone()
        return self._row(row) if row else job


class S3Uploader:
    """Presigns browser PUTs into the tenant bucket; no bytes via the API."""

    def __init__(
        self,
        bucket: str,
        ttl_seconds: int = 300,
        client=None,
        public_base: Optional[str] = None,
    ):
        self.bucket = bucket
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._public_base = public_base

    @property
    def client(self):
        if self._client is None:
            import boto3  # lazy: local runs do not need AWS SDK

            self._client = boto3.client("s3", region_name=os.environ.get("AWS_REGION"))
        return self._client

    def presign(self, tenant_id: str) -> dict:
        key = upload_key(tenant_id)
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": "text/csv"},
            ExpiresIn=self.ttl_seconds,
        )
        return {
            "upload_url": url,
            "method": "PUT",
            "key": key,
            "expires_in": self.ttl_seconds,
            "content_type": "text/csv",
        }

    def read(self, key: str) -> bytes:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        return body.read()

    def write_json(self, key: str, payload: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType="application/json")


class JobQueue:
    """Thin SQS sender; the worker reads messages itself."""

    def __init__(self, queue_url: str, client=None):
        self.queue_url = queue_url
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION"))
        return self._client

    def send(self, envelope: dict) -> None:
        import json

        self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps(envelope))


def envelope_for(job: Job) -> dict:
    """Message the dispatcher hands to the worker."""
    return {
        "job_id": job.job_id,
        "tenant_id": job.tenant_id,
        "upload_key": job.upload_key,
        "entity_id": job.entity_id,
        "reporting_year": job.reporting_year,
        "scope": job.scope,
    }


def build_pipeline(environ: dict[str, str] | None = None):
    """Assemble uploader + queue + store from the deployment environment.

    Returns ``(store, uploader_or_None, queue_or_None)``; the cloud deployment sets
    every value, local development sets none and the routes answer ``503``.
    """
    env = os.environ if environ is None else environ
    tenant_url = env.get("SPIP_TENANT_DATABASE_URL")
    store: JobStore = (
        PostgresJobStore(tenant_url) if tenant_url else InMemoryJobStore()
    )
    bucket = env.get("SPIP_TENANT_DATA_BUCKET")
    uploader = (
        S3Uploader(
            bucket=bucket,
            ttl_seconds=int(env.get("SPIP_UPLOAD_URL_TTL_SECONDS", 300)),
        )
        if bucket
        else None
    )
    queue = (
        JobQueue(env["SPIP_JOB_QUEUE_URL"]) if env.get("SPIP_JOB_QUEUE_URL") else None
    )
    return store, uploader, queue
