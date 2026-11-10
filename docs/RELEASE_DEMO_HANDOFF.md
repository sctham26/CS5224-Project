# Release and demo handoff — 2026-11-10

Verified live image 8a2305a... is tagged for backend commit 7298ec2f68a594b68d09dfca51f3d394fac8328a; run 42447636453 succeeded. The earlier db3f8c5 release failed, but that is not the latest deployed source. The JSON image defaults are bootstrap defaults, not authoritative deployed state: read CloudFormation image parameters and ECR source tags.

This change accepts a stable zero-capacity worker during release verification (API must remain at least one), applies Kiro scale-to-zero and shorter cooldowns, and restores KMS encryption/data-key permissions needed by S3 writers after replacing CDK bucket grants. Prefix-constrained listing still uses tenants/*: this restricts paths, not individual tenants. Application ownership validation and PostgreSQL RLS remain essential.

persist_uploads is disabled for this demo release. CSV objects and computed result JSON remain durable in S3; uploaded observations are not written back to the tenant database. Re-enable only after a dedicated end-to-end grant/migration and upload test. No new database-wide grants are applied here.

Backend pushes must use the updated pinned reusable cloud workflow. Each run records source commit and image digest; success requires completed CloudFormation rollout, matching task revisions and valid desired/running counts, then public routing/auth rejection checks. Those smoke checks do not establish authenticated upload success. Demo acceptance additionally requires a test-tenant login, CSV upload, job completion and a cross-tenant negative check.

## New release provenance

Backend source: be811685ef57de125ec60efdde74a8dfa233eb3c. ECR digest: sha256:783dfcb73834f21846ac602eaab474ebc6c5baff3531b566a98dc77b96b10ce1. Release run: https://github.com/sctham26/CS5224-Project/actions/runs/42655656319 . Sandbox image defaults are refreshed to this release; future automated releases still use live stack parameters and run artifacts as authority. PR #4 was refreshed with the DLQ guard and remains an unmerged proposal for additional dispatch/ack improvements.

The zero-worker smoke test exposed delayed native SQS metrics after dormancy: a queued message did not promptly trigger scale-out. A one-minute EventBridge/Lambda sampler now reads queue attributes and publishes Visible/InFlight/Delayed under SPIP/Scaling. Both scale-out and drain decisions use these fresh metrics. Missing/failed reads publish nothing, never fabricated zero. Native SQS dashboard metrics remain available. This adds a small scheduled Lambda/custom-metric cost and does not constitute a strict startup SLA.

## Verification evidence

- Backend publish run 42655656319: success; ECR tag confirms source be811685ef57de125ec60efdde74a8dfa233eb3c and digest 783dfcb73834f21846ac602eaab474ebc6c5baff3531b566a98dc77b96b10ce1.
- Frontend publish run 42656224972: success; live build-source.json confirms integration 5cdbb4f7cd6a2c721cab7378772c49de6b4fd470.
- One operator smoke task used the API task's real application credentials and an independent cloud-smoke tenant: encrypted S3 upload, durable job enqueue, worker wake-up from zero, analysis and durable result all succeeded (job_567fb1abfa1146b19922d5865492cb97). Observation write-back was disabled. Test objects/job records remain isolated for audit; no application user data was deleted.
- This exercised the internal application pipeline, not a browser/Cognito login: the operator supplied a Principal directly. Public transport and missing/invalid-token rejection checks passed; authenticated browser acceptance and cross-tenant HTTP verification remain separate.
- Native SQS metrics eventually woke the worker but were delayed. The new sampler was invoked successfully and published real queue counters; no faster end-to-end latency SLA is claimed from that invocation alone.
- Backend 118 tests passed; refreshed PR #4 119 tests passed. Cloud 43 tests and release-capacity tests passed. Latest cloud GitHub checks passed.

## Account recreation and tenant access — 2026-11-10

A signed-in Alex account received HTTP 403 from `/entities`. Cognito currently
identifies `alex.jin@u.nus.edu` as `39ca852c-3071-704e-d8ec-b0c10fe01998`;
the previously provisioned subject was `e9caf58c-7091-7041-fd92-01ac1f99d708`.
The old subject resolved to `spip-team`, while the current subject had no active
membership. Cognito group assignment does not provision database membership.

Recovery uses the existing operator-only `membership --sub <current-sub>
--tenant spip-team` command. Verify the subject using Cognito before provisioning;
never automatically grant tenants based only on email or group names. Recreating
an account requires explicitly reprovisioning its new subject. This is a database
access repair, not an image change.

Frontend follow-up: `classifyApiError` currently maps both 401 and 403 to “Please
sign in”. Distinguish invalid credentials (401) from missing tenant authorization
(403), which requires an administrator rather than another login.
