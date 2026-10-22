# Frontend deployment

This module builds the React/Vite application and publishes `frontend/dist/` to a private, versioned S3 bucket through CloudFront OAC. It does not deploy a backend, database, Cognito, or upload processing.

## Source and branch coordination

The initial frontend was imported from `feature/frontend-dashboard` at `a0975a9d773a12213f55b3535ab55e9a25eaaf18`. Only deployment-related API configuration and unused code rejected by lint were adjusted.

The workflow is present in `cloud-config` and triggers on relevant pushes to **cloud-config or main**. PRs targeting these branches build and test without AWS credentials. A manual dispatch is also supported from either trusted branch. Both branches publish to the **same development site** and releases are serialized. This is not separate dev/production infrastructure.

Changes pushed only to `feature/frontend-dashboard` are not automatically imported. Merge the frontend changes into `cloud-config` for module testing; after team integration, merge this module into `main`. The workflow builds the exact checked-out commit, never an independently moving source branch. Infrastructure changes are checked in CI but deployed separately by an authorised operator.

## One-time setup

Target: AWS account `825990809862`, region `ap-southeast-1`, profile `sandbox`, stack `InfraStack`. Verify these before provisioning:

```bash
aws sso login --profile sandbox
aws sts get-caller-identity --profile sandbox
cd infra
uv sync --locked
npm ci
npx cdk bootstrap aws://825990809862/ap-southeast-1 --profile sandbox --termination-protection
npx cdk diff --profile sandbox
npx cdk deploy --profile sandbox --outputs-file cdk-outputs.json
```

The standard bootstrap stack creates CDK publishing resources and CloudFormation roles, using the default CloudFormation execution policy. The GitHub release role does **not** receive these infrastructure permissions. Existing unrelated AWS resources are not imported or changed.

If the account already has a GitHub OIDC provider, avoid creating a duplicate. Supply its ARN consistently on synth, diff, and deploy:

```bash
npx cdk deploy --profile sandbox \
  -c github_oidc_provider_arn=arn:aws:iam::825990809862:oidc-provider/token.actions.githubusercontent.com \
  --outputs-file cdk-outputs.json
```

On 2026-10-22, GitHub's OIDC customization API reported immutable subject prefix:

```text
repo:sctham26@337585649/CS5224-Project@1403949135
```

The role trusts only that prefix with `ref:refs/heads/cloud-config` or `ref:refs/heads/main`, and audience `sts.amazonaws.com`. It rejects PR/fork subjects and other branches. If repository OIDC settings change, verify the actual subject format and pass `-c github_subject_prefix=...` before updating the stack. The current workflow intentionally does not use a GitHub Environment, which would change the subject and require owner/admin setup.

From the repository root, register outputs (requires repository variable write access):

```bash
python3 scripts/configure_frontend_variables.py infra/cdk-outputs.json
```

This creates four **non-secret** Actions variables: `FRONTEND_BUCKET_NAME`, `CLOUDFRONT_DISTRIBUTION_ID`, `FRONTEND_URL`, and `FRONTEND_DEPLOY_ROLE_ARN`. No permanent AWS keys are stored in GitHub. AWS account/region are explicit in the workflow.

After those variables exist, push a relevant change to `cloud-config` or `main`. GitHub Actions builds, uploads assets before HTML, writes `release.json`, waits for CDN invalidation, and checks the actual HTML, referenced JS/CSS, and commit SHA. Check the run summary for the URL and deployed commit. Actions must be enabled by the repository owner if repository policy blocks it.

## API configuration and current limits

`frontend/src/api.js` reads `VITE_API_BASE_URL` at **build time**. Local `npm run dev` defaults to `http://localhost:8000`; production defaults to `/api`. Once a backend is deployed, set the repository variable `VITE_API_BASE_URL` to its HTTPS base URL and rebuild, or add a CloudFront `/api/*` behavior to a backend origin that strips `/api` if the backend expects `/analysis/*`.

The current stack has only the static S3 origin. `/api/*` is deliberately not rewritten into HTML and is **not** connected to a backend. The existing frontend will show its API error state until backend integration is completed. Publishing the frontend is not evidence of working analytics, login, upload, or tenant isolation. Frontend `VITE_*` values are public; never use them for secrets.

## Local checks

