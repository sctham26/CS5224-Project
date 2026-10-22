# Backend cloud configuration

Implemented configuration on `cloud-config`; **not deployed**. This adds infrastructure and a database bootstrap utility, not application upload/job endpoints, ESG parsing, business tables, migrations, or an analytics worker. Interface agreement: [backend–cloud contract](BACKEND_CLOUD_CONTRACT.md).

## Modules and deployment boundaries

| Module | Definition | Creates on explicit deployment |
| --- | --- | --- |
| Existing frontend | `infra/infra/infra_stack.py` | Existing `InfraStack`, unchanged by default |
| Data foundation | `infra/infra/backend_data_stack.py` | Private/versioned public and tenant S3 buckets; encrypted SQS + DLQ; VPC/security groups; private PostgreSQL; role credentials; ECS cluster and an unstarted bootstrap task definition |
| Runtime | `infra/infra/backend_runtime_stack.py` | API/worker task definitions and services, internal ALB, VPC link, JWT-protected HTTP API |
| Database setup | `backend_cloud/bootstrap.py` | When separately run: `spip_public` / `spip_tenant`, restricted logins, and an `app` schema namespace; no business tables |
| Runtime bridge | `backend_cloud/entrypoint.py` | Converts injected credentials into the two agreed PostgreSQL URLs and starts the backend command |

The default CDK app synthesizes only the existing frontend. Backend stacks require `enable_backend=true`. Runtime additionally requires `enable_backend_runtime=true`, real digest-pinned ECR images, a worker start command, HTTPS JWT issuer, audience, required access-token scopes and explicit browser origins. No placeholder backend image is started automatically.

The GitHub backend workflow tests and synthesizes templates, builds the bootstrap image and checks database privileges using disposable PostgreSQL. It has no AWS deployment role or deployment step. The existing frontend workflow still publishes frontend changes only. Modifying a backend stack in Git does not create a database in AWS.

## Configuration

`infra/backend.example.json` is a **data-foundation** example. Its PostgreSQL `18.6`, `db.t4g.micro`, gp3, Multi-AZ and Performance Insights combination was confirmed orderable in `ap-southeast-1` on 2026-10-23. Recheck engine/class availability and cost before deployment. Multi-AZ defaults to true; setting `"multi_az": false` explicitly selects a development availability/cost tradeoff.

Defaults include encrypted storage/queues/logs, seven-day database backups, deletion protection, a retained data key and S3 buckets, versioning, a fifteen-minute initial work-queue visibility timeout and a DLQ after five receives. Visibility/retry settings are configurable and must be reviewed against the backend's measured execution duration and heartbeat implementation. No queue timeout is a claimed job-runtime guarantee. The DLQ has a CloudWatch alarm; a notification destination/escalation owner must still be attached.

To enable runtime, extend a reviewed config with:

```json
{
  "api_image": "<account>.dkr.ecr.ap-southeast-1.amazonaws.com/api@sha256:<64-hex-digest>",
  "worker_image": "<account>.dkr.ecr.ap-southeast-1.amazonaws.com/worker@sha256:<64-hex-digest>",
  "worker_command": ["python", "-m", "your_real_worker_module"],
  "jwt_issuer": "https://<your-real-issuer>",
  "jwt_audience": ["<your-client-id>"],
  "authorization_scopes": ["spip/access"],
  "allowed_origins": ["https://d10rc41o4pb0h.cloudfront.net"]
}
```

These placeholders are documentation only and fail runtime validation. The test fixture under `infra/tests/fixtures/` is exclusively for synthesis/CI and must never be deployed. Actual images must be built and pushed to the indicated private ECR repository first. Cross-account ECR requires a matching repository policy; it is not created by this module. This module reserves a runtime for the team's images, rather than building their application from a separate moving branch.

