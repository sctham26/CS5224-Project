# Tenant upload persistence

Backend source reviewed: `backend-analysis` at `8187786bb8313185624c5914a7d2e2d9a32fda0e` (2026-11-08).

The backend now merges uploaded observations with the tenant-visible stored dataset. With `SPIP_PERSIST_UPLOADS=1`, its worker also upserts the uploaded observations into the tenant database. Computed job reports already go to tenant S3 job prefixes; the new analysis cache is process-local, not a new persistent report store.

Cloud configuration:

- `BackendConfig.persist_uploads` is a strict boolean, default false. Sandbox enables it. Only the worker receives `SPIP_PERSIST_UPLOADS=1`; the HTTP API does not.
- Existing `spip_tenant_app` SELECT/INSERT/UPDATE grants on `app.observation` suffice. No new database-owner, membership-write, public-baseline-write or RLS-bypass privileges are granted.
- The tenant database also needs `004_observation_upsert_key.sql`, previously applied only to the public database. Cloud operations now applies that existing migration to both databases. Existing migration files are unchanged. Creating the unique index fails rather than deleting or guessing how to reconcile duplicate rows.
- Existing RLS constrains reads and writes to `app.tenant_id`; backend stamps uploaded observations with the authenticated tenant.
- The release role gains repository-scoped `ecr:BatchGetImage` for Docker's image-manifest check. This addresses the manifest HEAD 403 in run 42384347203. AWS lists it among [push permissions](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html).

Deployment retains current CloudFormation image parameters. Releasing the backend source remains a separate build/test/image release. A cache reload is governed by backend TTL settings; persistence does not imply immediate cache invalidation across API processes.

Rollback: set `persist_uploads` false and deploy the runtime stack; previously stored observations remain. Keep the tenant index and migration ledger. Do not downgrade image parameters unintentionally.

## Sandbox verification (2026-11-08)

- Existing application role privileges were verified live: SELECT/INSERT/UPDATE on tenant observation. The unique upsert index was absent.
- Applied the unchanged backend migration 004 to the tenant DB with migration-owner credentials and recorded its SHA-256 in `app._cloud_migrations`. No rows were deleted or rewritten.
- Using the deployed worker's application credentials, a rollback-only transaction verified own-tenant INSERT and conflict UPDATE, invisible cross-tenant rows, rejected cross-tenant writes, and no BYPASSRLS. Diagnostic rows were rolled back.
- CDK unit tests: 32 passed. Release/deployment script unit tests: 12 passed. Browser acceptance remains separate.
