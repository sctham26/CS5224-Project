# Upload retry integration — 2026-11-09

Previously, retry kept the idempotency key but changed the S3 upload key, producing a backend 409. The component now retains an attempt: after successful PUT it reuses the upload key, and after job creation it resumes polling the same job. Changing file/entity/year starts a new attempt. Attempts remain in component memory, not durable browser history; page reload recovery is still outstanding.

Polling now allows three minutes. Exhausting that window reports pending rather than claiming the backend job failed; Retry resumes the existing job. Backend PR #4 separately repairs uncertain queue dispatch. No cloud deployment or persistence setting is changed by this frontend commit.
