# Reliability review — 2026-11-09

Release verification now compares running capacity with desired capacity rather than assuming one task. A fully deployed autoscaled service previously failed verification. Regression test covers healthy scale-out and under-capacity.

Backend release callers must update BOTH the reusable workflow SHA and cloud_ref to the reviewed cloud commit. Existing pinned callers do not automatically receive this fix.

Integration currently disables upload persistence while cloud-config and the deployed worker enable it. Do not override this integration decision silently: confirm the tenant migration 004 and application grants before enabling it in that branch.

Deployment safety: always use the full backend context flags when deploying InfraStack; otherwise its API behaviors are omitted. Keep live image parameter values. Frontend publishing remains an explicit reviewed release; integration checks alone do not publish.

Follow-ups owned jointly with application developers: durable dispatch recovery, DLQ reconciliation, job heartbeat/task protection, resumable browser polling, role enforcement PR #3, authenticated E2E and load testing. Cloud unit tests are not evidence of successful workload scaling or browser acceptance.

## Separate observability addition

The runtime now defines a CloudWatch dashboard (CPU, queue backlog/age, ALB p95, database connections) and SNS-connected alarms for queue age, target 5xx and DLQ messages. Subscribe an approved operations destination to OperationalAlertsTopicArn after deployment; the topic alone does not notify a person. No subscription or message is sent by this change. Additional alarms/dashboard incur AWS charges.

Course acceptance: record a baseline, submit bounded authenticated jobs, capture API/worker desired and running task counts plus queue age and p95, verify every result, then observe drain and scale-in. Compare identical requests on cold/warm caches and different replicas. Do not fabricate results or send invalid messages to the shared queue. RDS remains single-AZ as an explicit cost trade-off; backup restoration, shared result caching and budget thresholds still require separate decisions.
