# SPIP frontend infrastructure

Python CDK managed by uv. See [the deployment guide](../docs/FRONTEND_DEPLOYMENT.md) for setup, IAM/OIDC, deployment, validation, and cleanup.

Use `uv sync --locked`, `npm ci`, `uv run --locked pytest -q`, and `npx cdk synth --strict`. Infrastructure deploys use an authorised AWS profile; application releases use the restricted GitHub role.
