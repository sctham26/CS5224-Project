"""Pydantic schemas for ESG records and analysis results."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ReportingScope(str, Enum):
    """Reporting granularity. Asset and portfolio scopes are never mixed."""

    ASSET = "asset"
    PORTFOLIO = "portfolio"


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class ComparabilityStatus(str, Enum):
    """Comparability of a metric observation, per the common schema (design 1.1)."""

    COMPARABLE = "comparable"
    MISSING = "missing"  # not disclosed for this entity/period
    INCOMPATIBLE = "incompatible"  # disclosed, but unit/scope not comparable


class MetricObservation(BaseModel):
    """A single reported metric value with its unit and provenance as submitted."""

    value: float = Field(ge=0.0, description="Reported value, must be non-negative")
    unit: str = Field(min_length=1)
    source: Optional[str] = Field(
        default=None, description="Where the observation came from (report/dataset/curation)"
    )


class ESGRecord(BaseModel):
    """One entity's ESG report for a single reporting period."""

    entity_id: str = Field(min_length=1)
    scope: ReportingScope
    reporting_period: str = Field(min_length=1)
    region: Optional[str] = None
    property_type: Optional[str] = None
    certification: Optional[str] = None
    metrics: dict[str, MetricObservation] = Field(default_factory=dict)
    dropped: dict[str, str] = Field(
        default_factory=dict,
        description="metric -> reason it was excluded during harmonisation",
    )
