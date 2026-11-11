# Admin alerts and remaining backend work

## Minimal cloud change (2026-11-10)

The existing operational SNS topic now subscribes `alex.jin@u.nus.edu` and
`auxane.baptiste@u.nus.edu`, configured by `alert_emails` in
`infra/backend.sandbox.json`. Each recipient must confirm the AWS subscription
email before delivery is enabled. This includes existing queue-age, API-error,
and dead-letter alarms.

New sampler alarms notify the same topic on ALARM and recovery (OK):

- Lambda Errors: at least one error in a one-minute period (includes timeouts).
- Lambda Throttles: at least one throttle in a one-minute period.
- Missing samples: any of Visible, InFlight or Delayed absent in each of five
  consecutive one-minute periods. Empty queues emit zero and are healthy.
  Missing samples are filled with -1 before testing presence, so an idle queue
  is not mistaken for an unavailable sampler. Detection is approximately five
  minutes plus CloudWatch evaluation/notification delay.

These alarms detect failures; they do not restart services or alter worker
scaling. Do not disable the live sampler to test during a demo. After confirming
both subscriptions, an explicitly labelled SNS test can verify delivery.

## Backend coordination: large files

A single file still runs in a single worker. The worker reads the full S3 object
and then creates a pandas DataFrame. Four workers improve concurrent jobs, not
one oversized job. Before submission, agree and enforce a tested maximum file
size (server-side object-size validation before download, with a clear error).
A frontend-only size limit is insufficient.

For tasks that can exceed 840 seconds, implement periodic renewal of BOTH the
PostgreSQL job lease and SQS visibility timeout. Renewal must verify lease
ownership and stop committing results after ownership is lost. Also ensure
retry, duplicate delivery and worker termination cannot lose or double-commit
work. Cloud config currently uses 840-second leases / 900-second visibility;
cloud operations can adjust these once the backend contract is agreed.

Streaming S3 reads / chunked processing can reduce memory later, but chunking
must preserve the analytical semantics (especially peer cohorts/percentiles).
No MapReduce or analytical rewrite is included in this change.

## Backend coordination: upload persistence and authorization

`persist_uploads=true` is now enabled by project-owner request (2026-11-10).
Raw CSV and result JSON remain in S3. Supported uploads are also written to
tenant PostgreSQL observations. For application acceptance,
backend/data owners should verify migrations, INSERT/UPDATE grants for the app
role, tenant RLS, unique/upsert keys, retry idempotency and cache invalidation.
Cloud operations owns deployment and runtime database permissions; backend/data
owners verify writeback semantics and application acceptance. A successful one-off report alone is not proof of
correct observation persistence.

Cognito groups and database membership are separate. For the final demo, cloud
operators can explicitly provision reviewed user subjects into approved tenants;
no backend change is needed for that manual process. Automatic invitation
acceptance/account provisioning requires a backend authorization path to write
membership under a controlled role. Administrator/backend/tester capabilities
also require backend enforcement; Cognito group assignment alone is insufficient.
Do not grant a shared tenant automatically based only on an email or group name.

Authenticated end-to-end release tests remain owned by the designated team
member. This change does not replace those tests.

### Writeback activation verification — 2026-11-10

Deployed `persist_uploads=true` to BackendRuntimeStack; the worker service is
stable on task definition `BackendRuntimeStackWorkerTaskB864145B:21` with
`SPIP_PERSIST_UPLOADS=1`. API and worker image digests were preserved.

An isolated one-off task using this worker definition called the existing
`worker.persist_upload` with two valid baseline-format observations:

- Tenant: `writeback-check-98775c53fccd` (test-only, not assigned to a user).
- First write: 2 observations committed.
- Repeated write: still 2 observations, confirming the upsert path for this sample.
- A different tenant context could see 0 of those observations.
- Test task: `3d2e44a71b6c438386a21aea7551e260`.

The two test observations are retained in their isolated tenant for audit.
This verifies deployed write permissions, the sample upsert and RLS read isolation;
it is not a browser upload E2E test or exhaustive validation of all CSV formats.
Unsupported formats can still be skipped by backend persistence logic.
Infrastructure tests: 45 passed. Public API health/negative-auth checks passed.
