# SPIP frontend

React/Vite dashboard, comparison and CSV demo. The cloud branch includes Cognito login/logout and authenticated API calls. See [login configuration and team contract](../docs/AUTH_CONTRACT.md) and [frontend deployment](../docs/FRONTEND_DEPLOYMENT.md).

Run `npm ci`, then copy `.env.example` to `.env.local`. Explicit `VITE_AUTH_MODE=demo` allows local analytics development only. For real login remove demo and supply the three public Cognito settings; use `http://localhost:5173` so callback URLs match.

Commands: `npm run dev`, `npm run lint`, `npm test`, `npm run build`. Production requires Cognito settings and always gates the app behind login. API calls use shared `API_BASE_URL` and `authenticatedFetch`; CSV selection currently validates locally and does not upload bytes.
