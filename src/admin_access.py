"""Privileged adapters; credentials remain separate from ordinary tenant access."""
from __future__ import annotations
import os
import uuid
from contextlib import contextmanager
from rbac import ROLE_GROUPS

class AdminUnavailable(Exception):
    pass

class ProtectedAdministrator(Exception):
    pass

class CognitoDirectory:
    def __init__(self, pool_id=None, client=None):
        self.pool_id = pool_id or os.environ.get("SPIP_AUTH_USER_POOL_ID")
        self._client = client

    @property
    def client(self):
        if not self.pool_id:
            raise AdminUnavailable("User directory is not configured")
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client("cognito-idp", config=Config(
                connect_timeout=3, read_timeout=5, retries={"mode": "standard", "total_max_attempts": 2}))
        return self._client

    def list_users(self, next_token=None):
        args = {"UserPoolId": self.pool_id, "Limit": 25}
        if next_token:
            args["PaginationToken"] = next_token
        result = self.client.list_users(**args)
        users = []
        for user in result.get("Users", []):
            attrs = {a["Name"]: a["Value"] for a in user.get("Attributes", [])}
            users.append({"subject": attrs.get("sub"), "email": attrs.get("email"),
                "enabled": user.get("Enabled", False), "status": user.get("UserStatus")})
        return {"users": users, "next_token": result.get("PaginationToken")}

    def set_role(self, subject, role):
        subject = str(uuid.UUID(subject))
        group = next((g for g, r in ROLE_GROUPS.items() if r == role), None)
        if group is None or role == "admin":
            raise ProtectedAdministrator("Administrator grants are managed by cloud operators")
        args = {"UserPoolId": self.pool_id, "Username": subject}
        existing = {g["GroupName"] for g in self.client.admin_list_groups_for_user(**args).get("Groups", [])}
        if "spip-admin" in existing:
            raise ProtectedAdministrator("Administrator grants are managed by cloud operators")
        # Demote first: a partial failure must not retain a higher application role.
        for old in sorted((existing & ROLE_GROUPS.keys()) - {group}):
            self.client.admin_remove_user_from_group(**args, GroupName=old)
        self.client.admin_add_user_to_group(**args, GroupName=group)
        actual = {g["GroupName"] for g in self.client.admin_list_groups_for_user(**args).get("Groups", [])}
        if actual & ROLE_GROUPS.keys() != {group}:
            raise AdminUnavailable("Role update could not be verified")
        return {"subject": subject, "role": role}

class MembershipAdministration:
    def __init__(self, url=None):
        self.url = url or os.environ.get("SPIP_MEMBERSHIP_ADMIN_DATABASE_URL")

    @contextmanager
    def _connect(self):
        if not self.url:
            raise AdminUnavailable("Membership administration is not configured")
        import psycopg
        with psycopg.connect(self.url) as conn:
            yield conn

    def set_membership(self, subject, tenant_id, active):
        subject = str(uuid.UUID(subject))
        with self._connect() as conn:
            conn.execute("SELECT set_config('app.user_sub',%s,true)", (subject,))
            conn.execute("INSERT INTO app.tenant_membership(user_sub,tenant_id,active) VALUES (%s,%s,%s) "
                "ON CONFLICT(user_sub) DO UPDATE SET tenant_id=excluded.tenant_id,active=excluded.active",
                (subject, tenant_id, active))
        return {"subject": subject, "tenant_id": tenant_id, "active": active}
