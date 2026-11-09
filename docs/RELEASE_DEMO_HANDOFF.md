# Release and demo handoff — 2026-11-10

Verified live image 8a2305a... is tagged for backend commit 7298ec2f68a594b68d09dfca51f3d394fac8328a; run 42447636453 succeeded. The earlier db3f8c5 release failed, but that is not the latest deployed source. The JSON image defaults are bootstrap defaults, not authoritative deployed state: read CloudFormation image parameters and ECR source tags.

This change accepts a stable zero-capacity worker during release verification (API must remain at least one), applies Kiro scale-to-zero and shorter cooldowns, and restores KMS encryption/data-key permissions needed by S3 writers after replacing CDK bucket grants. Prefix-constrained listing still uses tenants/*: this restricts paths, not individual tenants. Application ownership validation and PostgreSQL RLS remain essential.

persist_uploads is disabled for this demo release. CSV objects and computed result JSON remain durable in S3; uploaded observations are not written back to the tenant database. Re-enable only after a dedicated end-to-end grant/migration and upload test. No new database-wide grants are applied here.

Backend pushes must use the updated pinned reusable cloud workflow. Each run records source commit and image digest; success requires completed CloudFormation rollout, matching task revisions and valid desired/running counts, then public routing/auth rejection checks. Those smoke checks do not establish authenticated upload success. Demo acceptance additionally requires a test-tenant login, CSV upload, job completion and a cross-tenant negative check.

## New release provenance

Backend source: be811685ef57de125ec60efdde74a8dfa233eb3c. ECR digest: sha256:783dfcb73834f21846ac602eaab474ebc6c5baff3531b566a98dc77b96b10ce1. Release run: https://github.com/sctham26/CS5224-Project/actions/runs/42655656319 . Sandbox image defaults are refreshed to this release; future automated releases still use live stack parameters and run artifacts as authority. PR #4 was refreshed with the DLQ guard and remains an unmerged proposal for additional dispatch/ack improvements.
