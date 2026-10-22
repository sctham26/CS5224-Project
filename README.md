# SPIP - Cloud Deployment

Deployment plan for `cloud-config` (Alex and Auxane)

**Status:** frontend hosting is deployed and its first GitHub Actions release passed on 2026-10-22; see [frontend deployment and verification](docs/FRONTEND_DEPLOYMENT.md). Backend runtime, authentication, database, and ingestion remain planned. Cloud verification is recorded separately in that deployment guide.

## 1. Before provisioning

- Confirm the AWS account, region, available permissions, lease expiry, remaining budget, and existing resources.
- Choose the infrastructure-as-code tool, shared configuration/state, resource names, and responsibility for each change.
- Agree the application source versions, runtime configuration, and storage/API integration boundaries with Song and Sin Che.
- Estimate the chosen stack's running costs, including database and networking charges.

## 2. Deployment tasks

All items below are planned.

| Area | Work to implement | Completion check |
| --- | --- | --- |
| Infrastructure and permissions | Define VPC/subnets, security groups, service roles, protected secrets, and reproducible infrastructure configuration. | Required connections work; database access is private; roles have the intended permissions. |
| Backend runtime | Add a Dockerfile, publish a versioned image to ECR, and configure the ECS Fargate service, startup command, data/configuration paths, and health checks. | The identified image serves the agreed synthetic analysis and produces logs. |
| API access | Configure API Gateway and its actual backend integration; a private route may use a VPC link and internal load balancer. Configure browser origins. | The deployed API URL reaches Fargate through the documented route. |
| Authentication | Configure Cognito, token validation, trusted organisation membership, and frontend login settings. | Valid users connect; invalid tokens and unauthorised organisation access are rejected. |
| Database | Provision private RDS PostgreSQL; add schema migrations, data-access integration, and Row-Level Security using a restricted application role. | Data survives restarts; two organisations cannot read or modify each other's private rows. |
| File storage | Configure private S3 storage, organisation-scoped access policies, authorised upload URLs, ownership records, and retention. | Users can upload permitted files and cannot access or replace another organisation's files. |
| Background processing | Connect S3 notifications to SQS; add a Fargate worker, retries, duplicate protection, failed-message handling, and persistent job status. Reuse Song's engine with authorised inputs. | An upload produces stored results; concurrent files stay separate and retries create no duplicate records. |
| Frontend hosting | Build the frontend; upload the output to private S3 and serve it through CloudFront with origin access control and HTTPS. Supply deployed API/login configuration. | The website works without a local backend and displays the uploaded data's results. |
| Monitoring and costs | Configure CloudWatch logs, retention, failure/backlog monitoring, cost tracking, and cleanup procedures. | A failed upload can be diagnosed; resource consumption and shutdown/retention choices are documented. |
| Deployment automation | Add GitHub Actions for checks, builds, and releases after verifying AWS authentication support. Define triggers, release coordination, and recovery. | A known commit can be released repeatedly; its deployed version and recovery procedure are recorded. |

The existing API reads local files. S3/PostgreSQL adapters and the queued worker still need implementation; deploying the current code does not add them automatically. Coordinate those interfaces with Song and the cloud API/login/upload integration with Sin Che.

## 3. Implementation order

1. Confirm permissions, interfaces, costs, and a working local baseline.
2. Prepare infrastructure and packaging; deploy a synthetic-data website/API demonstration.
3. Complete authentication, tenant isolation, durable storage, and queued ingestion before accepting private organisation data.
4. Verify the complete upload-to-dashboard journey, record operational evidence, and automate the verified release path.

AI infrastructure is outside scope. Add EventBridge only if scheduled public-data refreshes are agreed.

## 4. Deployment handover

Record the account/region, resource names, infrastructure and application versions, website/API URLs, non-secret settings, secret locations, deployment triggers, verification results, running costs, recovery steps, and cleanup/data-retention procedure.

Keep **planned**, **implemented**, **tested**, and **deployed** statuses separate.

Application walkthroughs and technical explanations are in the [Project and Architecture Guide](docs/PROJECT_GUIDE.md).

## 5. Component delivery boundaries

Alex proposed implementing these components individually before connecting them through an end-to-end test:

1. Authentication and authorisation.
2. Frontend distribution and storage (CloudFront + S3).
3. Backend runtime deployment and input/output integration.
4. Database deployment and multi-tenant isolation validation.
5. File upload and asynchronous processing.

## 6. Frontend delivery

Python CDK (`infra/`, managed by uv) defines private S3, CloudFront OAC, and a scoped GitHub OIDC publishing role. The [workflow](.github/workflows/frontend.yml) builds and checks PRs, and publishes relevant pushes to `cloud-config`/`main` to one development site. See [setup, branch coordination, API limitations, and recovery](docs/FRONTEND_DEPLOYMENT.md).

Development website: https://d10rc41o4pb0h.cloudfront.net. The frontend renders, but analytics requires the separately planned backend integration.

## 7. Proposed backend integration contract

The [backend–cloud contract draft](docs/BACKEND_CLOUD_CONTRACT.md) reserves upload/job/result interfaces, worker message envelopes, storage and secret configuration, and responsibility boundaries. It is a proposal for backend-team review; it does not define ESG columns or business tables and is not deployed.

## 8. Backend cloud configuration

[Backend deployment](docs/BACKEND_DEPLOYMENT.md) describes the opt-in data/runtime CDK stacks, PostgreSQL logical-database bootstrap, application-role permissions, reserved JWT-protected API routes and worker configuration. The backend [interface draft](docs/BACKEND_CLOUD_CONTRACT.md) remains included. These templates are implemented but not deployed; business tables, RLS migrations and upload/job processing remain backend-owned.
