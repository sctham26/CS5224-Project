# Backend–cloud integration contract — proposed v0.1

**2026-10-25 integration update:** This remains the original application proposal. For deployed path mapping, authentication, image/migration operations and frontend responsibilities, use [API integration](API_INTEGRATION.md). Backend commit `27cc9fb` now implements its own upload/job payloads using `upload_key`; use that backend's interface/source for payload details. Cloud routing does not rename those fields.

**Status: application interfaces proposed for team review, not implemented or deployed.** Infrastructure templates and a database bootstrap utility are now available in [Backend deployment](BACKEND_DEPLOYMENT.md); this does not implement the application endpoints. Prepared 2026-10-23 against `ccproj/backend-analysis` commit `721d3ab`. A fresh fetch found no newer backend commit. This document reserves infrastructure-facing interfaces; it does not prescribe ESG file columns, cleaning rules, business tables, or analytical calculations. Examples use fabricated identifiers and placeholder URLs/resources.

## 1. Existing backend and compatibility

The current FastAPI application has `GET /health`, `GET /analysis/{entity_id}` and synchronous multipart `POST /analyze`. It calls `analyse_to_contract(data_path, entity_id, metrics_path, peer_rules_path, reporting_year, scope)` against a local CSV. Configuration uses `SPIP_DATA`, `SPIP_METRICS`, and `SPIP_RULES`.

Keep the existing analytical result object (`entity_id`, `entity_name`, `tenant_id`, `reporting_year`, `peer_cohort`, `metrics`) as the payload of a successful **analysis** job. Backend-owned ingestion results may have a different payload. Preserve the calculation function; add orchestration around it. Current code does not implement authentication, S3 access, durable jobs, queues, or database storage. Its shared `data/_upload.csv` temporary path must become a unique job directory before concurrent processing. A cloud wrapper must assemble authorised public/current-tenant inputs before calling the engine.

Public browser routes below use `/api`; backend routes omit that prefix. CloudFront/API routing must remove exactly the leading `/api` before forwarding. The deployed frontend stack currently has no backend origin; these routes are reservations, not working URLs. Local development can call the backend directly.

## 2. Browser-facing interfaces

All protected endpoints require `Authorization: Bearer <access-token>`. The API validates the token and resolves organisation membership to a tenant ID. Client-provided `tenant_id`, S3 locations, database names, or result paths cannot override that identity.

| Public route | Purpose | Result |
| --- | --- | --- |
| `POST /api/uploads` | Reserve a tenant-owned object and issue an upload URL | `201`: upload instructions |
| `PUT <upload_url>` | Browser uploads bytes directly to S3 | S3 success response; no application processing yet |
| `POST /api/jobs` | Submit an ingestion or analysis request | `202`: stable job ID and status URL |
| `GET /api/jobs/{job_id}` | Read the authorised job's persistent state/result | `200`; other tenants receive `404` |
| `GET /api/analysis/{entity_id}` | Existing read API, with tenant-aware backend lookup added | Existing analysis result contract |
| `GET /api/health` | Existing liveness endpoint | Public minimal liveness, including the internal ALB probe; no proof of database readiness |

The existing synchronous `/analyze` can remain for local compatibility. Do not expose its current unauthenticated form as a production upload path. The API must also authorise existing entity-based reads; the new jobs route alone does not secure them.

### Upload reservation

Request metadata describes bytes, not their ESG schema. These are claims to verify, not evidence that a file is valid. The API/backend team defines allowed formats and size limits; cloud configuration supplies matching CORS/permissions and upload mechanisms. The single-PUT flow below is the first proposed interface; multipart upload is a separate extension if required.

```json
{
  "filename": "report.csv",
  "content_type": "text/csv",
  "size_bytes": 12345
}
```

Example response (300-second expiry is a proposed configurable default):

```json
{
  "upload_id": "upl_example",
  "upload_url": "https://example.invalid/presigned-put",
  "method": "PUT",
  "headers": {"Content-Type": "text/csv"},
  "expires_in_seconds": 300
}
```

The server generates a unique key such as `tenants/<trusted-tenant-id>/uploads/<upload-id>/source`; the original filename is metadata, not the object path. The browser sends the returned signed headers. S3 remains private. A signed URL is a temporary bearer capability, not a one-use token: do not log it or put it in a queue. The upload record binds the ID to its tenant and server-selected object location.

### Job submission

Require `Idempotency-Key: <client-generated-unique-value>`. Scope it to tenant + endpoint, bind it to a request hash, return the same job for an identical retry, and return `409` if the key is reused with a different request.

Supported operations proposed for v0.1:

