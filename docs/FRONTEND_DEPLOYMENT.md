# Frontend deployment

This module builds the React/Vite application and publishes `frontend/dist/` to a private, versioned S3 bucket through CloudFront OAC. It does not deploy a backend, database, Cognito, or upload processing.

## Source and branch coordination

Updated 2026-11-01. Deployment logic stays in `cloud-config`; application integration stays with the frontend team.

- Pushes and PRs from `cloud-config` check the current `integration` frontend, never the cloud branch's historical frontend. Other main/integration pushes and PR checks build the exact event commit. PRs run without AWS credentials. Integration triggers become available once that branch receives this workflow; feature-only pushes currently do not install or trigger this cloud workflow.
- **Manual checks:** open Actions → Frontend checks and AWS deployment → Run workflow. Select workflow branch **cloud-config**, choose `frontend_source_ref`, and leave `deploy=false`. Approved sources are `integration` and the three frontend feature branches listed in the input menu. Feature branches are check-only.
- **Manual test publication:** after the frontend team merges and tests its changes in `integration`, select that source with `deploy=true`. This publishes to the existing **shared** CloudFront test site, replacing its current UI. It is not an isolated preview URL. The latest integration commit is resolved once at checkout; publishing downloads that run's tested build and never rechecks a moving branch.
- Pushes to `main` retain automatic publication. Cloud-config/integration pushes do not publish automatically; manual publication requires the explicit boolean and a trusted cloud-config/main workflow ref.

Every selected source runs npm ci, lint, tests and a production build. `/api` is the default production base; existing public Cognito build variables are reused. The artifact name includes run/attempt; `build-source.json` records application and workflow SHAs. `release.json` and post-publish verification use the **application SHA**, so selecting integration cannot incorrectly label a release with the cloud-config commit.

No frontend JS, IAM trust, Cognito settings, API/S3 CORS, database or running site is changed just by installing this workflow. Main/cloud-config already have the existing frontend publishing role's trust. Localhost CORS is deliberately outside this update.

### Team snapshot — 2026-11-01

| Branch | Fetched head | Status |
| --- | --- | --- |
| `feature/frontend-error-handling` | `e00c7a1` | Includes real CSV upload branch plus entity/retry handling and README updates |
| `feature/real-csv-upload` | `e554763` | Already an ancestor of error-handling; no separate duplicate merge needed |
| `feature/insufficient-peer-display` | `c5dde1a` | Independent; not included in either branch above |
| `integration` | `243e683` | Still needs frontend feature integration and the latest cloud release configuration |
| `backend-analysis` | `faaa3f6` | Latest backend release run `41004869610` succeeded on 2026-10-30 |

Michael/frontend owners should combine error-handling and insufficient-peer-display, resolve overlapping App.jsx changes, and rerun the combined tests before publishing integration. A passing feature-branch test run is not evidence that the combined frontend works. The new upload code follows the existing cloud transport: authenticated POST /api/uploads → ordinary presigned S3 PUT without a bearer header → authenticated POST /api/jobs with Idempotency-Key → GET /api/jobs/{id}. No new API route or database deployment is required for that sequence. Backend-owned request fields and tenant authorization remain authoritative; see API_INTEGRATION.md.

The team's reported frontend test count and pending browser upload test are not a completed live AWS UI acceptance test. Run the actual login/upload/result journey on the shared site after the integrated source is intentionally published. Preserve the newer cloud automatic-release files when merging cloud-config into integration.

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
