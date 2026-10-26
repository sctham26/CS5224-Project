# Login module and application authorization contract

Prepared 2026-10-25. Login infrastructure and the browser integration are implemented. Login authenticates an account; it does not grant membership of an organisation. Backend tenant authorization remains to implement.

## Delivered module

- Independent Python CDK `AuthStack`: Cognito user pool, public browser client (no client secret), `spip/access` resource-server scope, managed login v2 and default branding.
- Accounts are invitation-only; self-registration is disabled. Email sign-in, password reset, 12-character password policy and optional authenticator-app MFA are configured. No client-writable tenant/role attribute exists.
- Access/ID tokens last 15 minutes, refresh tokens one day, with rotation (10-second retry grace) and revocation. The pool is retained and deletion-protected.
- `AuthGate` prevents the dashboard/comparison/upload components mounting until signed in. It shows login errors without exposing raw OAuth responses.
- `oidc-client-ts` handles authorization code + PKCE, transaction state and nonce. Tokens live in memory only; sessionStorage holds transient OAuth transaction state. Reloading requires pressing Sign in again; the Cognito browser cookie may avoid another password prompt. No token is written to localStorage, a URL or a repository variable.
- `authenticatedFetch` gets/refreshes an access token and attaches it only to the configured API origin/path. Concurrent requests share one refresh; failed refresh returns to login. POST requests are not automatically retried.
- Logout attempts refresh-token revocation, clears local state and redirects through Cognito logout. Local cleanup/hosted logout still run if revocation fails. Already issued JWTs can remain accepted by signature-only API authorizers until expiry; logout is not an immediate revocation list for every API request.

## Public configuration and registered URLs

Deployed sandbox account `825990809862`, region `ap-southeast-1`:

| Setting / output | Value |
| --- | --- |
| User pool | `ap-southeast-1_frOvkBoAN` |
| `VITE_AUTH_ISSUER` | `https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_frOvkBoAN` |
| `VITE_AUTH_CLIENT_ID` | `6apgo9j7mard1vbfvlaqekcohc` |
| `VITE_AUTH_DOMAIN` | `https://spip-825990809862-ap-southeast-1.auth.ap-southeast-1.amazoncognito.com` |
| API scope | `spip/access` |
| Hosted callback | `https://d10rc41o4pb0h.cloudfront.net/auth/callback` |
| Hosted logout destination | `https://d10rc41o4pb0h.cloudfront.net/` |
| Local callback | `http://localhost:5173/auth/callback` |
| Local logout destination | `http://localhost:5173/` |

These identifiers are public, not credentials. Repository variables feed Vite at build time. A change needs a rebuild; users cannot safely supply arbitrary redirect destinations. No application `/login` password endpoint is required: Sign in redirects to Cognito `/oauth2/authorize`, the registered browser callback exchanges the code at `/oauth2/token`, and Logout uses `/logout`.

The production build fails closed to a configuration screen when settings are absent; setting `VITE_AUTH_MODE=demo` cannot bypass a production build. For local analytics without Cognito, copy `frontend/.env.example` to `.env.local` and explicitly select `VITE_AUTH_MODE=demo`. For real local login, remove demo and fill the three Cognito values above. Keep Vite on port 5173 or register a new exact callback first.

## Frontend integration

The cloud branch includes the frontend team's CSV demo components from `f0fe860`, while preserving shared API URL configuration. Upload remains a local validation demo; login does not make it a real S3 upload.

Existing analytics calls use:

```js
import { authenticatedFetch } from './auth'
import { API_BASE_URL } from './api'
const response = await authenticatedFetch(API_BASE_URL + '/analysis/A001?scope=asset&reporting_year=2024')
```

The comparison component uses the equivalent relative imports. Keep `AuthGate` outside `App`. Do not add passwords/client secrets to React or implement your own token parser to make authorization decisions. UI identity fields are display-only.

When implementing the agreed upload flow, use `authenticatedFetch` for `POST /api/uploads` and `POST /api/jobs`, including `Idempotency-Key` for jobs. Use ordinary `fetch(upload_url, {method:'PUT', headers, body:file})` for the returned S3 URL: **never send the Cognito bearer token to S3**. The signed URL already authorizes that specific PUT.

