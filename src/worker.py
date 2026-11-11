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

import pandas as pd

from contract import (
    ContractInputError,
    EntityNotFound,
    analyse_dataframe_to_contract,
)
from datastore import CsvDataSource, DataSource, build_data_source
from import_baseline import REQUIRED_COLUMNS, ImportError_, prepare_rows, load as load_observations
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


#: Same natural key as the importer's upsert (migrations/004): a re-upload
#: replaces the stored observation for that entity, year, scope and metric.
_UPSERT_KEY = ("entity_id", "reporting_year", "reporting_scope", "metric_code")

_datasource: DataSource | None = None


def _data_source() -> DataSource:
    """Built once per process so the TTL cache survives across jobs."""
    global _datasource
    if _datasource is None:
        _datasource = build_data_source()
    return _datasource


def stored_frame(tenant_id: str):
    """Rows the tenant may already see, or ``None`` when nothing is stored here.

    The worker also runs where no database is configured; benchmarking against the
    upload alone then keeps the job working instead of failing it outright.
    """
    source = _data_source()
    if isinstance(source, CsvDataSource) and not source.path.exists():
        return None
    try:
        return source.load(tenant_id)
    except Exception:
        log.exception("stored dataset unavailable; benchmarking the upload alone")
        return None


def _row_key(frame: pd.DataFrame) -> pd.Series:
    """Key as strings, with numeric years normalised (2024 vs 2024.0)."""
    year = pd.to_numeric(frame["reporting_year"], errors="coerce").astype("Int64").astype(str)
    return (
        frame["entity_id"].astype(str)
        + "\x00"
        + year
        + "\x00"
        + frame["reporting_scope"].astype(str).str.lower()
        + "\x00"
        + frame["metric_code"].astype(str)
    )


def merge_upload(stored, uploaded: pd.DataFrame) -> pd.DataFrame:
    """Stored rows (peer cohort) plus uploaded rows (target); the upload wins.

    Overlap is removed from the stored frame on the importer's upsert key, so a
    re-uploaded building corrects its own observation instead of appearing twice.
    """
    if stored is None or stored.empty:
        return uploaded
    if not set(_UPSERT_KEY) <= set(uploaded.columns):
        # Engine-format upload; its columns are not the stored long table's.
        log.warning("upload is not in the team long format; stored rows not merged")
        return uploaded
    keep = ~_row_key(stored).isin(set(_row_key(uploaded)))
    return pd.concat([stored[keep], uploaded], ignore_index=True)


def _has_target(uploaded: pd.DataFrame, entity_id: str, reporting_year: int | None) -> bool:
    """The uploaded file must actually contain the record being analysed."""
    if "entity_id" not in uploaded.columns:
        return False
    hit = uploaded["entity_id"].astype(str) == entity_id
    column = "reporting_year" if "reporting_year" in uploaded.columns else "reporting_period"
    if reporting_year is not None and column in uploaded.columns:
        hit &= pd.to_numeric(uploaded[column], errors="coerce") == reporting_year
    return bool(hit.any())


def persist_upload(uploaded: pd.DataFrame, tenant_id: str) -> int:
    """Write the upload into the tenant's own observations (opt-in).

    RLS keeps these rows visible only to that tenant, so this makes a one-off
    analysis re-runnable and gives the tenant a multi-year trail; it does not add
    anything to the shared cohort.
    """
    if os.environ.get("SPIP_PERSIST_UPLOADS", "") != "1":
        return 0
    url = os.environ.get("SPIP_TENANT_DATABASE_URL")
    if not url:
        log.warning("SPIP_PERSIST_UPLOADS is on but SPIP_TENANT_DATABASE_URL is unset")
        return 0
    if not set(REQUIRED_COLUMNS) <= set(uploaded.columns):
        log.warning("upload is not in the team long format; not persisted")
        return 0
    try:
        rows = prepare_rows(uploaded, tenant_id=tenant_id)
    except ImportError_ as exc:
        raise ContractInputError(f"cannot persist upload: {exc}") from None
    return load_observations(rows, url, tenant_id=tenant_id)


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

        try:
            uploaded = pd.read_csv(path)
        except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
            raise ContractInputError(f"unreadable CSV: {exc}") from None

        year = envelope.get("reporting_year")
        if not _has_target(uploaded, envelope["entity_id"], year):
            raise EntityNotFound(
                f"entity {envelope['entity_id']} is not in the uploaded file"
                + (f" for {year}" if year is not None else "")
            )

        # The upload supplies the target; the stored dataset supplies the peers,
        # so a single building's file can still be benchmarked.
        result = analyse_dataframe_to_contract(
            df=merge_upload(stored_frame(envelope["tenant_id"]), uploaded),
            entity_id=envelope["entity_id"],
            metrics_path=METRICS,
            peer_rules_path=RULES,
            reporting_year=year,
            scope=envelope.get("scope", "asset"),
            tenant_id=envelope["tenant_id"],
        )

        # Before the result write, so SUCCEEDED means the rows are also stored.
        persist_upload(uploaded, envelope["tenant_id"])
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
            if job is None or job.status not in (SUCCEEDED, FAILED):
                # A DLQ receipt is not proof that the logical job failed: another
                # delivery may still be processing it. Retain for operator review.
                log.warning("retain non-terminal or unknown DLQ job %s", envelope["job_id"])
                return reconciled
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

            # A duplicate may belong to a worker holding a live lease.
            # Leave it retryable unless a durable terminal state is confirmed.
            current = store.get(envelope["tenant_id"], envelope["job_id"])
            if current is None or current.status not in (SUCCEEDED, FAILED):
                continue
            client.delete_message(
                QueueUrl=queue.queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
            log.info("job %s -> %s", envelope["job_id"], status)
        if once:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
