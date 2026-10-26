# SPIP React Frontend

The frontend is the React user interface for the CS5224 Sustainable Property
Intelligence Platform (SPIP). It provides an ESG dashboard, a property
comparison view, and a CSV upload interface currently running in local demo
mode. The frontend is a project prototype; this README does not imply that the
platform is deployed end to end.

## Implementation status

| Area | Status |
|---|---|
| Dashboard and Property Comparison frontend | Implemented; uses the local Analytics API |
| Frontend–Analytics API integration | Locally tested against FastAPI on port 8000 |
| CSV upload | Demo-only frontend component; validates filename extension and non-empty file, but does not upload or process it |
| Authentication and AWS/S3 ingestion | Pending integration; no authentication or presigned S3 upload workflow is implemented here |

## Technology stack

- React 19 and React DOM
- Vite 8 for local development and production builds
- Recharts for the property-comparison chart
- ESLint with React Hooks and React Refresh plugins

Install the dependencies declared in `package.json` using npm. No frontend test
runner or test script is currently defined.

## Implemented features

### ESG Dashboard

The Dashboard and Comparison Tool share an asset-level entity list loaded
using `GET /entities?scope=asset`. Portfolio-level entities are excluded from
property selection. The Dashboard provides a searchable property selector
whose options show the building name and entity ID, plus reporting-year options
from that entity's `reporting_years`. A newly selected property defaults to
its `latest_reporting_year` when available. It shows the energy intensity
metric and its peer median, percentile, and gap status, plus peer-cohort
details, an ESG metrics table, and flagged gap-analysis recommendations when
present. Loading, empty-list, missing-year, and request-error states are
displayed in the UI.

### Property Comparison Tool

The comparison page lets users choose two different properties from the same
searchable, asset-level entity list as the Dashboard, a reporting year shared
by both properties, and an ESG metric. It retrieves both properties from the
Analytics API and displays the metric values, a chart and a comparison summary
when the selected values are comparable. It displays an unavailable message
instead of presenting a direct numerical comparison when the selected metric
is missing or incompatible.

### CSV upload interface

The Upload Data page lets the user select a CSV file, displays its filename and
size, and rejects files that do not have a `.csv` filename extension or have
zero bytes. The Upload button is enabled only for a selected file that passes
those checks.

This is a demo-only frontend component, not a completed upload workflow. The
handler is currently a local demo: clicking Upload shows a brief loading state
and then a message that the file passed local validation only. The file is
**not** sent to a server, stored, or processed. The interface does not parse
CSV contents, validate headers or rows, impose a file-size limit, or verify
that the selected file's contents are actually CSV data. A template download
is not yet provided; the frontend template still needs to be aligned with the
agreed project input schema.

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

The Dashboard and Comparison pages make requests to the local Python Analytics
API at `http://localhost:8000`. Start that API separately using its own
worktree. From PowerShell, create a virtual environment and use its Python
executable directly (activation is not required):

```powershell
Set-Location 'C:\path\to\CS5224-Backend'
python -m venv .venv

.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m uvicorn api:app --app-dir src --port 8000
```

If the API is unavailable, the frontend displays request errors. Since Vite
serves the frontend on a different local origin, the API must allow browser
requests from that origin (CORS).

## Analytics API integration

The source currently makes `GET` requests in these forms:

```
http://localhost:8000/entities?scope=asset
http://localhost:8000/analysis/{entityId}?scope=asset&reporting_year={year}
```

- The Dashboard fetches the entity list once; both the Dashboard and
  Comparison Tool use this shared response for their property selectors.
- `scope=asset` limits the selection list to asset-level/building entities;
  portfolio-level entities are excluded from both selectors.
- The entity-list response contains `count`, `tenant_id`, and `entities`.
  Each entity provides `entity_id`, `entity_name`, `postal_code`,
  `property_type`, `region`, `scope`, `reporting_years`, and
  `latest_reporting_year`. The UI uses the entity IDs and reporting years
  returned by the API and does not hardcode tenant identity.
- `{entityId}` is URL-encoded by the client. The dashboard sends the selected
  `entity_id`; the comparison page sends one request for each selected ID.
- `scope` is set to `asset` for both the entity-list and analysis requests.
- `reporting_year` is selected from the entity's available years; comparison
  only offers years present for both selected entities.
- A non-success HTTP response is treated as an error; successful responses are
  read as JSON.

Based on the fields accessed by the UI, the JSON response is expected to
provide `entity_id`, `entity_name`, `reporting_year`, and a `metrics` array.
Metric entries are read for `metric_code`, `standardised_value`,
`canonical_unit`, `comparability_status`, `performance_direction`,
`benchmark.peer_median`, `benchmark.empirical_percentile`, and
`gap_analysis` fields including `is_flagged`, `gap_type`, and
`recommendation_signal`. The dashboard also reads `peer_cohort` fields
including `property_type`, `region`, `sample_size_n`, `fallback_applied`, and
`fallback_reason`. This describes what the frontend consumes; it is not a
replacement for a confirmed API contract.

## Local Integration Verification

In local testing, the frontend connected to the separately running FastAPI
Analytics API on port `8000`; `GET /entities?scope=asset` returned an
asset-only entity list, and the selected analytics requests returned HTTP
`200`. Switching properties refreshed the dashboard data, and the Comparison
page rendered comparison visualisations for comparable results. The CSV
page's demo validation was also tested: valid non-empty `.csv` selections
enabled the button and showed the local demo result, while non-CSV and empty
files were rejected. The CSV demo did not upload, store, or process files.
This documents locally tested functionality only; it does not mean the
platform is deployed end to end or that authentication/AWS integration is
implemented.

## Planned integration and dependencies

The CSV interface is not yet connected to a backend upload API. Cognito
authentication and AWS integration are not implemented in this frontend. A
future presigned S3 upload flow is planned, but is not implemented: no signing
endpoint, upload URL, or direct S3 request is configured here. Integration
depends on confirming the backend API contract, including how an authorized
upload URL is requested, how the frontend template aligns with the agreed CSV
input schema, what metadata is required, how validation and upload errors are
reported, and how successful uploads are confirmed. Until these details are
implemented, keep the page in demo mode; do not treat its local demo message
as a completed upload. AWS/Cognito/S3 integration is pending, not part of the
locally verified frontend–FastAPI analytics integration.

Other current dependencies and limitations:

- The property list and reporting years are fetched from the local Analytics
  API when the frontend loads.
- Analytics requests use a hard-coded local API base URL. No environment-based
  API configuration or Vite proxy is configured.
- Analytics data is required to display dashboard and comparison results; the
  frontend does not provide an end-to-end deployed backend or deployment
  configuration.
- No automated frontend test suite is currently configured.

## Build and lint

Run these commands from the `frontend` directory:

```powershell
npm.cmd run lint
npm.cmd run build
```

To serve the production build locally after building:

```powershell
npm.cmd run preview
```
