"""Metric registry: direction, scope and unit conversion driven by config/metrics.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from schemas import MetricDirection, ReportingScope


class UnknownMetricError(KeyError):
    """Metric name not declared in the registry."""


class IncompatibleUnitError(ValueError):
    """Unit is not declared as convertible for the given metric."""


@dataclass(frozen=True)
class MetricSpec:
    name: str
    canonical_unit: str
    direction: MetricDirection
    scopes: tuple[ReportingScope, ...]
    factors: dict[str, float] = field(default_factory=dict)
    gap_percentile_threshold: float = 40.0

    def supports(self, scope: ReportingScope) -> bool:
        return scope in self.scopes


class MetricRegistry:
    def __init__(self, metrics: dict[str, MetricSpec]):
        self.metrics = metrics

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MetricRegistry":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["metrics"]
        parsed: dict[str, MetricSpec] = {}
        for name, cfg in raw.items():
            parsed[name] = MetricSpec(
                name=name,
                canonical_unit=cfg["canonical_unit"],
                direction=MetricDirection(cfg["direction"]),
                scopes=tuple(ReportingScope(s) for s in cfg["scopes"]),
                factors=dict(cfg.get("factors", {})),
                gap_percentile_threshold=float(cfg.get("gap_percentile_threshold", 40.0)),
            )
        return cls(parsed)

    def spec(self, metric: str) -> MetricSpec:
        try:
            return self.metrics[metric]
        except KeyError:
            raise UnknownMetricError(metric) from None

    def convert(self, metric: str, value: float, unit: str) -> float:
        """Convert `value` from `unit` into the metric's canonical unit."""
        spec = self.spec(metric)
        factor = spec.factors.get(unit)
        if factor is None:
            raise IncompatibleUnitError(f"{metric}: unsupported unit {unit!r}")
        return value * factor