- `ingest`: backend validates/transforms an uploaded file and decides what to persist. An ingestion result can return a backend-assigned `dataset_id`.
- `analyze`: backend analyses an upload or an authorised dataset. Existing `entity_id`, `scope` and `reporting_year` parameters remain available. The backend defines any additional operation-specific parameters.

An analysis request compatible with the existing engine's parameters:

```json
{
  "operation": "analyze",
  "input": {"upload_id": "upl_example"},
  "parameters": {
    "entity_id": "ALPHA_BLDG_01",
    "reporting_year": 2025,
    "scope": "asset"
  }
}
```

For a prior ingestion, replace `input` with `{"dataset_id":"ds_example"}`. Exactly one input reference is allowed. For ingestion, use `operation: "ingest"` with an upload reference and backend-defined parameters. This does not require all uploads to be CSV: unsupported content becomes a backend validation error.

Before acceptance the API checks reference ownership, required request fields, and upload existence. For uploads it pins the actual S3 version ID so a later reuse of the upload URL cannot change an accepted job's input. Versioning must therefore be enabled. File parsing/business validation happens in the worker.

```json
{
  "job_id": "job_example",
  "status": "PENDING",
  "status_url": "/api/jobs/job_example"
}
```

Persist the job and a dispatch record atomically before returning `202`. A durable dispatcher/outbox sends it to SQS; a send failure must not lose an accepted job. This bookkeeping and its table schema belong to the backend, not to CDK.

## 3. API-to-worker message

Only the trusted API/dispatcher publishes to the work queue. The browser cannot send messages. The dispatcher resolves the upload reference to a versioned S3 object; it does not forward arbitrary client S3 paths or a client-supplied tenant.

```json
{
  "contract_version": "1.0",
  "job_id": "job_example",
  "tenant_id": "tenant_alpha",
  "operation": "analyze",
  "input": {
    "kind": "s3_object",
    "bucket": "example-tenant-data-bucket",
    "key": "tenants/tenant_alpha/uploads/upl_example/source",
    "version_id": "example-s3-version-id"
  },
  "parameters": {
    "entity_id": "ALPHA_BLDG_01",
    "reporting_year": 2025,
    "scope": "asset"
  }
}
```

Dataset jobs instead use `input: {"kind":"dataset","dataset_id":"ds_example"}`. The backend catalog resolves that ID to permitted public/current-tenant data. The worker checks the message against the persisted job's tenant, operation and input; unsupported contract versions fail explicitly. No file contents, credentials, presigned URLs, or SQL appear in messages. Cloud configuration treats `parameters` as an operation-specific JSON object; the backend validates it.

**Proposed trigger choice:** explicit job submission sends through the dispatcher. Do not also enable S3 ObjectCreated → the same work queue for these uploads; uploading bytes alone should not create a second job or guess its analysis parameters. If the team chooses event-driven ingestion later, revise the contract to add correlation and deduplication.

## 4. Job state, results and retries

Proposed states: `PENDING` → `QUEUED` → `RUNNING` → `SUCCEEDED` or `FAILED`. Dispatcher/worker races must not move a running or terminal job backwards. A queue timeout may retry processing; the job may remain `RUNNING` while a lease is recovered.

`GET /api/jobs/{job_id}` checks ownership before returning metadata, errors or results. During processing it returns job ID, status and timestamps. On success it may return the existing analysis JSON under `result`, or issue a short-lived download URL after authorisation for a larger file. The public API never exposes unprotected raw S3 paths.

Example failure:

```json
{
  "job_id": "job_example",
  "status": "FAILED",
  "error": {
    "code": "UNSUPPORTED_FORMAT",
    "message": "This file format is not supported.",
    "retryable": false
  }
}
```

Use `401` for missing/invalid authentication, `404` for absent or inaccessible upload/dataset/job/entity references, `409` for conflicting idempotency-key reuse, and `422` for an invalid request envelope. File-content errors occur asynchronously as `FAILED`, rather than as the earlier `202` request's HTTP error. Do not return internal stack traces or other tenants' metadata.

SQS Standard can deliver a message more than once. Backend processing needs a per-job claim/lease and idempotent database writes/results. Completed jobs must not execute again. Acknowledge only after durable completion/failure recording; transient errors remain eligible for retry. Cloud provides a DLQ; backend/operations must reconcile exhausted messages into visible job failures instead of leaving jobs running forever. Queue visibility/heartbeat and retry thresholds must match measured task duration, not an invented fixed processing time.

Job status is persistent backend state, not the queue depth. Structured logs include job ID and a request/correlation ID, but no raw data, credentials or upload/download URLs.

## 5. Storage and runtime configuration

