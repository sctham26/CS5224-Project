# Application RBAC proposal

**Review target: backend-analysis. Not merged/deployed.** Cognito group assignments are a separate cloud operation; no application user receives AWS console, IAM, deployment or database-login permissions.

| Signed Cognito group | Tenant data operations | Diagnostics / local cache invalidation | User directory / role and membership administration |
|---|---|---|---|
| spip-admin | yes | yes | yes |
| spip-backend | yes | yes | no |
| spip-tester | yes | no | no |
| spip-customer | yes | no | no |

Precedence: admin > backend > tester > customer. Missing/unrecognized groups keep ordinary customer operations for existing users. Malformed group claims fail closed. Roles come only from the already verified access token, never a header, email or request body. All roles still require active tenant membership; existing data routes remain tenant-scoped, including for admins. Administrator is the highest supported application role, not AWS AdministratorAccess or an RLS bypass.

## Endpoints

Backend paths below gain `/api` at CloudFront. All use the existing JWT authentication. Wrong role returns 403; missing/invalid authentication returns 401. Successful identity/ops/admin responses use `Cache-Control: no-store`.

| Method/path | Allowed roles | Behavior |
|---|---|---|
| GET /auth/me | all | subject, tenant, role and permissions |
| GET /ops/status | admin/backend | current tenant's cache count/TTL and pipeline configuration status; no credentials or cross-tenant metadata |
| POST /ops/cache/invalidate | admin/backend | invalidate current tenant's data/report cache in the serving API process |
| GET /admin/users?next_token=... | admin | bounded Cognito directory page (25 users), subject/email/status/enabled and opaque next_token |
| PUT /admin/users/{subject}/role | admin | role = backend/tester/customer |
| PUT /admin/memberships/{subject} | admin | tenant_id plus strict boolean active |

Subjects are UUIDs; tenant IDs follow the existing 1–64 character letters/digits/underscore/hyphen contract. Membership changes update the one existing tenant mapping, not multi-tenant membership. Existing data is not moved or deleted. Directory/role endpoints do not create accounts or send invitations.

Cloud operators retain all administrator-group grants/removals. The API cannot promote anyone to admin, change existing admins' groups, or modify the calling admin's own membership. This preserves an independent bootstrap/recovery path. Non-admin group changes demote first and verify read-back; a failed provider operation may leave a lower-role/no-group state and requires retry. Existing tokens can retain old group claims until expiration (currently 15 minutes); users must refresh/re-login for role changes. Membership deactivation affects subsequent membership lookups.

Cache invalidation is best effort, process-local and tenant-specific: it does not invalidate other API replicas, workers or in-flight calculations. Shared generation-based invalidation is future work. Do not advertise this endpoint as cluster-wide cache flushing.

## Cloud integration required after review

This proposal does not change infrastructure. Coordinate the following before expecting the new endpoints to work live:

1. Add these exact API Gateway routes with the existing authorizer and spip/access scope. Add PUT to gateway CORS. Retain disabled CloudFront API caching. Backend CORS includes PUT here.
2. Inject SPIP_AUTH_USER_POOL_ID into the API service. Grant only that task role the pool-scoped Cognito actions ListUsers, AdminListGroupsForUser, AdminAddUserToGroup and AdminRemoveUserFromGroup. Workers need no directory permissions.
3. Inject a separate TLS-verifying SPIP_MEMBERSHIP_ADMIN_DATABASE_URL from Secrets Manager. Its dedicated login role needs CONNECT/USAGE and SELECT/INSERT/UPDATE only on app.tenant_membership; no table ownership, BYPASSRLS, migration credentials or observation writes. The adapter sets transaction-local app.user_sub to the explicitly authorized target so the existing self-row policy remains enabled. Do not expand ordinary spip_tenant_app grants.
4. Update the pinned cloud release support/entrypoint as needed for that additional secret. Never put a DSN in Vite variables, Git, logs or responses. No migration/dependency declaration changes are introduced here.
5. Missing configuration/provider errors return 503. There is no fallback to ordinary application credentials or a mock admin store. Review infrastructure separately before merging triggers the backend auto-release.

Mutating adapters log actor subject, action and target without credentials or request bodies. CloudTrail provides Cognito-side audit. These interfaces intentionally do not grant shell access, arbitrary SQL, AWS role assumption or cross-tenant data reads.

## Verification

Tests cover verified-claim propagation through a stub validator (the existing JWT validation path remains unchanged), malformed groups, role precedence, normal tenant isolation for every role, forged headers, privileged route denial before adapter calls, local tenant cache invalidation, admin self-protection, protected bootstrap admins, safe provider errors and missing privileged credentials. Existing analytics algorithms, migrations and dependency declarations are unchanged.

Live acceptance remains separate: tester ordinary requests 200 and ops/admin 403; backend ops 200/admin 403; configured admin management requests succeed; all roles remain unable to read another tenant's private data. Real Cognito tokens and cloud-adapter permissions must be verified after acceptance/deployment; unit tests are not live E2E evidence.
