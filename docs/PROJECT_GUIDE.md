# SPIP - Project and Architecture Guide

This secondary guide explains the application, the code available on other branches, and the proposed cloud architecture. For the deployment work plan, start with the [main cloud deployment README](../README.md).

**Current scope:** ESG data upload, harmonisation, property benchmarking, a dashboard, authentication, organisation data isolation, and AWS deployment. The AI assistant is outside the current implementation scope.

## Reading guide

Start with sections 1–2 for the overall picture. Sections 3–4 explain the existing analytics and frontend code in detail. Sections 5–6 describe the proposed cloud implementation. Section 7 covers team responsibilities, and section 8 explains local tools, GitHub, and AWS. Sections 9–10 cover implementation stages and handover evidence. Section 11 lists technical references.

1. [What SPIP does](#1-what-spip-does)
2. [What needs to be deployed: the big picture](#2-what-needs-to-be-deployed-the-big-picture)
3. [Understanding the analytics branch](#3-understanding-the-analytics-branch)
4. [Understanding the frontend branch](#4-understanding-the-frontend-branch)
5. [The proposed user and data journey on AWS](#5-the-proposed-user-and-data-journey-on-aws)
6. [Deployment components in detail](#6-deployment-components-in-detail)
7. [Integration boundaries and team responsibilities](#7-integration-boundaries-and-team-responsibilities)
8. [What lives on a laptop, GitHub, or AWS](#8-what-lives-on-a-laptop-github-or-aws)
9. [Implementation stages](#9-implementation-stages)
10. [Verification and handover](#10-verification-and-handover)
11. [Technical references](#11-technical-references)

## 1. What SPIP does

SPIP helps property organisations compare sustainability observations that may use different units or reporting formats. ESG means environmental, social, and governance; the current analytics examples focus on environmental property metrics.

For example, two properties may report energy intensity as `125 kWh/m2/yr` and `0.125 MWh/m2/year`. These values describe the same annual energy use per square metre. The system must convert them into a common unit before comparing them.

The intended user journey is:

1. A user signs in as a member of an organisation.
2. The user uploads a supported CSV containing property observations.
3. SPIP validates the input and harmonises supported metrics and units.
4. SPIP selects comparable properties, called **peers**, and calculates benchmarks.
5. The dashboard displays standardised values, peer statistics, percentiles, and gaps.

A **performance gap** means a comparable observation performs below an agreed threshold. A **disclosure gap** means information is missing or unsuitable for comparison. An unavailable benchmark can also mean there are too few suitable peers; it does not automatically mean poor performance.

The platform does not currently produce one universal ESG score. Each metric has its own unit, interpretation, comparability rules, and benchmark.

SPIP is intended to be **multi-tenant**: several customer organisations use one application while their private data remains separated.

## 2. What needs to be deployed: the big picture

The frontend and analytics engine already have source code. Cloud deployment must make them accessible, connect them to durable storage, and enforce access rules.

| Capability | Purpose in SPIP | Proposed AWS components | Current repository status |
| --- | --- | --- | --- |
| Serve the website | Let users open the dashboard in a browser | S3 for built frontend files; CloudFront for HTTPS delivery | Frontend source exists; hosting configuration is missing |
| Sign users in | Establish the user's identity and organisation membership | Cognito, with organisation membership checked by the application | Not implemented |
| Expose the API | Provide a reachable address for requests from the website | API Gateway, connected to the backend through a defined network integration | Local API exists; cloud integration is missing |
| Run Python | Execute Song's API and analytics code | ECS with Fargate | Container packaging and runtime configuration are missing |
| Receive source files | Preserve approved public datasets and private uploads | S3, with separate access boundaries | Current backend reads local CSV files |
| Process uploads | Handle work outside the browser request, track progress, and retry failures | SQS and a worker running on Fargate | Queue, worker loop, and processing-status model are missing |
| Store application records | Preserve organisations, standardised observations, and processing state | RDS for PostgreSQL | Schema, database access, and migrations are missing |
| Isolate organisations | Restrict private files and database records to authorised organisations | Application authorisation, S3 policies, and PostgreSQL Row-Level Security | Not implemented |
| Operate the service | Diagnose errors and observe health, workload, and costs | CloudWatch, appropriate IAM roles, and cost monitoring | Not configured in the repository |
| Repeat deployments | Build and release a known code version consistently | Infrastructure as code and, later, GitHub Actions | No infrastructure files or workflows exist |

Permissions, architecture choices, cost, and existing AWS resources must be checked before provisioning anything, because I don't know yet the permissions we currently have.

EventBridge belongs to the earlier proposal for scheduled public-data refreshes. It is conditional on implementing that feature; a manually prepared baseline does not need a refresh schedule. Bedrock and other AI infrastructure are not part of the current plan. Full subscription billing is also outside the core prototype.

## 3. Understanding the analytics branch

### 3.1 What runs, and what it reads

The **backend** is the server-side Python program. Its calculation engine can be called from Python, or through an **API**, an interface that accepts requests and returns structured results. FastAPI defines the HTTP endpoints; Uvicorn runs the web server that receives requests.

At present, the backend reads CSV files on the computer running it. It does not query PostgreSQL or download S3 objects. Moving it to Fargate will not automatically add either capability.

The default dataset is `data/synthetic_esg.csv`: 88 metric observations covering 12 properties and five portfolios, including an older report for property A003. These are demonstration values, not a verified public ESG baseline.

A CSV uses **long format**: one row represents one metric for one entity and reporting period. A property reporting five metrics therefore contributes five rows.

```csv
entity_id,scope,reporting_period,region,property_type,certification,metric,value,unit,source
A001,asset,2024,UK,office,BREEAM,ENERGY_INTENSITY_EUI,118.0,kWh/m2/yr,synthetic-dataset
```

Here, `A001` is a property identifier; `asset` means one property; `2024` is the reporting year; and `118.0` is its reported energy intensity. A `portfolio` represents a collection of assets. This asset/portfolio **reporting scope** is different from the emissions accounting terms **Scope 1** and **Scope 2** used in some metric names.

### 3.2 How a CSV becomes an analysis result

1. **Read and interpret the CSV.** The code accepts the engine format above or the team's common format. The latter uses fields such as `metric_code`, `reporting_year`, `standardised_value`, and `reporting_scope`.
2. **Prepare observations.** The loader groups metric rows into entity reports. The team-format adapter excludes observations with unusable values or non-comparable statuses from benchmarking.
3. **Harmonise units.** The metric dictionary specifies common units and supported conversions. For example, A004's `0.125 MWh/m2/year` becomes `125 kWh/m2/yr`.
4. **Select peers.** For each metric, the current rules try the same property type and region, then the same region, then the same property type, then all eligible entities in the same scope. At least five peers are required. Matching year, metric availability, and supported units also constrain selection.
5. **Calculate benchmarks.** The engine calculates statistics such as the peer median, together with the target's rank and percentile. Performance direction matters: lower energy intensity is desirable, while a higher renewable share is desirable.
6. **Identify gaps.** The current configured percentile threshold is 40. This is a business assumption to confirm, not an independently verified ESG standard.
7. **Return a structured result.** The adapter produces the JSON format used by application callers. JSON is a data format containing named fields, objects, and lists.

For a concrete example, A001 reports energy intensity of `118 kWh/m2/yr`. Its five strict peers have values `132`, `101`, `125`, `145`, and `109` after conversion. Their median is `125`; A001 uses less energy per square metre than that median. This explanation comes from the supplied synthetic rows and saved example, not a new execution of the application.

Different metrics can use different peer groups. A direct comparison of two selected properties is also different from benchmarking one property against a larger group.

Useful vocabulary when reading the code or dashboard:

| Term | Meaning in this project |
| --- | --- |
| Metric | One measured indicator, such as annual energy use per square metre |
| Canonical unit | The agreed reference unit used after conversion |
| Peer cohort | The group of other entities selected for a particular comparison |
| Median | The middle value after sorting the peer values; for five peers, the third value |
| Rank | The target's position when values are ordered by the metric's performance direction |
| Percentile | The engine's direction-aware relative position on a 0–100 scale; higher indicates better performance |
| Fallback rule | A broader selection rule tried when too few peers meet the stricter rule |
| Data contract | The agreed field names, types, and meanings exchanged between components |
| Provenance | Information describing where an observation or result came from |

The threshold of 40 refers to the percentile, not a 40% reduction in energy or emissions. The target itself is excluded from its peer group. If the available peers still do not meet the minimum after fallback, no benchmark is asserted.

### 3.3 File guide

Paths below are relative to the root of `backend-analysis`.

| File | Role |
| --- | --- |
| `README.md` | Introduces the engine, local commands, design decisions, and assumptions |
| `INTERFACES.md` | Describes callable functions, HTTP routes, accepted inputs, and output formats |
| `pyproject.toml` | Defines the Python project, Python 3.10+ requirement, dependencies, and test configuration |
| `requirements.txt` | Lists packages to install; minimum versions are given rather than an exact dependency lock |
| `src/__init__.py` | Contains the package description and version |
| `src/schemas.py` | Defines data models and vocabulary, including reporting scope, metric direction, and observations |
| `src/metrics.py` | Loads the metric dictionary and performs supported unit conversions |
| `src/harmonisation.py` | Loads engine-format CSV rows, groups observations, partitions reporting scopes, and harmonises units |
| `src/peers.py` | Chooses eligible peers using the ordered fallback rules |
| `src/benchmark.py` | Calculates statistics, ranks, and direction-aware percentiles |
| `src/gap_analysis.py` | Calls the analysis stages in order and creates the detailed internal result |
| `src/contract.py` | Adapts the team's CSV format to the engine and converts the result into the team's response format |
| `src/api.py` | Defines the HTTP routes used by callers such as the frontend |
| `config/metrics.yaml` | Declares metric codes, canonical units, conversions, performance directions, scopes, and gap thresholds |
| `config/peer_rules.yaml` | Defines minimum peer count and fallback selection order |
| `data/synthetic_esg.csv` | Provides the default fictional dataset |
| `examples/run_example.py` | Demonstrates a direct Python call and writes an example result |
| `examples/output.json` | Stores an example internal engine result; its format differs from the HTTP response |
| `tests/fixtures_their.csv` | Provides a small example of the team's CSV format |
| `tests/fixtures_unknown_metric.csv` | Provides an invalid metric for error-handling tests |
| `tests/test_schemas.py`, `tests/test_metrics.py` | Check data models, metric definitions, and conversions |
| `tests/test_harmonisation.py`, `tests/test_peers.py` | Check CSV processing, compatibility, and peer selection |
| `tests/test_benchmark.py`, `tests/test_gap_analysis.py` | Check calculations and the combined analytics flow |
| `tests/test_contract.py`, `tests/test_api.py` | Check response adaptation and HTTP behaviour with a local test client |
| `.gitignore` | Excludes generated Python files, local environments, and caches from Git |

### 3.4 Available API and configuration

The routes below exist in the inspected [API source][analytics-api]. They are not published AWS URLs.

| Route | Input | Current behaviour |
| --- | --- | --- |
| `GET /health` | None | Returns `{"status":"ok"}`; checks that the process responds, not database or dataset readiness |
| `GET /analysis/{entity_id}` | Optional query parameters `scope` and `reporting_year` | Analyses the server's configured CSV for that entity |
| `POST /analyze` | Multipart file field `file`; query parameters `entity_id`, optional `scope` and `reporting_year` | Analyses the uploaded CSV and returns results immediately |

`GET` requests retrieve results. `POST` submits input for processing. Query parameters appear after `?` in the URL. The uploaded file is sent in the request body.

The HTTP response includes:

| Field | Meaning |
| --- | --- |
| `entity_id`, `entity_name` | The analysed property's or portfolio's identity |
| `tenant_id` | Organisation metadata; currently not an access-control mechanism |
| `reporting_year` | The analysed year |
| `peer_cohort` | A summary of a selected peer group and any fallback used; it does not describe every metric's exact peer set |
| `metrics[]` | A list of metric results, including values, units, comparability, benchmarks, and gaps |

For each metric, the frontend reads fields including `metric_code`, `standardised_value`, `canonical_unit`, `comparability_status`, `performance_direction`, `benchmark`, and `gap_analysis`.

The API reads three environment variables at startup. An **environment variable** supplies configuration to a program without changing its source code.

| Variable | Default value | Purpose |
| --- | --- | --- |
| `SPIP_DATA` | `data/synthetic_esg.csv` | CSV used by `GET /analysis/{entity_id}` |
| `SPIP_METRICS` | `config/metrics.yaml` | Metric dictionary |
| `SPIP_RULES` | `config/peer_rules.yaml` | Peer selection rules |

### 3.5 Available local commands and current limits

These commands are documented for a checkout containing the analytics files, run from that branch's root. They were **not executed for this guide update** and will not work from the documentation-only `cloud-config` tree.

| Command | What it does and changes |
| --- | --- |
| `python -m pip install -r requirements.txt` | Installs the listed packages into the selected local Python environment; may download packages. Use a project-specific virtual environment to keep dependencies separate. |
| `python -m uvicorn api:app --app-dir src --port 8000` | Starts the local API on port 8000; `api:app` identifies the application, and `--app-dir src` tells Uvicorn where to find it. It runs until stopped and does not deploy anything. |
| `python -m pytest -q` | Runs the test suite with concise output; may create local caches. It does not test AWS deployment. |
| `python examples/run_example.py` | Runs the example analysis and writes `examples/output.json` locally. |

The inspected tree contains 58 test functions. No successful test run, server execution, or AWS deployment is established by this documentation review.

Important integration limits:

- There is no login, token validation, tenant authorisation, S3 access, or database connection.
- `POST /analyze` processes only the uploaded file. It does not automatically combine private uploads with the configured public baseline.
- The upload handler reads the file into memory, writes `data/_upload.csv`, and deletes it afterwards. This shared temporary filename is unsafe for concurrent requests and is not durable storage.
- CORS currently allows all origins. CORS governs which browser origins may call the API; it does not authenticate users or isolate organisations.
- The documentation references shared contract/dictionary files from a team PR that are absent from the inspected branches. Their authoritative versions must be located.
- Analytics rules and edge cases still need review with Song and Nasya. Examples include fallback-policy wording, metric scope applicability, and unsupported canonical-unit combinations. This guide does not certify the engine as production-ready.
- Some analytics documentation still says the frontend uses hardcoded results. The inspected frontend branch already makes API calls; the code and current cross-branch review take precedence over that older statement.

## 4. Understanding the frontend branch

### 4.1 What runs in the browser

The **frontend** is the part users see. It contains JavaScript, HTML, CSS, and images. React describes the screens using components; Vite serves them during development and builds distribution files; Recharts draws the comparison chart.

After deployment, S3 and CloudFront would deliver the built files. The user's browser would then run the JavaScript and call the backend. S3 does not execute the Python engine, and GitHub does not run the website simply because its source is stored there.

The startup sequence is `frontend/index.html` → `frontend/src/main.jsx` → `frontend/src/App.jsx`. When Comparison is selected, `App.jsx` displays `PropertyComparison.jsx`.

### 4.2 File guide

Paths below are relative to the root of `feature/frontend-dashboard`.

| File | Role |
| --- | --- |
| `frontend/package.json` | Lists dependencies and available npm commands |
| `frontend/package-lock.json` | Records the resolved dependency versions for consistent installation |
| `frontend/index.html` | Contains the HTML root element into which React renders the application |
| `frontend/src/main.jsx` | Starts React, loads global CSS, and renders `App` |
| `frontend/src/App.jsx` | Contains navigation, dashboard state, API requests, metric displays, and the upload placeholder |
| `frontend/src/components/PropertyComparison.jsx` | Fetches two properties' results and displays a comparison table, chart, and summary |
| `frontend/src/index.css` | Defines basic global styling |
| `frontend/src/App.css` | Styles navigation, cards, tables, charts, and responsive layouts |
| `frontend/src/assets/`, `frontend/public/` | Contain images and other static assets |
| `frontend/vite.config.js` | Enables the React plugin; currently contains no API proxy or cloud deployment configuration |
| `frontend/eslint.config.js` | Defines JavaScript and React source-checking rules |
| `frontend/.gitignore` | Excludes generated directories such as `node_modules/` and `dist/` |
| `frontend/README.md` | Contains the generic React/Vite template documentation |

### 4.3 What each screen actually does

**Dashboard.** `App.jsx` remembers the selected property, year, loading state, and returned results using React **state**: values that cause the screen to update when they change. It requests analysis when the selection changes and displays loading or error messages as appropriate. Results populate metric cards, a peer-group summary, a metric table, and gap information.

The current property choices are `A001` through `A006`. The year selector currently offers only `2024`. These choices are not fetched from an organisation's database.

**Comparison.** `PropertyComparison.jsx` maintains its own property and metric selections. It requests results for two properties in parallel. Before displaying the chart and difference summary, it checks usable values, comparability status, units, reporting year, and performance direction. The table displays usable values separately; its presence alone does not guarantee that both values are comparable.

The available comparison metrics are energy intensity, Scope 2 carbon intensity, water intensity, renewable share, and waste diversion rate. Recharts displays the returned values; Song's engine calculates the benchmarks.

**Upload Data.** This screen currently displays explanatory text and “File upload functionality coming soon.” There is no file selector, upload request, or processing-status display.

Navigation changes a `currentPage` state value inside the application. Separate browser URL routes are not defined in this version.

### 4.4 What the frontend sends to the backend

The dashboard currently sends a request such as:

```http
GET http://localhost:8000/analysis/A001?scope=asset&reporting_year=2024
```

The comparison tool sends the same kind of request for each selected property. These are real API calls in the source, rather than a fully simulated dashboard. Their success still depends on the API running and returning the expected format.

Both [`App.jsx`][frontend-app] and [`PropertyComparison.jsx`][frontend-comparison] contain the local API address. **`localhost` means the computer running the browser.** Publishing these files unchanged would make visitors look for the API on their own computers. The API address must become configurable for deployment, with the configuration method agreed with Sin Che.

No login, token handling, `Authorization` header, or organisation membership flow is present. The backend must enforce access restrictions even after these are added to the interface.

### 4.5 Available local commands and current limits

These commands apply inside `frontend/` in a checkout containing the frontend branch. They are reference information, not commands executed for this guide update.

| Command | What it does and changes |
| --- | --- |
| `npm ci` | Installs the locked dependencies locally into `node_modules/`, replacing that directory if present; may download packages. |
| `npm run dev` | Starts Vite's local development server. The API must run separately. |
| `npm run build` | Creates the static distribution in `dist/` inside the current directory (`frontend/dist/` relative to the repository root). Building files is separate from uploading them to AWS. |
| `npm run lint` | Checks configured source rules using ESLint; this script does not automatically fix files. |
| `npm run preview` | Serves an existing build locally for inspection. It is not a production deployment. |

Node.js runs the local JavaScript development tools; npm installs packages and runs the declared scripts. A shared Node version still needs to be selected: the inspected branch has no `engines` field or `.nvmrc` version file.

There are no automated frontend tests or deployment files in the inspected tree. Installation, linting, building, and browser behaviour were not tested for this documentation change. Cloud integration still needs a configurable API address, login, upload/status screens, and a way to list the current organisation's available properties and years.

## 5. The proposed user and data journey on AWS

The following journey is a design proposal. None of its AWS connections is implemented by this guide.

### Step 1: open the website

The browser downloads the built React files through CloudFront from a private S3 bucket. These files display the interface; they do not contain private database credentials or execute the analytics engine.

### Step 2: sign in and establish organisation membership

Cognito is the proposed application login service. A successful login issues a **token**, a signed statement about an authenticated user. The API validates the token and checks which organisation the user may act for.

An organisation identifier supplied by the browser is not sufficient proof of membership. The backend must obtain or verify that association from trusted identity/membership information. Signing in to the NUS AWS portal is separate from signing in as a customer of SPIP.

### Step 3: request permission to upload

The authenticated browser asks the application for an upload authorisation. The backend chooses an organisation-scoped object key, for example `tenants/<tenant-id>/uploads/<upload-id>.csv`.

The proposed mechanism is a **presigned S3 URL**: temporary permission to upload a particular object. The browser sends the file directly to S3 using that URL. This avoids routing the entire file through the analytics API. Object naming, expiry, size restrictions, and file validation remain implementation decisions; see the [S3 documentation][aws-presigned].

### Step 4: queue and process the file

After the upload, a configured S3 notification can send a message to SQS. A **queue** holds pending work until a worker can process it. The message identifies an upload; the CSV remains in S3.

A Fargate worker reads the message, verifies the file and its trusted organisation association, then calls Song's analytics components. It supplies the organisation's authorised data together with the approved public baseline. Repeated messages must not create duplicate records. Failed work needs bounded retries and a **dead-letter queue**, a separate queue for messages requiring investigation.

This requires a worker program and integration logic that do not yet exist. The current `POST /analyze` endpoint is a synchronous local-file path, not this background-processing workflow.

### Step 5: persist observations and processing state

The proposed PostgreSQL database stores the agreed standardised records and upload status, with ownership and source information. Whether particular analysis results are saved or calculated on request must be decided with Song.

The browser can ask the API whether its upload is pending, processing, complete, or failed. These statuses are proposed application behaviour, not existing endpoints.

### Step 6: request and display results

The browser sends authenticated requests for a property it is allowed to access. The API restricts the input dataset, calls the analytics engine or reads an agreed saved result, and returns the response format expected by the dashboard.

Private records belonging to another organisation must not become visible merely because a caller knows their entity identifier. How private observations may contribute to shared benchmarks also needs an explicit policy; public baseline access must not imply access to another tenant's private rows.

### Step 7: observe the application

CloudWatch collects useful logs and metrics from the API and workers. Operators should be able to follow an upload identifier through processing and diagnose a failure without logging secrets or complete private files.

## 6. Deployment components in detail

### 6.1 Frontend hosting: S3 and CloudFront

Build the frontend into static files, store them in a dedicated S3 bucket, and serve them over HTTPS through CloudFront. Keep website assets separate from private upload access.

For a private S3 origin, the proposed setup uses CloudFront **Origin Access Control (OAC)**, which authorises the distribution to read the bucket. AWS documents OAC with a regular S3 bucket origin, rather than the S3 website endpoint. Cache behaviour and any future browser-route fallback must also be configured; see [CloudFront's S3 origin guidance][aws-cloudfront].

The deployed frontend needs the correct API URL and authentication settings. Browser-delivered configuration is visible to users, so it must contain only public configuration.

### 6.2 Identity and permissions: three separate concerns

| Concern | Question answered | Implementation responsibility |
| --- | --- | --- |
| Authentication | Who signed in? | Cognito integration and token validation |
| Application authorisation | Which organisation's data may this user access? | Membership checks, dataset filtering, S3 access decisions, and database policies |
| AWS service permissions | Which resources may this program operate on? | IAM roles and policies for the API, workers, runtime, and deployment automation |

IAM means **Identity and Access Management**, AWS's permissions system. An ECS task role authorises application calls to AWS; a task execution role lets the runtime perform tasks such as pulling an image and sending logs. Neither replaces customer data authorisation.

### 6.3 API entry point and network integration

API Gateway is the proposed public entry point. It forwards requests to the backend; it does not run Python or start the worker for each request automatically.

If an HTTP API connects privately to ECS, the design needs a **VPC link**, a connection into the private network, plus a supported integration target. One candidate is an internal **Application Load Balancer (ALB)**, which forwards requests to healthy API tasks. AWS also supports service-discovery integrations; see [API Gateway private integrations][aws-api-private].

The team must choose the actual route and account for its permissions, cost, health checks, and path mapping. API Gateway, VPC link, and ALB must not be treated as an already configured connection. A simpler entry point can be considered if its effect on authentication and the preliminary architecture is documented.

Keep the current analytics routes distinct from proposed ingestion routes. For example, an upload-authorisation route, a job-status route, and an organisation-scoped entity-list route still require a contract and implementation; their names are not established here.

### 6.4 Running the backend: container, ECR, ECS, and Fargate

A **container image** packages application code, Python, and dependencies. A running container is an instance of that image. **ECR** is the proposed image registry; **ECS** manages tasks and services; **Fargate** supplies their compute capacity without the team managing an EC2 host.

Deployment work includes a Dockerfile, dependency installation, configuration/data paths, a startup command, network binding, task definitions, and health checks. No such deployment files exist yet.

The API process and background worker have different jobs. They can reuse the same analytics modules, but need appropriate commands and runtime configuration. An API service listens for HTTP requests; a worker consumes queued work. The current local Uvicorn command must be adapted for container networking, including a suitable host binding such as `0.0.0.0`.

### 6.5 Network and secrets

A **VPC** is the application's AWS network. **Subnets** divide that network; **security groups** restrict permitted network traffic. The design must allow the required API-to-database connections while keeping the database inaccessible directly from the public internet.

Fargate tasks also need a route to obtain images and reach the services they use. Depending on the network design, this may involve internet access through NAT or private service endpoints. These are architecture and cost decisions, not free automatic connections; see [Fargate networking][aws-fargate-networking].

Store sensitive runtime values using an approved secret-management mechanism, such as Secrets Manager or Systems Manager Parameter Store with appropriate protection. Do not put credentials in Git, frontend files, image layers, or handover examples. Service permissions and network reachability must both permit access.

### 6.6 Data storage: S3 and RDS PostgreSQL

S3 stores objects such as source CSVs. PostgreSQL stores structured application records that can be queried. A file being present in S3 does not create database rows automatically; the ingestion program must perform that work.

Agree the database schema with Song before implementing the integration. Expected concepts include organisations, user membership, uploads/jobs, standardised observations, provenance, and visibility. **Migrations** are versioned changes to that schema so collaborators can reproduce the same structure.

S3 object prefixes such as `tenants/<tenant-id>/` organise files but are not sufficient isolation on their own. The API's upload/download decisions and AWS policies must enforce the intended access boundaries.

PostgreSQL **Row-Level Security (RLS)** restricts which rows a database role can read or change. The application must set trusted organisation context correctly for each transaction, including when database connections are reused. The application role must not bypass the intended policies through database ownership or privileged roles. Test this using the actual runtime role; see [PostgreSQL row security][postgres-rls].

No SQL schema, migration, RLS policy, or database adapter is currently supplied in the inspected branches.

### 6.7 Queues, schedules, monitoring, and cost

SQS and the worker need an agreed message format, retry policy, duplicate-processing protection, and job-status updates. Queue delivery does not replace CSV validation or tenant checks.

EventBridge is needed only if scheduled baseline refreshes enter the implemented scope. Before automating refreshes, Nasya must confirm usable sources and update rules.

CloudWatch configuration should cover API/worker errors, processing duration, queue backlog, and log retention. A health endpoint should eventually check the dependencies necessary to serve requests; the current `/health` checks only that the API process responds.

Estimate costs for the whole chosen design, including persistent database and networking resources. Low request volume does not establish near-zero idle cost. Record the region, resource sizes, runtime schedule, storage, and workload assumptions for the cloud/on-premises comparison. [RDS pricing][aws-rds-pricing] explicitly includes running database instance time.

### 6.8 Reproducible infrastructure and deployment automation

**Infrastructure as code (IaC)** means versioned files describing the AWS resources and configuration. The team still needs to choose a tool such as Terraform, CloudFormation, or CDK. This guide does not imply that any tool is already configured.

If Terraform is chosen, agree how its shared **state**, the record linking configuration to real resources, is stored, protected, and locked. Both students must use the agreed environment rather than independently creating duplicate stacks.

**CI** means automated checks on changes. **CD** means automating the release/deployment steps. A future GitHub Actions workflow could run checks, build the frontend and image, publish the image, and update approved resources. No workflow or trigger is currently versioned.

GitHub-to-AWS **OIDC** is a possible authentication mechanism using temporary credentials. It requires an appropriate AWS identity provider, role, trust policy, and permissions. Sandbox support is unverified. Restrict any future deployment role to the intended repository and approved branches or environments; see [AWS GitHub OIDC guidance][aws-oidc].

Choose deployment triggers deliberately and record them before the first push that could activate deployment. Updating this guide locally does not create a workflow or trigger an AWS deployment.

## 7. Integration boundaries and team responsibilities

| Owner | Responsibility | Cloud integration dependency |
| --- | --- | --- |
| Nasya | ESG sources, metric definitions, comparability criteria, business model, and prototype scope | Confirm the approved baseline, data rights, visibility, thresholds, and peer rules |
| Song | Harmonisation, benchmarking, gap calculations, fallback behaviour, and analytics API | Agree how authorised stored data reaches the engine and how results retain the frontend contract |
| Sin Che | Dashboard and comparison tool | Integrate configurable API URL, authentication, upload/status UI, and available property/year lists |
| Alex/Jin and Auxane | AWS architecture, deployment, authentication flow, and tenant isolation | Implement hosting, infrastructure, secure ingestion/storage integration, runtime permissions, and operational documentation |
| Michael | System and user evaluation | Define and record end-to-end, privacy, performance, usability, and cost evidence |

Cloud integration must reuse Song's analytics work. It should not independently reimplement unit conversions, peer selection, or percentile calculations. Database and ingestion changes that overlap the analytics API need an explicit interface agreement with Song.

The detailed division between Alex/Jin and Auxane remains open. A possible starting point is for Alex/Jin to lead deployment packaging and infrastructure, and for Auxane to lead the handover inventory, organisation-scoped storage integration, and operational checks, with security and authentication reviewed together. This is a proposal, not a confirmed assignment.

## 8. What lives on a laptop, GitHub, or AWS

| Location | What it contains | What is shared automatically? |
| --- | --- | --- |
| Each student's laptop | Local Git copy, selected branch, development tools, dependencies, local files, and personal login sessions | Neither installed packages nor login sessions are transferred by pushing code |
| GitHub | Commits, branches, reviewed source/configuration/documentation, and future workflow definitions | Teammates receive versioned files when they fetch and integrate changes |
| AWS account | Deployed resources, runtime data, policies, logs, and resource charges | Changes affect whoever uses that account/environment, subject to permissions |

Both collaborators need their own Git setup and authorised AWS login. Python 3.10+ is required for local analytics work; Node.js/npm are required for frontend work. Docker, an AWS CLI configuration, and the chosen IaC tool become relevant when those implementation steps begin. Agree versions and record actual setup instructions when validated.

GitHub does not share uncommitted files or local environment variables. Do not share AWS passwords or session credentials as a handover method.

The previously observed sandbox account is `825990809862`, labelled `NUS ISB Account 31`. This is team-provided context, not a fresh AWS identity check. Account exclusivity, authorised members, usable regions, service permissions, remaining budget, and lease expiry still require verification. The NUS guide prohibits GPU instances and does not document how to list all account members.

To avoid conflicting work, agree who is changing each file or shared resource, review changes before integration, and record any AWS change with its purpose and configuration. Provisioning, changing, or deleting shared resources requires understanding its concrete effect and cost first.

## 9. Implementation stages

This is a roadmap rather than a list of commands to execute immediately. Each stage needs an agreed owner and recorded evidence.

| Stage | Work | Evidence needed before moving on |
| --- | --- | --- |
| 1. Agree the baseline | Confirm scope, sandbox constraints, code layout, ownership, dataset, and API contract | A shared configuration/decision record; no assumption that branch contents are already integrated |
| 2. Verify the local application | Deliberately integrate the existing components and run the agreed synthetic example | Recorded backend tests, frontend checks, and dashboard/comparison requests reaching the API |
| 3. Prepare deployment files | Add reproducible packaging, environment configuration, IaC, and cost assumptions | Reviewed files describing what will be created and how to remove it |
| 4. Establish a limited cloud demonstration | Deploy the approved website/API path using synthetic data | Reachable URLs, logs, and a recorded comparison with local behaviour; this alone does not establish tenant privacy |
| 5. Complete the secure user journey | Add login, tenant checks, durable upload/storage, background processing, and database integration | Authenticated upload-to-dashboard behaviour and rejection of cross-tenant access |
| 6. Automate and evaluate | Add approved deployment automation and gather evaluation evidence | A repeatable release, documented triggers and recovery, privacy/performance results, and cloud/on-premises cost comparison |

Use synthetic data for early infrastructure checks. Private organisation data requires the access boundaries to be implemented and verified first.

## 10. Verification and handover

Keep these statuses separate when documenting progress:

- **Planned:** described but not implemented.
- **Implemented:** source/configuration exists at an identified commit.
- **Tested:** a named check was executed, with its result and environment recorded.
- **Deployed:** an identified version is running in a named AWS account/region, with a verified access path.

For this documentation update, the source trees, configuration, history, and existing test definitions were inspected. No package installation, application execution, test suite, AWS inventory, or deployment was performed. No commit or push is part of the guide edit.

As implementation progresses, record:

- The owner, branch/commit, date, change, and verified outcome.
- Account, region, resource names, and the IaC configuration responsible for them.
- Required local tools and non-secret runtime configuration; record where secrets are managed, never their values.
- The actual website/API URLs, deployment triggers, and last successfully deployed version.
- How to inspect logs, retry failed processing safely, and recover or roll back a release.
- Test evidence for numerical correctness, complete upload-to-dashboard behaviour, and denied access across two organisations, including files, rows, jobs, and property results.
- Known limitations, current cost assumptions, resource lifetime, and the next owner/action.
- A reviewed cleanup procedure that explains which resources and data would be removed or retained.

Do not mark a deployment successful merely because an image built, a workflow file exists, or `/health` responds. Verify the user journey and the relevant storage/access controls.

## 11. Technical references

These references explain candidate mechanisms. They do not prove that the NUS sandbox permits them or that they are configured for SPIP.

- [S3 presigned URLs][aws-presigned]
- [CloudFront access to a private S3 origin][aws-cloudfront]
- [API Gateway private integrations][aws-api-private]
- [Fargate task networking][aws-fargate-networking]
- [PostgreSQL Row-Level Security][postgres-rls]
- [GitHub OIDC roles in AWS][aws-oidc]
- [RDS PostgreSQL pricing][aws-rds-pricing]

[analytics-api]: https://github.com/sctham26/CS5224-Project/blob/721d3ab6417dbaadadb36fced0573ecb8b145a3a/src/api.py
[frontend-app]: https://github.com/sctham26/CS5224-Project/blob/a0975a9d773a12213f55b3535ab55e9a25eaaf18/frontend/src/App.jsx
[frontend-comparison]: https://github.com/sctham26/CS5224-Project/blob/a0975a9d773a12213f55b3535ab55e9a25eaaf18/frontend/src/components/PropertyComparison.jsx
[aws-presigned]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html
[aws-cloudfront]: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html
[aws-api-private]: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-private.html
[aws-fargate-networking]: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html
[postgres-rls]: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
[aws-oidc]: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html#idp_oidc_Create_GitHub
[aws-rds-pricing]: https://aws.amazon.com/rds/postgresql/pricing/
