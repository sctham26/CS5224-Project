"""Load raw ESG records and harmonise every metric into its canonical unit."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from metrics import IncompatibleUnitError, MetricRegistry, UnknownMetricError
from schemas import ESGRecord, MetricDirection, MetricObservation, ReportingScope


@dataclass(frozen=True)
class HarmonisedMetric:
    value: float
    canonical_unit: str
    direction: MetricDirection
    source_unit: str
    conversion_factor: float
    source: Optional[str] = None


@dataclass(frozen=True)
class HarmonisedRecord:
    """One entity/period report, all metric values in canonical units."""

    entity_id: str
    scope: ReportingScope
    reporting_period: str
    region: Optional[str]
    property_type: Optional[str]
    certification: Optional[str]
    metrics: dict[str, HarmonisedMetric]
    dropped: dict[str, str]


def _opt(value) -> Optional[str]:
    """Normalize a possibly-missing CSV cell to str | None (NaN is not falsy)."""
    if value is None or pd.isna(value):
        return None
    s = str(value).strip()
    return s or None


def load_records(path: str | Path) -> list[ESGRecord]:
    """Parse the long-format CSV into one ESGRecord per entity/period."""
    merged: dict[tuple, ESGRecord] = {}
    df = pd.read_csv(path)
    for row in df.to_dict(orient="records"):
        key = (row["entity_id"], row["reporting_period"])
        obs = MetricObservation(
            value=float(row["value"]),
            unit=row["unit"],
            source=_opt(row.get("source")),
        )
        if key in merged:
            merged[key].metrics[row["metric"]] = obs
        else:
            merged[key] = ESGRecord(
                entity_id=row["entity_id"],
                scope=ReportingScope(row["scope"]),
                reporting_period=str(row["reporting_period"]),
                region=_opt(row["region"]),
                property_type=_opt(row["property_type"]),
                certification=_opt(row["certification"]),
                metrics={row["metric"]: obs},
            )
    return list(merged.values())


def partition_by_scope(
    records: list[ESGRecord], scope: ReportingScope
) -> list[ESGRecord]:
    """Split records by scope; asset and portfolio analyses must never be mixed."""
    return [r for r in records if r.scope == scope]


def harmonise_records(
    records: list[ESGRecord], registry: MetricRegistry
) -> list[HarmonisedRecord]:
    """Convert every metric to its canonical unit, dropping unsupported ones."""
    out: list[HarmonisedRecord] = []
    for rec in records:
        metrics: dict[str, HarmonisedMetric] = {}
        dropped: dict[str, str] = {}
        for name, obs in rec.metrics.items():
            try:
                spec = registry.spec(name)
            except UnknownMetricError:
                dropped[name] = "unknown_metric"
                continue
            try:
                value = registry.convert(name, obs.value, obs.unit)
            except (IncompatibleUnitError, UnknownMetricError):
                dropped[name] = "unsupported_unit"
                continue
            factor = spec.factors[obs.unit]
            metrics[name] = HarmonisedMetric(
                value=value,
                canonical_unit=spec.canonical_unit,
                direction=spec.direction,
                source_unit=obs.unit,
                conversion_factor=factor,
                source=obs.source,
            )
        out.append(
            HarmonisedRecord(
                entity_id=rec.entity_id,
                scope=rec.scope,
                reporting_period=rec.reporting_period,
                region=rec.region,
                property_type=rec.property_type,
                certification=rec.certification,
                metrics=metrics,
                dropped=dropped,
            )
        )
    return out
