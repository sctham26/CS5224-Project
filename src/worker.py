"""Ingestion worker: SQS -> S3 -> analytics engine -> durable job result.

Run in ECS as ``python src/worker.py`` (or ``python -m worker`` with ``src`` on
``PYTHONPATH``); the deployment supplies ``worker_command``.
Acknowledges a message only after the job is durably terminal, so transient
failures stay retryable; exhausted messages are reconciled from the DLQ into
visible ``FAILED`` jobs instead of leaving them ``RUNNING`` forever.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile

from contract import ContractInputError, EntityNotFound, analyse_to_contract
from jobs import (
    FAILED,
    SUCCEEDED,
    JobStore,
    PostgresJobStore,
    S3Uploader,
    build_pipeline,
    owns_upload_key,
    result_key,
)

log = logging.getLogger("spip.worker")

METRICS = os.environ.get("SPIP_METRICS", "config/metrics.yaml")
RULES = os.environ.get("SPIP_RULES", "config/peer_rules.yaml")
VALID_SCOPES = {"asset", "portfolio"}


class InvalidEnvelope(Exception):
    """Message body does not describe a job we can process."""


def parse_envelope(body: str | dict) -> dict:
    """Validate before touching storage; malformed messages must not be acked."""
    try:
        data = json.loads(body) if isinstance(body, str) else dict(body)
    except (ValueError, TypeError) as exc:
        raise InvalidEnvelope(f"message is not JSON: {exc}") from None
    for field in ("job_id", "tenant_id", "upload_key", "entity_id"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise InvalidEnvelope(f"{field} is required")
    if not owns_upload_key(data["tenant_id"], data["upload_key"]):
        raise InvalidEnvelope("upload_key is outside the tenant's upload prefix")
    if data.get("scope", "asset") not in VALID_SCOPES:
        raise InvalidEnvelope("invalid scope")
    year = data.get("reporting_year")
    if year is not None and not isinstance(year, int):
        raise InvalidEnvelope("reporting_year must be an integer")
    return data


def process_job(
    envelope: dict,
    store: JobStore,
    uploader: S3Uploader,
    lease_seconds: int = 900,
) -> str:
    """Claim and run one job; returns the terminal status if it finished here."""
    job = store.claim(envelope["job_id"], envelope["tenant_id"], lease_seconds)
    if job is None:
        log.info("job %s not claimable (done or leased)", envelope["job_id"])
        return "SKIPPED"

    path = None
    try:
        body = uploader.read(envelope["upload_key"])
        fd, path = tempfile.mkstemp(prefix="spip-job-", suffix=".csv")
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)

        result = analyse_to_contract(
            data_path=path,
            entity_id=envelope["entity_id"],
            metrics_path=METRICS,
            peer_rules_path=RULES,
            reporting_year=envelope.get("reporting_year"),
            scope=envelope.get("scope", "asset"),
            tenant_id=envelope["tenant_id"],
        )
        # Durable result object first, then the terminal row: a crash between the
        # two only causes a retry, never a job that reports SUCCEEDED without data.
        uploader.write_json(
            result_key(envelope["tenant_id"], envelope["job_id"]),
            json.dumps(result, ensure_ascii=False).encode("utf-8"),
        )
        store.finish(job, SUCCEEDED, result=result, error=None)
        return SUCCEEDED
    except (ContractInputError, EntityNotFound) as exc:
        # File-content problems are asynchronous failures, not HTTP errors.
        store.finish(job, FAILED, result=None, error=str(exc))
        return FAILED
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def reconcile_dlq(dlq_url: str, store: JobStore, client=None) -> int:
    """Turn exhausted retries into visible FAILED jobs; return how many."""
    if client is None:
        import boto3

        client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION"))

    reconciled = 0
    while True:
        response = client.receive_message(
            QueueUrl=dlq_url, MaxNumberOfMessages=10, WaitTimeSeconds=0
        )
        messages = response.get("Messages", [])
        if not messages:
            return reconciled
        for message in messages:
            try:
                envelope = parse_envelope(message["Body"])
            except InvalidEnvelope:
                client.delete_message(QueueUrl=dlq_url, ReceiptHandle=message["ReceiptHandle"])
                continue
            job = store.get(envelope["tenant_id"], envelope["job_id"])
            if job is not None and job.status not in (SUCCEEDED, FAILED):
                store.finish(
                    job, FAILED, result=None, error="retries exhausted (dead-letter queue)"
                )
            client.delete_message(QueueUrl=dlq_url, ReceiptHandle=message["ReceiptHandle"])
            reconciled += 1
    return reconciled


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    store, uploader, queue = build_pipeline()
    if uploader is None or queue is None:
        log.error("SPIP_TENANT_DATA_BUCKET and SPIP_JOB_QUEUE_URL are required")
        return 2
    if not isinstance(store, PostgresJobStore):
        log.warning("no SPIP_TENANT_DATABASE_URL; using in-memory job state")

    if "--reconcile-dlq" in argv:
        dlq = os.environ.get("SPIP_JOB_DLQ_URL")
        if not dlq:
            log.error("SPIP_JOB_DLQ_URL is required for reconciliation")
            return 2
        log.info("reconciled %d dead-letter message(s)", reconcile_dlq(dlq, store))
        return 0

    import boto3

    client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION"))
    lease = int(os.environ.get("SPIP_JOB_LEASE_SECONDS", 900))
    once = "--once" in argv
    log.info("worker started on %s", queue.queue_url)
    while True:
        response = client.receive_message(
            QueueUrl=queue.queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20
        )
        for message in response.get("Messages", []):
            try:
                envelope = parse_envelope(message["Body"])
            except InvalidEnvelope as exc:
                # Leave it unacked: SQS redrives it and the DLQ reconciliation
                # reports the failure instead of silently dropping work.
                log.error("invalid message: %s", exc)
                continue

            try:
                status = process_job(envelope, store, uploader, lease)
            except Exception:
                # Transient (S3/SQS/DB): leave the message for redelivery after the
                # visibility timeout; the lease allows the retry to claim it.
                log.exception("transient failure on job %s", envelope.get("job_id"))
                continue

            # Only ack once the job is durably terminal in the database.
            client.delete_message(
                QueueUrl=queue.queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
            log.info("job %s -> %s", envelope["job_id"], status)
        if once:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