The API uses the currently documented startup command: `python -m uvicorn api:app --app-dir src --host 0.0.0.0 --port 8000`. Both application images must include `/opt/spip-cloud/entrypoint.py` and the current RDS CA bundle at `/opt/spip-cloud/rds-ca.pem`, with Python available. The bridge is dependency-free Python. Download the CA from `https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem` during the application-image build. The separate bootstrap image builds from `backend_cloud/Dockerfile` with locked psycopg dependencies. Docker must be running when deploying its image asset.

## Network and IAM boundaries

- One VPC spans two AZs. RDS and the internal ALB use isolated subnets. RDS has no public endpoint; port 5432 accepts only API, worker and bootstrap security groups.
- To avoid NAT gateways in this prototype, API/worker/bootstrap tasks use public subnets and public IPs **for outbound access**, with no internet-facing task ingress. The API task accepts port 8000 only from the internal ALB; the ALB accepts port 80 only from the VPC-link security group. The worker/bootstrap have no ingress rules. S3 uses a gateway endpoint. Public IPv4 still has a charge. For production private tasks, budget NAT gateways or the required ECR/Logs/Secrets/SQS interface endpoints before changing placement.
- The public HTTP API validates JWT issuer, audience and required scopes for every reserved route, including external `/health`. The ALB's internal health check calls `/health` without authentication. The backend must independently validate the forwarded token, resolve trusted tenant membership and enforce reference ownership. An API Gateway JWT check does not establish tenant membership or secure database queries by itself.
- External HTTPS terminates at API Gateway/CloudFront. The VPC-link/ALB/task hops use HTTP inside the restricted VPC; they are not end-to-end application TLS. Database connections use `verify-full` with the RDS CA. If the deployment requires TLS on the internal HTTP hops too, add the internal certificate/listener design before enabling runtime.
- App execution roles fetch only the public-reader and tenant-app secrets, and pull only the configured ECR repositories (ECR token acquisition necessarily uses `Resource: *`). App task roles have scoped S3/work-queue permissions. They receive no master, public-writer or migration passwords and no object-delete permission. Shared task roles can access multiple tenant prefixes: backend authorisation is still essential.
- Only the separately started bootstrap task receives the master secret and role credentials. Normal services do not run bootstrap. A dedicated public importer can use the public-writer role; none of the normal tenant endpoints may select that role or publish public data.
- A versioned source object is retained after processing. There is no automatic S3 ObjectCreated job trigger, no data parsing, and no expiry rule that silently deletes raw records.

## Database roles and backend responsibilities

The RDS instance initially creates `spip_public`. Running the bootstrap task creates `spip_tenant` and grants the intended role boundaries. Foundation deployment alone does **not** create the second logical database or demonstrate isolation.

| Login | Database | Intended permissions |
| --- | --- | --- |
| `spip_public_reader` | `spip_public` | Read backend-created `app` tables |
| `spip_public_writer` | `spip_public` | Read/write backend-created `app` tables; no schema ownership |
| `spip_tenant_app` | `spip_tenant` | Read/write backend-created `app` tables; subject to backend-defined RLS |
| `spip_public_migrator` | `spip_public` | Create/own public application schema objects |
| `spip_tenant_migrator` | `spip_tenant` | Create/own tenant application schema objects |

Default database `PUBLIC` connect privileges are revoked; logins receive explicit access to their own database. App logins are not owners, superusers, role creators or BYPASSRLS roles. Migrations should create tables as the appropriate migrator in schema `app`, so the configured default grants apply. Tables in another schema or created by another owner require explicit grants. Bootstrap checks reserved role/schema ownership and refuses unexpectedly elevated pre-existing roles. It should only be used with these reserved project names.

The backend team must create business tables and enable tenant RLS in its migrations **before starting services with private data**. It must bind trusted tenant context per transaction, reset pooled connection state, filter S3/job/dataset ownership and implement durable dispatch/idempotency. No generic infrastructure template can safely invent row policies without the backend's table and tenancy design. The included RLS tests use disposable demonstration tables, not a prescribed ESG schema or proof of end-to-end API isolation.

