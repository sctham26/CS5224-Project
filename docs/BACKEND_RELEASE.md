# Backend application releases from GitHub

Configured 2026-10-26 for the existing Singapore sandbox. Cloud configuration remains in `cloud-config`; the backend team is authorized to maintain the small workflow entrypoint in `backend-analysis`. Application source is not copied into the cloud branch.

## For the backend team

Push an application change to `backend-analysis`. Its `.github/workflows/backend-deploy.yml` invokes the reusable `backend-release.yml` from a pinned cloud commit. Open **Actions → Deploy backend sandbox** to follow the run. A failed run may be retried with **Re-run all jobs** by a collaborator with write access. No local Docker/AWS setup, personal AWS keys, SSO login or Cognito admin account is needed.

The workflow checks the reviewed schema/dependency baseline, builds Linux AMD64, and runs the actual backend tests inside that image before requesting AWS credentials. It then uploads to the existing immutable `spip-backend` ECR repository and changes the API/worker image parameters through a fixed release function. It waits for CloudFormation and both ECS services to complete, then checks `/api/health` and missing/invalid-token rejection. Releases are serialized; an active release is not cancelled by a newer push.

The Actions artifact `backend-release-<run>-<attempt>` records backend commit, cloud-support hash, unique image tag and digest. Both services must report that exact digest for the run to succeed. The tag includes the run/attempt so retries do not overwrite immutable tags. Image publication alone is not successful deployment. These checks do not replace the backend team's authenticated tenant/upload E2E tests.

## Permissions and ownership

- GitHub uses OIDC role `spip-backend-github-release`, trusted only for this repository's immutable identity and `backend-analysis` ref. PRs and other branches are not trusted.
- The role can upload images only to `spip-backend`, invoke only `spip-backend-release`, and read the one runtime stack/application service/task definitions needed for verification. It cannot directly update ECS, change a CloudFormation template, pass IAM roles or read Secrets Manager credentials.
- The cloud-owned release function accepts only a validated digest, source SHA and run ID. It verifies an existing project ECR image/source tag, then uses **the previous CloudFormation template**, preserving all parameters except `ApiImageDigest` and `WorkerImageDigest`. Callers cannot supply roles, templates, stack names or arbitrary parameters.
- Database, migrations/importers, Cognito, memberships, networking and IAM stay with cloud operations. Operator task definitions are deliberately not updated by routine backend releases. The normal API/worker roles retain their existing application permissions.

Changing migration files or dependency declarations stops automatic release before AWS authentication. Coordinate with cloud operations to review/run migrations as appropriate, update the hash-locked runtime dependencies and `backend_cloud/release-baseline.json`, and publish a reviewed cloud workflow version. The gate does not automatically apply SQL or grant privileges.

## For cloud operations

`BackendRuntimeStack` exposes the two digest parameters. `infra/backend.sandbox.json` provides their initial defaults, not a continuously updated record of automated releases. The **live stack parameters** and the successful Actions artifact are the deployed version's authority. Read them before a manual release:

```bash
aws cloudformation describe-stacks --stack-name BackendRuntimeStack \
  --profile sandbox --region ap-southeast-1 \
  --query 'Stacks[0].Parameters'
```

Keep `enable_backend`, `enable_backend_operations`, `enable_backend_runtime` and `enable_backend_release` enabled when synthesizing the complete assembly. CDK's `--previous-parameters` defaults to true: retain those existing values during infrastructure-only updates. To deliberately change images with CDK, supply both parameters explicitly, for example:

```bash
npx cdk deploy BackendRuntimeStack --exclusively --profile sandbox \
  -c enable_backend=true -c enable_backend_operations=true \
  -c enable_backend_runtime=true -c enable_backend_release=true \
  -c backend_config=backend.sandbox.json \
  --parameters 'BackendRuntimeStack:ApiImageDigest=sha256:<reviewed-digest>' \
  --parameters 'BackendRuntimeStack:WorkerImageDigest=sha256:<reviewed-digest>'
```

Changing only the JSON defaults no longer updates an existing stack parameter. A normal backend release updates CloudFormation itself, so it does not create direct ECS configuration drift. CloudFormation/ECS rollback protections remain enabled. On failure, inspect Actions and the runtime stack; never bootstrap/reimport the database to recover an image release. Restore a previously successful digest with the explicit parameter procedure above and rerun the health/E2E checks.

When updating the reusable workflow, update the backend entrypoint's `uses` SHA and `cloud_ref` together after cloud checks pass. Its SHA pin ensures the deployment code is reviewed independently from application changes. Before switching to a final `main` release model, explicitly review the trigger/trust policy; `main` is not currently granted this backend release role.

## Validation

Infrastructure tests cover the OIDC branch boundary, absence of infrastructure/secret privileges on the GitHub role, strict release inputs, existing-image/source checks, previous-template-only parameter updates, busy-stack rejection and no-op releases. The schema gate has a test for added/nested migrations and changed dependencies. The first real backend workflow run is the acceptance test for OIDC, ECR, the deployment broker and ECS rollout; record its link in the PR.

The broker's SDK permissions were checked with a local IAM Policy Autopilot baseline (not uploaded):

```bash
uvx iam-policy-autopilot@latest generate-policies backend_cloud/release/handler.py \
  --region ap-southeast-1 --account 825990809862 \
  --service-hints cloudformation ecr --pretty
```

The generated baseline includes optional API permissions for role/tag/stack-policy changes. This fixed handler supplies none of those fields; its deployed role is scoped to the actual named runtime stack and project repository. GitHub never receives the broker's CloudFormation update permission.
