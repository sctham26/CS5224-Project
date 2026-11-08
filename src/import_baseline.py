"""Load the public baseline CSV into ``spip_public.observation``.

Ownership (per Jin, 2026-10-25): the cloud team manages authentication and
authorisation plus ``tenant_membership``; the backend owns data import, and the
baseline is imported exactly like any other dataset — only its ``tenant_id``
(``PUBLIC``) and visibility differ.

Re-running is safe: rows are upserted on
``(tenant_id, entity_id, reporting_year, reporting_scope, metric_code)``, so a
corrected CSV updates in place instead of duplicating observations.

Usage:
    python src/import_baseline.py --data data/cleaned/public_esg_baseline.csv --dry-run
    python src/import_baseline.py --data data/cleaned/public_esg_baseline.csv
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Optional

import pandas as pd

PUBLIC_TENANT = "PUBLIC"
DEFAULT_DATA = "data/cleaned/public_esg_baseline.csv"

REQUIRED_COLUMNS = (
    "entity_id",
    "reporting_scope",
    "reporting_year",
    "metric_code",
)

#: Destination column order; must match migrations/001_public.sql.
COLUMNS = (
    "tenant_id",
    "entity_id",
    "entity_name",
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

UPSERT_KEY = ("tenant_id", "entity_id", "reporting_year", "reporting_scope", "metric_code")

_UPSERT_SQL = f"""
INSERT INTO observation ({", ".join(COLUMNS)})
VALUES ({", ".join(["%s"] * len(COLUMNS))})
ON CONFLICT ({", ".join(UPSERT_KEY)}) DO UPDATE SET
    entity_name = EXCLUDED.entity_name,
    property_type = EXCLUDED.property_type,
    region = EXCLUDED.region,
    standardised_value = EXCLUDED.standardised_value,
    canonical_unit = EXCLUDED.canonical_unit,
    comparability_status = EXCLUDED.comparability_status,
    source_reference = EXCLUDED.source_reference
"""


class ImportError_(Exception):
    """CSV cannot be imported without losing or corrupting observations."""


def _text(value) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def prepare_rows(df: pd.DataFrame, tenant_id: str = PUBLIC_TENANT) -> list[tuple]:
    """Validate and normalise to observation tuples, deduplicated on the upsert key.

    Raises :class:`ImportError_` for a structurally unusable file rather than
    writing partial data, because a silent partial import corrupts every peer
    cohort that follows.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ImportError_(f"missing required column(s): {', '.join(missing)}")

    frame = df.copy()
    frame["reporting_year"] = pd.to_numeric(frame["reporting_year"], errors="coerce")
    bad_years = int(frame["reporting_year"].isna().sum())
    if bad_years:
        raise ImportError_(f"{bad_years} row(s) have a non-numeric reporting_year")
    frame["reporting_year"] = frame["reporting_year"].astype(int)

    frame["standardised_value"] = pd.to_numeric(
        frame.get("standardised_value"), errors="coerce"
    )
    # Scope is stored lower-case, the same shape the engine and adapter expect.
    frame["reporting_scope"] = frame["reporting_scope"].astype(str).str.strip().str.lower()
    frame["tenant_id"] = tenant_id

    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    rows: dict[tuple, tuple] = {}
    for record in frame[list(COLUMNS)].to_dict("records"):
        value = record["standardised_value"]
        record["standardised_value"] = None if pd.isna(value) else float(value)
        for key in ("entity_name", "property_type", "region", "canonical_unit",
                    "comparability_status", "source_reference"):
            record[key] = _text(record[key])
        record["entity_id"] = _text(record["entity_id"])
        if not record["entity_id"] or not _text(record["metric_code"]):
            continue  # unusable observation
        rows[tuple(record[k] for k in UPSERT_KEY)] = tuple(record[c] for c in COLUMNS)

    return list(rows.values())


def load(
    rows: Iterable[tuple],
    database_url: str,
    batch_size: int = 1000,
    dry_run: bool = False,
    tenant_id: Optional[str] = None,
) -> int:
    """Upsert rows in batches; all batches run in one transaction.

    ``tenant_id`` sets the RLS context before writing: the tenant policy's
    ``USING`` clause doubles as the ``INSERT`` check, so without it every row is
    rejected.
    """
    items = list(rows)
    if dry_run:
        return len(items)

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - configuration error
        raise RuntimeError("psycopg is required to import into PostgreSQL") from exc

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if tenant_id:
                cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            for start in range(0, len(items), batch_size):
                batch = items[start : start + batch_size]
                cur.executemany(_UPSERT_SQL, batch)
    return len(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the baseline into spip_public.observation")
    parser.add_argument("--data", default=os.environ.get("SPIP_DATA", DEFAULT_DATA))
    parser.add_argument("--tenant", default=PUBLIC_TENANT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args(argv)

    df = pd.read_csv(args.data)
    rows = prepare_rows(df, tenant_id=args.tenant)
    print(f"prepared {len(rows)} observation(s) from {args.data}")

    url = os.environ.get("SPIP_PUBLIC_DATABASE_URL")
    if not url:
        if args.dry_run:
            print("dry run: no SPIP_PUBLIC_DATABASE_URL, nothing written")
            return 0
        print("SPIP_PUBLIC_DATABASE_URL is required to import", file=sys.stderr)
        return 2

    written = load(rows, url, batch_size=args.batch_size, dry_run=args.dry_run)
    print(f"{'validated' if args.dry_run else 'upserted'} {written} observation(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