Secrets Manager generates separate role passwords; bootstrap aligns them with PostgreSQL. These application-role secrets do not yet have an automated rotation workflow. Coordinate any role-secret rotation with DB password updates and task replacement. The administrative password is RDS-managed. Never print DSNs, credentials or signed object URLs in application logs.

## Deployment sequence (operator-run, not automatic)

Review cost, target account and security/tenancy prerequisites first. Run from `code/cloud-config` unless a command explicitly changes directory.

1. Verify `aws sts get-caller-identity --profile sandbox` is account `825990809862`; region is `ap-southeast-1`.
2. With Docker running, synthesize and review only the data foundation:

```bash
cd infra
uv sync --locked
npm ci
npx cdk synth --strict -c enable_backend=true -c backend_config=backend.example.json
npx cdk diff BackendDataStack --profile sandbox -c enable_backend=true -c backend_config=backend.example.json
npx cdk deploy BackendDataStack --profile sandbox -c enable_backend=true -c backend_config=backend.example.json --outputs-file cdk-outputs-backend.json
cd ..
```

3. Run the one-off database setup and require its container exit to be zero:

```bash
AWS_PROFILE=sandbox python3 scripts/run_database_bootstrap.py infra/cdk-outputs-backend.json
```

4. The backend team runs its public/tenant migrations with the corresponding migration secrets from inside the VPC and verifies RLS/reference ownership. Both database URLs need TLS verification; a GitHub-hosted runner cannot directly reach the private DB. Use a reviewed one-off VPC task for migrations. No migration command is assumed by this template.
5. Build real API/worker images including the bridge and CA, confirm the proposed contract is implemented, and provide real JWT configuration. Save a reviewed non-secret config, e.g. `infra/backend.runtime.json`. Never put a DB password or token into it.
6. Synthesize/diff the runtime and frontend together, then explicitly deploy the runtime and optional `/api/*` CloudFront route:

```bash
cd infra
npx cdk synth --strict -c enable_backend=true -c enable_backend_runtime=true -c backend_config=backend.runtime.json
npx cdk diff --profile sandbox -c enable_backend=true -c enable_backend_runtime=true -c backend_config=backend.runtime.json
npx cdk deploy BackendRuntimeStack InfraStack --profile sandbox -c enable_backend=true -c enable_backend_runtime=true -c backend_config=backend.runtime.json
```

The existing data foundation must be deployed with the same reviewed settings. Enabling runtime adds `/api/*` routing to the existing distribution, strips only the leading `/api`, disables caching and forwards the Authorization header. Without runtime enabled, the frontend stack remains unchanged. After the API is enabled, always use the same backend/runtime context when synthesizing or deploying `InfraStack`; deploying the context-free frontend template would remove that API behavior. The app-upload GitHub workflow does not run `cdk deploy`, so it cannot remove it.

## Tests, cost and cleanup

Local checks: infrastructure pytest, strict synthesis of default/data/full configurations, helper pytest, actionlint and shell syntax. `scripts/test_backend_postgres.sh` requires a running Docker daemon and uses a disposable TLS PostgreSQL container; it checks idempotent bootstrap with a non-superuser administrator, public read-only grants, cross-database denial, and transaction-scoped RLS on synthetic tables. CI additionally builds the bootstrap image. This is not AWS RDS integration or backend endpoint testing.

The template provisions chargeable RDS (Multi-AZ by default), storage/backups, KMS keys/requests, secrets, ALB, tasks, public IPv4, API requests and logs when enabled. Worker/API services each start at one task; they do not scale to zero. Price the target region and expected usage before deployment: [RDS](https://aws.amazon.com/rds/postgresql/pricing/), [Fargate](https://aws.amazon.com/fargate/pricing/), [ALB](https://aws.amazon.com/elasticloadbalancing/pricing/), [S3](https://aws.amazon.com/s3/pricing/).

Data stack termination protection and RDS deletion protection prevent casual deletion. S3, credentials and data KMS keys are retained; RDS uses snapshot removal. Deleting a stack is not a full data purge. Review exact resources and approved retention before any destructive cleanup. No such cleanup or live backend deployment is performed by this change.
