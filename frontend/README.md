# SPIP React Frontend

The SPIP frontend is a React application for viewing and comparing property ESG
analytics. This document describes the current frontend implementation and
separates verified checks from incomplete or unverified integration.

## Implementation status

| Area | Status | Details |
|---|---|---|
| Dashboard | Implemented | Loads asset entities, lets users search and select a property, and displays its analytics for an available reporting year. |
| Property Comparison | Implemented | Compares two distinct asset entities for a shared reporting year and selected metric. |
| Cognito authentication | Integrated | `AuthGate` handles sign-in and sign-out. Protected API requests use the Cognito access token. |
| Shared API configuration | Implemented | `src/api.js` reads `VITE_API_BASE_URL`; defaults to `http://localhost:8000` in development and `/api` in production. |
| CloudFront | Static site deployed; API checks verified | The recorded release and website checks succeeded. CloudFront `/api/health` returned 200; protected entities requests without a token or with an invalid token returned 401. Authenticated browser-to-API end-to-end functionality has not been verified. |
| CSV upload and processing | Demo-only | The page checks the filename extension and that the file is non-empty. Real presigned S3 upload and job processing are pending. |

The CloudFront deployment record is dated 2026-10-22 and identifies the
released source commit in [frontend deployment notes](../docs/FRONTEND_DEPLOYMENT.md).
That record does not establish that this worktree's latest frontend changes
have been published. The later API health and authentication rejection checks
verify reachability and negative-auth behavior only; they do not prove that an
invited user's access token works end to end in the frontend.

## Dashboard and comparison

The Dashboard and Comparison pages share an asset-only property list fetched
with `GET /entities?scope=asset`. Portfolio entities are not offered. Both
pages use searchable property selectors. The Dashboard offers the selected
property's available reporting years and defaults to its latest available
year; Comparison offers the years shared by its two selected properties.

The Dashboard requests the selected property's analytics using
`GET /analysis/{entity_id}?scope=asset&reporting_year={year}`. Comparison
requests the same endpoint for each selected property and only presents a
numeric comparison when the metric values are compatible. The API supplies
the entity list and reporting years; the frontend does not hardcode them.

**Known limitation:** when fewer than five eligible peers exist, the
performance-gap display may misleadingly show **“Not Flagged”**. Backend and
frontend handling of this case still needs correction.

## Authentication and API requests

`src/main.jsx` wraps the application in `AuthGate`. In normal mode, the
dashboard and its API requests are unavailable until Cognito sign-in completes.
The Cognito flow uses authorization code with PKCE via `oidc-client-ts`.
`authenticatedFetch` obtains the access token and sends it only to the
configured API origin/path; it refuses to send credentials to other origins,
including a presigned S3 URL.

All frontend API calls share the base URL from `src/api.js`:

| Build environment | Default API base |
|---|---|
| Vite development | `http://localhost:8000` |
| Production build | `/api` |

Set `VITE_API_BASE_URL` to override either default at build time. Vite
environment variables are public and must not contain secrets.

For local unauthenticated development, copy `frontend/.env.example` to
`frontend/.env.local`; it selects the development-only `VITE_AUTH_MODE=demo`.
The frontend `.gitignore` excludes `*.local`, but **do not commit `.env.local`**
or put credentials/secrets in it. For real local Cognito sign-in, remove demo
mode and provide `VITE_AUTH_ISSUER`, `VITE_AUTH_CLIENT_ID`, and
`VITE_AUTH_DOMAIN`; the registered local callback uses
`http://localhost:5173/auth/callback`. See the [authentication contract](../docs/AUTH_CONTRACT.md).

## Local setup on Windows

Install a Node.js version compatible with the Vite version in `package.json`.
In PowerShell, from the repository checkout:

```powershell
Set-Location 'C:\path\to\CS5224-Docs\frontend'
npm.cmd ci
Copy-Item .env.example .env.local
npm.cmd run dev
```

Open the Vite URL printed in the terminal (normally
`http://localhost:5173`). `npm.cmd` avoids PowerShell execution-policy issues
with `npm.ps1`. The demo environment skips Cognito only for local development.

## Local FastAPI integration verification

Run the FastAPI analytics service in a second PowerShell window. From the
repository root:

```powershell
Set-Location 'C:\path\to\CS5224-Docs'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn api:app --app-dir src --port 8000
```

The local API uses the CSV data source by default and allows local auth
verification to remain disabled unless configured otherwise. Check its
reachability and asset list from another PowerShell window:

```powershell
Invoke-RestMethod 'http://localhost:8000/health'
$entities = Invoke-RestMethod 'http://localhost:8000/entities?scope=asset'
$entities.entities | Select-Object entity_id, entity_name, reporting_years
```

With the frontend running in local demo mode, open Dashboard and Comparison.
Select properties and years from the API response and confirm that the
analytics requests render results. If requests fail in the browser, check that
the API is running on port 8000 and that its CORS allow-list includes
`http://localhost:5173`. These are verification steps, not a claim that a local
run was performed for this README update.

## CSV upload: demo only

The CSV page checks only that a selected filename ends in `.csv` and that the
file is non-empty. Its demo handler reports local validation; it does not send,
store, parse, or process the file. This does not validate that the contents
are CSV data. **Real presigned S3 upload and backend job submission/processing
are pending**; do not treat the demo result as a completed upload.

## Tests and production build

Run from `frontend` in PowerShell:

```powershell
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Vitest runs the frontend tests, ESLint checks source, and the production build
is written to `dist/`. To serve that build locally:

```powershell
npm.cmd run preview
```

## CloudFront deployment and verification

The deployment notes record a successful static CloudFront release and checks
of the served HTML, JavaScript/CSS assets, and release metadata. The current
CloudFront API route has also passed `GET /api/health` with HTTP 200 and
protected `GET /api/entities` checks with no token and with an invalid token,
both returning HTTP 401. These checks confirm static hosting, API reachability,
and rejection of missing/invalid credentials.

They do **not** verify sign-in and analytics in an authenticated browser
session, real-user token acceptance, or the complete upload-to-job workflow.
The current frontend publication status must be checked against the recorded
release commit; a successful CloudFront deployment or API health response is
not evidence that the latest worktree has been deployed or that authenticated
end-to-end behavior works. See [frontend deployment evidence](../docs/FRONTEND_DEPLOYMENT.md)
and [cloud API integration status](../docs/API_INTEGRATION.md).
