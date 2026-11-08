"""Application permissions derived only from verified Cognito groups."""
from __future__ import annotations

ROLE_GROUPS = {"spip-admin": "admin", "spip-backend": "backend", "spip-tester": "tester", "spip-customer": "customer"}
ROLE_PERMISSIONS = {
    "customer": frozenset({"data:use"}),
    "tester": frozenset({"data:use"}),
    "backend": frozenset({"data:use", "ops:read", "cache:invalidate"}),
    "admin": frozenset({"data:use", "ops:read", "cache:invalidate", "users:read", "roles:write", "memberships:write"}),
}

def role_for(groups: tuple[str, ...]) -> str:
    for group, role in ROLE_GROUPS.items():
        if group in groups:
            return role
    # Existing invited customers without a group keep normal tenant operations.
    return "customer"

def permissions_for(groups: tuple[str, ...]) -> frozenset[str]:
    return ROLE_PERMISSIONS[role_for(groups)]