```bash
cd frontend
npm ci
npm run lint
npm run build
cd ../infra
uv sync --locked
uv run --locked pytest -q
npm ci
npx cdk synth --strict
cd ..
python3 -m unittest discover -s tests -v
```

CI uses Node 24 and Python 3.12, with locked npm/uv dependencies, an exact CDK CLI version, and commit-pinned actions. Default macOS Node 26 may produce a jsii untested-version warning; it is not used in CI.

## Release behavior and recovery

- Hashed `assets/*` files receive one-year immutable caching; other static files use five-minute caching. HTML requires revalidation. CloudFront's minimum TTL is zero.
- Existing assets are preserved. No deployment uses `s3 sync --delete`, so an already-open old page can still load its dependencies.
- A failed dependency upload stops before replacing HTML. If invalidation or smoke checks fail after upload, some or all new files may already be live; the script does not claim automatic rollback.
- PR checks and missing repository variables prevent release before any upload. GitHub's role can write only this bucket and invalidate this distribution; it cannot delete objects or change infrastructure.
- To roll back, revert the application change through Git and push a new commit to a trusted branch. Alternatively, download a successful run's `frontend-<commit>` artifact (retained seven days) and republish it with `GITHUB_SHA` set to that full commit, then run the verification script.
- Editing only documentation does not trigger deployment. Repository-variable changes do not trigger a run: use **Run workflow** on `cloud-config`/`main` (if the workflow exists on the default branch), `gh workflow run frontend.yml --ref cloud-config`, or push a relevant change. GitHub may require the workflow on the default branch before dispatch is available.

## Costs and cleanup

This module does not provision ECS, RDS, NAT gateways, custom domains, or a paid certificate. S3 storage/requests, CloudFront traffic/requests, CDN Functions, invalidations, and private-repository Actions usage depend on actual use and applicable allowances. Do not assume zero cost. Versioning and retained historical assets consume storage.

`cdk destroy` removes the distribution and stack-managed IAM configuration but **retains the frontend bucket and all versions**. Confirm which provider was created by this stack before deleting IAM resources shared later with other applications. Never delete the shared `CDKToolkit` stack as routine application cleanup. To remove the retained bucket, explicitly confirm its exact identity and delete all versions/delete markers first.

## Deployment evidence

Record deployed resource IDs and the first successful Actions run below after verification. Never confuse local synthesis or unit tests with a deployed service.

Verified on **2026-10-22 (Asia/Singapore)**:

| Item | Observed result |
| --- | --- |
| AWS account / region | `825990809862` / `ap-southeast-1` |
| CDK bootstrap | `CDKToolkit` created, with termination protection |
| Frontend stack | `InfraStack` reached `CREATE_COMPLETE` |
| Website | https://d10rc41o4pb0h.cloudfront.net |
| S3 bucket | `infrastack-webbucket12880f5b-raw9utx9tvl3` |
| CloudFront distribution | `E3QY7X63F4GZGW`, deployed |
| OIDC publishing role | `arn:aws:iam::825990809862:role/InfraStack-FrontendDeployRoleBA19618F-vZQMAvup1aIE` |
| Released source | `51936a87f91ddb1eccd30bb254c4d3d35f11a12d` |
| First automatic run | [39768583082](https://github.com/sctham26/CS5224-Project/actions/runs/39768583082), all three jobs succeeded |
| Local checks | Frontend lint/build, four infrastructure tests, eight publication/verification tests, strict CDK synthesis, and actionlint passed |
| Live release check | HTML matched the build; both JS/CSS assets loaded; `release.json` matched the commit |
| Access/routing checks | Anonymous direct S3 read returned 403; SPA navigation returned HTML/200; missing JS and unconnected `/api/health` retained 403 responses |
| Browser check | React dashboard rendered; analytics showed the expected unavailable-API error |

The first release used GitHub OIDC credentials, not the operator's SSO credentials. No permanent AWS access keys were added. GitHub repository variable writes succeeded with collaborator permissions. The earlier existing CloudFront distribution `E1V5DW2RLX4J8A` was left unchanged.

The frontend code's existing error text still mentions starting the local Python API on port 8000. The deployed browser uses `/api`, not localhost. This is a wording limitation of the existing application; backend integration remains a separate task.