## Backend authorization contract

For all protected API routes, the browser sends:

```http
Authorization: Bearer <Cognito access token>
```

With `enable_auth=true` and runtime enabled, CDK binds API Gateway to this pool's issuer, browser client ID and `spip/access` scope. Existing API paths/result shapes remain unchanged. The JWT-protected runtime is now deployed with backend commit `27cc9fb`, which implements token checks and database membership lookup; see [cloud API integration](API_INTEGRATION.md) for current verification. A UI gate alone does not secure an API.

Backend must:

1. Validate signature against the issuer's JWKS, exact issuer, expiry, `token_use=access`, expected `client_id` and required scope using a maintained JWT library. Forwarded bearer tokens remain available through the ALB integration; do not trust caller-supplied user/tenant headers.
2. Use verified `sub` as the stable user key. Resolve tenant membership and application permissions from server-controlled records. Email, browser body/query `tenant_id`, and the mere presence of `spip/access` are not tenant membership.
3. For the first version, resolve one active tenant membership per user; deny private operations if none exists. If multiple memberships are later supported, agree an explicit tenant-selection contract and verify membership on every request.
4. Check upload/dataset/job/entity ownership and apply trusted tenant context to each DB transaction with backend-defined RLS. Keep the public dataset read-only for ordinary app requests.
5. Return `401` for missing/invalid/expired credentials; `403` for a valid account without required membership/permission; `404` for absent or inaccessible tenant-owned resource IDs. CORS must allow the registered frontend origin and Authorization header.

No new business endpoint is assumed by this login module. A future backend-owned `GET /api/me` may expose the verified user ID, active tenant and permissions to the UI, but it is **not implemented or reserved in the current gateway routes**. Agree its schema and add the route before using it; do not fabricate tenant membership from ID-token fields.

## Deployment and operation

From `infra/`, with the expected sandbox identity and region:

```bash
uv sync --locked
npm ci
AWS_REGION=ap-southeast-1 AWS_DEFAULT_REGION=ap-southeast-1 npx cdk synth AuthStack --strict --no-lookups -c enable_auth=true -c auth_local_origin=http://localhost:5173
AWS_REGION=ap-southeast-1 AWS_DEFAULT_REGION=ap-southeast-1 npx cdk diff AuthStack --profile sandbox -c enable_auth=true -c auth_local_origin=http://localhost:5173
AWS_REGION=ap-southeast-1 AWS_DEFAULT_REGION=ap-southeast-1 npx cdk deploy AuthStack --profile sandbox -c enable_auth=true -c auth_local_origin=http://localhost:5173 --outputs-file auth-outputs.json
```

Auth deploys independently: it does not start RDS, ECS, ALB or the backend API. Preserve the local-origin context in future updates if local login is still needed. When deploying the backend/runtime and CloudFront API route later, also set `enable_auth=true`; CDK then supplies Cognito issuer/audience/scope from `AuthStack`. Keep the same context flags on future infrastructure updates.

Only an AWS operator with the required Cognito administration permission may invite users. In the Cognito console, open this user pool → Users → Create user, supply the agreed email and send the invitation. The first login changes the temporary password. Do not grant AWS IAM access to app users and do not assign a tenant based solely on an email domain. No user account or invitation is created automatically by this module; do not commit passwords or use real private data for initial tests.

Essentials enables managed login v2; Cognito usage is subject to the account's current pricing/free-tier conditions. No billing exemption is assumed. Optional MFA is a prototype setting; make it required if the team's private-data policy requires it.

## Verification boundaries

Automated checks cover callback single-use initialization, callback rejection/URL cleanup, refresh concurrency/failure, logout cleanup, token destination restrictions, production demo denial, and infrastructure login settings. CI synthesizes both the standalone login stack and the combined auth/data/runtime configuration without deploying backend resources.

Actual invitation, password change, login, refresh and logout with a human account remain an acceptance step until recorded as completed. Backend checks must separately demonstrate no-token rejection, ID-token rejection, wrong issuer/client/scope rejection and cross-tenant denial; this module does not claim those application tests have passed.

References: [Cognito authorization endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html), [API Gateway JWT validation](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html), [oidc-client-ts](https://authts.github.io/oidc-client-ts/).
