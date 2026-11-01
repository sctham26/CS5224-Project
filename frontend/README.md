# SPIP React Frontend

The frontend is the React user interface for the CS5224 Sustainable Property
Intelligence Platform (SPIP). It provides a dashboard, a property comparison
view, and a CSV upload workflow built around the shared authenticated API client.
This README describes the current implementation in the checked-in frontend
source and automated tests; it does not claim a deployed CloudFront frontend or
live AWS end-to-end upload verification.

## Implementation status

| Area | Status |
|---|---|
| Dashboard and Property Comparison | Implemented; shared asset-level entity catalogue and property/year selection flow |
| Frontend–Analytics API integration | Implemented; production uses `/api`, while local dashboard/comparison data loading was previously validated against a separately running FastAPI API on `http://localhost:8000` during development |
| Entity catalogue error handling | Implemented; loading, empty, auth, network/API states and `Retry` are surfaced in the UI |
| CSV upload workflow | Implemented in the frontend client code and Vitest tests: `/uploads` reservation, presigned S3 PUT, `/jobs` submission with `Idempotency-Key`, polling and result handoff |
| Authentication flow | Implemented with Cognito/OIDC and `authenticatedFetch`; demo mode exists for local development |
| Live browser-to-AWS upload processing | Not yet verified in the repository; live AWS upload success is still pending explicit evidence |

## Technology stack

- React 19 and React DOM
- Vite 8 for local development and production builds
- Recharts for the property comparison chart
- ESLint with React Hooks and React Refresh plugins
- Vitest for frontend unit tests

## Property selection and dashboard behaviour

The dashboard and comparison pages share an asset-level entity catalogue loaded
from `GET /entities?scope=asset`. The UI fetches the list once, filters to the
asset scope, and renders a searchable selector that shows each property's name
and entity ID. The reporting-year selector is populated from that entity's
`reporting_years`, and a newly selected property defaults to
`latest_reporting_year` when present.

The same selection model is used in the CSV upload page, where the user chooses a
property and a reporting year as the upload target before selecting a file. The
upload form keeps the current target value separate from the dashboard's shared
state and only updates the target selectors when the catalogue data changes in a
safe, non-destructive way.

The dashboard also handles these UI states explicitly:

- loading the entity catalogue while the request is in flight
- empty result sets when the API returns no entities
- invalid/expired authentication
- network/API failures with a clear error message
- missing or unavailable reporting years for a selected property

## CSV upload workflow

The Upload Data page uses the real presigned-S3 upload flow implemented in the
frontend client, not the older local validation-only demo. The current flow is:

1. Reserve an upload slot via `POST /uploads` using the authenticated API client.
2. Receive a presigned URL and storage key from the backend.
3. Upload the selected CSV file with a direct `PUT` to the signed URL.
4. Submit a processing job via `POST /jobs` with the `Idempotency-Key` header.
5. Poll `GET /jobs/{job_id}` until the job reaches `SUCCEEDED` or `FAILED`.
6. Hand the successful analytics result back to the app and switch to the dashboard.

This logic is implemented in the shared upload handler and is exercised by the
Vitest suite. The UI also reports upload progress and backend errors while the
job is queued and processed.

The upload page validates that the selected file is a non-empty `.csv`, prevents
submissions while the request is in progress, and shows progress states such as
`Reserving...`, `Uploading...`, `Queued...`, and `Processing...`. On a backend
failure, the error message returned by the job is surfaced to the user. The
retryable entity catalogue request is separate from the upload job itself and uses
its own `Retry` action.

## Error handling and retry behaviour

The frontend distinguishes between different failure modes when loading the
entity catalogue and analytics data:

- loading state: request in flight
- empty state: valid response contains no asset entities
- authentication failure: expired, missing or invalid access token
- network failure: the API is unavailable or the browser cannot reach it
- API failure: non-OK HTTP response or invalid payload from the backend

The `App` component stores a structured `entitiesError` object and passes it to
`CsvUpload`. When the catalogue request fails, the upload page shows a clear
error and a `Retry` button that reissues `GET /entities?scope=asset` using the
existing authenticated client. This keeps the fetch path consistent with the
existing Cognito login and token refresh logic.

## Authentication and API configuration

The frontend reads its API base URL from `frontend/src/api.js`:

```js
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? 'http://localhost:8000' : '/api')
).replace(/\/+$/, '')
```

This means:

- local development defaults to `http://localhost:8000`
- production builds default to `/api`
- `VITE_API_BASE_URL` can override either mode at build time

All protected requests use `authenticatedFetch` from the shared auth module. The
function adds the Cognito access token and only sends it to URLs under the active
`API_BASE_URL`, while preserving the existing login/logout flow and token refresh
behaviour. Local demo mode remains available via `VITE_AUTH_MODE=demo`, but the
production build fails closed if the required Cognito configuration is missing.

See the detailed documentation in [../docs/AUTH_CONTRACT.md](../docs/AUTH_CONTRACT.md)
and [../docs/API_INTEGRATION.md](../docs/API_INTEGRATION.md).

## Run locally on Windows

Install a Node.js/npm version compatible with the Vite version in
`package.json`. From PowerShell:

```powershell
Set-Location 'C:\path\to\CS5224-Project\frontend'
npm.cmd install
npm.cmd run dev
```

Vite prints the local development URL in the terminal (normally
`http://localhost:5173`). Open it in a browser. In PowerShell, use `npm.cmd`
if the execution policy prevents running the `npm.ps1` script; in Command
Prompt, the usual `npm` commands can be used.

For local dashboard and comparison testing, a separate FastAPI service can run on
`http://localhost:8000`. Earlier local analytics verification was performed with
a separately running backend on that port. In this Windows environment, direct
Python backend validation was restricted by Windows Smart App Control, so the
current upload workflow is verified through the frontend's mock-based tests rather
than a local end-to-end Python run.

## Testing

Run the frontend tests from the `frontend` directory:

```powershell
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

The current Vitest suite covers:

- entity catalogue loading and error states
- retry behaviour for the asset catalogue request
- successful recovery after a transient failure
- CSV upload progress, validation and job polling flow
- selection and target-year handling for upload property/year choices
- a state-preservation case ensuring catalogue refreshes do not discard a selected file or active upload progress

To preview the production build locally after building:

```powershell
npm.cmd run preview
```

## Limitations and verification status

Important limitations of the current repository state:

- The frontend does not claim a successful live browser-to-AWS upload processing run.
- The checked-in repo contains frontend tests for the upload client flow and retry behaviour, but not a verified live end-to-end upload to AWS.
- The current branch has not been confirmed as deployed to CloudFront in this repository state.
- Earlier local checks against the Python Analytics API are separate from the newly mock-tested upload workflow and must not be interpreted as a verified live upload run.

This means the implementation status is: frontend functionality is in place and
covered by automated tests, local API integration has been validated for the
analytics routes, and live AWS processing remains unverified until explicit
operational evidence exists.

## Related documentation

- [../docs/AUTH_CONTRACT.md](../docs/AUTH_CONTRACT.md)
- [../docs/API_INTEGRATION.md](../docs/API_INTEGRATION.md)
- [../docs/FRONTEND_DEPLOYMENT.md](../docs/FRONTEND_DEPLOYMENT.md)