Proposed topology: one RDS PostgreSQL instance hosting logical databases `spip_public` and `spip_tenant`; these are not two RDS instances. They have separate connection credentials/roles. A normal application role can read public records; only a dedicated public importer can write them. The tenant database contains backend-owned private business data and persistent job bookkeeping. Schema, migrations and import logic remain backend-owned.

| Runtime setting | Meaning | Delivery |
| --- | --- | --- |
| `AWS_REGION` | Deployment region | Non-secret configuration |
| `SPIP_PUBLIC_DATABASE_URL` | Connection to `spip_public` using the intended restricted role | Built at container startup from Secrets Manager-injected credentials |
| `SPIP_TENANT_DATABASE_URL` | Connection to `spip_tenant` using the intended restricted role | Built at container startup from Secrets Manager-injected credentials |
| `SPIP_PUBLIC_DATA_BUCKET` | Source snapshots/releases for public data | Cloud resource output |
| `SPIP_TENANT_DATA_BUCKET` | Private original uploads and file results | Cloud resource output |
| `SPIP_JOB_QUEUE_URL` | Worker job queue | Cloud resource output |
| `SPIP_JOB_DLQ_URL` | Failed-delivery queue for operations | Cloud resource output; not general application send permission |
| `SPIP_UPLOAD_URL_TTL_SECONDS` | Proposed short-lived URL expiry policy | Non-secret configuration |

Retain the existing `SPIP_DATA`, `SPIP_METRICS`, and `SPIP_RULES` for local compatibility while database integration is added. AWS access uses task roles, not long-lived access keys. Database URLs must not enter browser configuration, source control, or ordinary GitHub repository variables.

The runtime injects `SPIP_DB_HOST`, `PGSSLROOTCERT`, `SPIP_PUBLIC_DB_CREDENTIALS` and `SPIP_TENANT_DB_CREDENTIALS`. The supplied entrypoint converts them to the two database URLs and removes the intermediate credential variables before starting the backend. Database credentials are not generated by application code.

Keep original uploaded objects after processing, under an agreed retention/deletion policy. Results can use `tenants/<tenant-id>/jobs/<job-id>/result.json`. S3 file storage and PostgreSQL structured storage coexist; no infrastructure rule automatically converts or deletes source content. `PUBLIC` means shared application data, not internet-readable S3/RDS.

A PostgreSQL connection addresses one database; public/private results must be combined by the backend or another explicitly designed mechanism. Two databases separate public/private datasets, not tenant A from tenant B. Tenant-table RLS, owner checks, trustworthy tenant context, and connection-pool context reset require backend migrations/application code. The app must not use table-owner, superuser or BYPASSRLS credentials. Cloud resource isolation alone cannot establish application-level tenant isolation for a shared worker.

## 6. Ownership and acceptance

| Cloud team | Backend team | Joint agreement |
| --- | --- | --- |
| Private S3, versioning, CORS for approved frontend origins, HTTPS/encryption, scoped IAM | Authenticated upload/job endpoints and presigning | Membership-to-tenant mapping and permitted upload size/type policy |
| Queue, DLQ, runtime environment, network and logs | Dispatcher, worker entry point, job state, retry/idempotency logic | Worker start command, task duration/heartbeat and retry policy |
| Private PostgreSQL, logical-database setup mechanism, secrets and role boundaries | Business tables, migrations, validation, cleaning, imports and analysis | Database grants/RLS and end-to-end isolation tests |

Before declaring integration complete, verify:

1. The API can reserve an object and the browser can upload without sending bytes through the API.
2. An authorised job reaches a worker and exposes persistent progress/result; an invalid file fails clearly without assuming one ESG schema.
3. A retry reuses the same job and a duplicate queue delivery does not duplicate committed work.
4. Tenant A cannot use tenant B's upload/dataset/job ID, read its result, overwrite its S3 object, or access its database rows; test direct object access and reused pooled DB connections too.
5. Ordinary tenant operations cannot write public records, spoof tenant IDs, or choose arbitrary S3 locations. Nonexistent uploads fail before dispatch; an overwrite after submission does not change the pinned input version.
6. Secrets stay server-side; the original file remains available under the agreed retention policy.

The backend team needs to confirm the two operation names, proposed HTTP paths/state names, worker launch command, and opaque input/result-reference handling. Metric definitions and table schemas are deliberately outside this interface proposal. The cloud templates reserve the listed runtime routes but the backend must implement their behavior. No resources are deployed by accepting this Markdown alone.

References: [S3 presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html), [SQS at-least-once delivery](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html), [PostgreSQL database connection boundaries](https://www.postgresql.org/docs/current/manage-ag-overview.html), [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).
