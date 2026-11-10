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

`persist_uploads=false` is deliberate. Raw CSV and result JSON still persist in
S3; uploaded observations are not written back to PostgreSQL. To enable it,
backend/data owners should verify migrations, INSERT/UPDATE grants for the app
role, tenant RLS, unique/upsert keys, retry idempotency and cache invalidation.
They should explicitly approve the writeback behavior; cloud operations then
enables the flag and deploys. A successful one-off report alone is not proof of
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
