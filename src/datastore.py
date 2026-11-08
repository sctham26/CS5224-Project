"""Tenant-scoped data source for the analytics API.

Keeps the engine's no-database boundary: callers get a DataFrame in the team's
long format (``metric_code`` / ``standardised_value`` / ``reporting_scope``).
Two implementations, selected by environment:

* ``CsvDataSource`` — local development and examples (``SPIP_DATA``).
* ``PostgresDataSource`` — ``SPIP_PUBLIC_DATABASE_URL`` / ``SPIP_TENANT_DATABASE_URL``.

A tenant always sees the public baseline plus its own private rows. Rows owned by
another tenant are never returned, which is what makes entity reads authorisable.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

import pandas as pd

PUBLIC_TENANT = "PUBLIC"

#: Columns the adapter expects (team long format, PR #1).
FRAME_COLUMNS = (
    "tenant_id",
    "entity_id",
    "entity_name",
    "postal_code",
    "property_type",
    "region",
    "reporting_scope",
    "reporting_year",
    "metric_code",
    "standardised_value",
    "canonical_unit",
    "comparability_status",
    "source_reference",
)

#: Columns selected from PostgreSQL; same names as the team CSV.
_SQL_COLUMNS = ", ".join(FRAME_COLUMNS)


class DataSource(Protocol):
    """Loads the records a tenant is allowed to analyse."""

    def load(self, tenant_id: str) -> pd.DataFrame: ...


@dataclass(frozen=True)
class _Entry:
    expires_at: float
    frame: pd.DataFrame


class _TtlCache:
    """Small process-local cache; PostgreSQL loads are expensive per request."""

    def __init__(self, ttl_seconds: float):
        self.ttl = ttl_seconds
        self._entries: dict[tuple, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Optional[pd.DataFrame]:
        with self._lock:
            hit = self._entries.get(key)
            if hit and hit.expires_at > time.monotonic():
                return hit.frame
            self._entries.pop(key, None)
            return None

    def invalidate_tenant(self, tenant_id: str) -> int:
        with self._lock:
            keys = [key for key in self._entries if key[-1] == tenant_id]
            for key in keys:
                del self._entries[key]
            return len(keys)

    def put(self, key: tuple, frame: pd.DataFrame) -> pd.DataFrame:
        with self._lock:
            self._entries[key] = _Entry(time.monotonic() + self.ttl, frame)
        return frame


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce dtypes the adapter relies on and fill absent optional columns."""
    out = df.copy()
    for col in FRAME_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[list(FRAME_COLUMNS)]


class CsvDataSource:
    """Local CSV source; tenant rows are filtered by the ``tenant_id`` column."""

    def __init__(self, path: str | Path, ttl_seconds: float = 60.0):
        self.path = Path(path)
        self._cache = _TtlCache(ttl_seconds)

    def invalidate(self, tenant_id: str) -> int:
        return self._cache.invalidate_tenant(tenant_id)

    def load(self, tenant_id: str) -> pd.DataFrame:
        # mtime is part of the key, so editing the CSV invalidates immediately.
        mtime = self.path.stat().st_mtime if self.path.exists() else 0.0
        key = ("csv", str(self.path), mtime, tenant_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        df = _normalise(pd.read_csv(self.path))
        visible = df[
            df["tenant_id"].isna()
            | (df["tenant_id"].astype(str) == PUBLIC_TENANT)
            | (df["tenant_id"].astype(str) == tenant_id)
        ]
        return self._cache.put(key, visible.reset_index(drop=True))


class PostgresDataSource:
    """Reads the public baseline and the current tenant's private rows.

    The two logical databases cannot be joined server-side, so both frames are
    concatenated here. Tenant tables are additionally guarded by row-level
    security; ``SET LOCAL app.tenant_id`` supplies the trusted context.
    """

    def __init__(
        self,
        public_url: str,
        tenant_url: str | None,
        ttl_seconds: float = 30.0,
    ):
        self.public_url = public_url
        self.tenant_url = tenant_url
        self._cache = _TtlCache(ttl_seconds)

    def invalidate(self, tenant_id: str) -> int:
        return self._cache.invalidate_tenant(tenant_id)

    def load(self, tenant_id: str) -> pd.DataFrame:
        key = ("pg", tenant_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        frames = [
            self._query(
                self.public_url,
                f"SELECT {_SQL_COLUMNS} FROM observation WHERE tenant_id = %s",
                (PUBLIC_TENANT,),
            )
        ]
        if self.tenant_url:
            frames.append(
                self._query(
                    self.tenant_url,
                    f"SELECT {_SQL_COLUMNS} FROM observation WHERE tenant_id = %s",
                    (tenant_id,),
                    tenant_id=tenant_id,
                )
            )
        visible = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return self._cache.put(key, _normalise(visible).reset_index(drop=True))

    @staticmethod
    def _query(
        url: str,
        sql: str,
        params: tuple,
        tenant_id: str | None = None,
    ) -> pd.DataFrame:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - configuration error
            raise RuntimeError(
                "psycopg is required when SPIP_PUBLIC_DATABASE_URL is set"
            ) from exc

        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                if tenant_id:
                    # Trusted tenant context for row-level security; LOCAL keeps it
                    # scoped to this transaction only.
                    cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                cur.execute(sql, params)
                rows = cur.fetchall()
                columns = [c.name for c in cur.description]
        return pd.DataFrame(rows, columns=columns)


def build_data_source(environ: dict[str, str] | None = None) -> DataSource:
    """PostgreSQL when configured (cloud), otherwise the local CSV."""
    env = os.environ if environ is None else environ
    public_url = env.get("SPIP_PUBLIC_DATABASE_URL")
    if public_url:
        return PostgresDataSource(
            public_url=public_url,
            tenant_url=env.get("SPIP_TENANT_DATABASE_URL"),
            ttl_seconds=float(env.get("SPIP_CACHE_TTL_SECONDS", 30)),
        )
    return CsvDataSource(
        path=env.get("SPIP_DATA", "data/cleaned/public_esg_baseline.csv"),
        ttl_seconds=float(env.get("SPIP_CACHE_TTL_SECONDS", 60)),
    )
