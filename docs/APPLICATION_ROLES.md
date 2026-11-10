# Application role assignment (2026-11-08)

Cognito groups were applied and read back in sandbox account 825990809862, region ap-southeast-1, pool ap-southeast-1_frOvkBoAN:

| Person | Account | Group |
|---|---|---|
| Alex | alex.jin@u.nus.edu | spip-admin |
| Auxane | auxane.baptiste@u.nus.edu | spip-admin |
| Michael | e1554354@u.nus.edu | spip-tester |
| Sifan | songsifan@u.nus.edu | spip-backend |

No IAM grants, passwords, invitations or tenant mappings were changed. Tham's existing customer assignment was not changed. These are application group labels carried by newly issued Cognito tokens; they do not grant AWS console/deployment access.

**Enforcement is proposed, not live:** [backend PR #3](https://github.com/sctham26/CS5224-Project/pull/3) targets backend-analysis from proposal/application-rbac-20261108. It adds verified-group permissions, role discovery, backend/admin diagnostics and tenant/process-local cache invalidation, plus admin-only directory and membership interfaces. Teammates choose whether to accept it. No proposal code was pushed directly to backend-analysis or deployed.

The proposed highest application role is admin. Backend has operational capabilities but cannot administer users/memberships. Tester has the same ordinary data operations as customer. All existing data requests remain tenant-scoped even for administrators; no role bypasses RLS. Bootstrap admin group assignment/removal stays with cloud operators to prevent lockout. The proposal document in that PR lists gateway, scoped Cognito IAM and a separate membership-only DB credential needed in a later cloud change; do not grant ordinary application credentials membership writes.

Refresh/re-login to obtain current group claims. Group changes do not rewrite an already issued token. Actual role enforcement requires acceptance, cloud integration and deployment of the proposal; current labels alone do not prove privileged API capabilities exist.

## Reproduce reviewed group assignments

`auth_roles.sandbox.json` pins reviewed email + Cognito subject pairs. The script validates every identity/account before its first mutation, modifies only known application groups, preserves unrelated groups and reads back assignments. It never creates an IAM role or changes membership rows.

```sh
python scripts/configure_application_roles.py auth_roles.sandbox.json --profile sandbox
python scripts/configure_application_roles.py auth_roles.sandbox.json --profile sandbox --apply
```

The first command is a dry run. The second applies the explicit manifest. Keep the manifest reviewed: it is a desired role assignment, not a user-controlled input to the web app.
