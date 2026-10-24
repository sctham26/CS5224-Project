"""End-to-end gap analysis: harmonise -> peers -> benchmark -> structured JSON."""

from pathlib import Path

from benchmark import empirical_percentile, rank_in_group, summarize
from harmonisation import (
    HarmonisedRecord,
    harmonise_records,
    load_records,
    partition_by_scope,
)
from metrics import MetricRegistry
from peers import PeerSelector, load_peer_rules
from schemas import ReportingScope


def _gap_to_median(value: float, median: float, direction: str) -> float:
    """Positive = improvement needed to reach median; negative = already better."""
    return value - median if direction == "lower_is_better" else median - value


def _analyse_metric(
    target: HarmonisedRecord,
    candidates: list[HarmonisedRecord],
    spec,
    selector: PeerSelector,
) -> dict:
    metric = spec.name
    t_obs = target.metrics.get(metric)

    # Disclosure status of the target itself (design 1.1 / 1.3).
    if t_obs is None:
        reason = (
            "incomparable_unit"
            if metric in target.dropped
            else "not_disclosed"
        )
        status = "incompatible" if metric in target.dropped else "missing"
        return {
            "metric": metric,
            "status": "unavailable",
            "comparability_status": status,
            "reason": reason,
            "gap_type": "disclosure_gap",
            "gap_flag": None,
            "peer_count": 0,
            "applied_fallback_rule": None,
            "compatibility": {
                "scope": target.scope.value,
                "reporting_period": target.reporting_period,
                "unit": spec.canonical_unit,
            },
        }

    group = selector.select(target, candidates, metric)
    if group.unavailable_reason:
        return {
            "metric": metric,
            "status": "unavailable",
            "comparability_status": "comparable",
            "reason": group.unavailable_reason,
            "gap_type": None,  # benchmark unavailable, not an entity gap
            "gap_flag": None,
            "peer_count": len(group.peer_ids),
            "applied_fallback_rule": group.applied_rule,
            "compatibility": group.compatibility,
        }

    by_id = {
        c.entity_id: c
        for c in candidates
        if c.reporting_period == target.reporting_period
    }
    peer_values = [by_id[pid].metrics[metric].value for pid in group.peer_ids]

    stats = summarize(peer_values)
    direction = t_obs.direction.value
    ranked = [t_obs.value] + peer_values
    percentile = empirical_percentile(t_obs.value, ranked, direction)
    # Direction-aware percentile: 100 = best, so below threshold = performance gap.
    gap_flag = percentile < spec.gap_percentile_threshold
    return {
        "metric": metric,
        "status": "available",
        "comparability_status": "comparable",
        "reason": None,
        "value": t_obs.value,
        "unit": t_obs.canonical_unit,
        "source_unit": t_obs.source_unit,
        "conversion_factor": t_obs.conversion_factor,
        "source": t_obs.source,
        "direction": direction,
        "peer_count": len(peer_values),
        "applied_fallback_rule": group.applied_rule,
        "compatibility": group.compatibility,
        "peer_ids": list(group.peer_ids),
        "benchmark": stats,
        "rank": rank_in_group(t_obs.value, ranked, direction),
        "percentile": percentile,
        "gap_percentile_threshold": spec.gap_percentile_threshold,
        "gap_to_median": round(_gap_to_median(t_obs.value, stats["median"], direction), 4),
        "gap_flag": gap_flag,
        "gap_type": "performance_gap" if gap_flag else None,
    }


def run_gap_analysis(
    data_path: str | Path,
    metrics_path: str | Path,
    peer_rules_path: str | Path,
    entity_id: str,
    reporting_period: str | None = None,
    scope: ReportingScope = ReportingScope.ASSET,
) -> dict:
    """Analyse one entity against its peer group; asset and portfolio never mixed."""
    registry = MetricRegistry.from_yaml(metrics_path)
    selector = PeerSelector(load_peer_rules(peer_rules_path))
    records = harmonise_records(
        partition_by_scope(load_records(data_path), scope), registry
    )

    targets = [r for r in records if r.entity_id == entity_id]
    if reporting_period:
        targets = [r for r in targets if r.reporting_period == reporting_period]
    if not targets:
        raise ValueError(f"entity {entity_id!r} not found in {scope.value} scope")
    # Multi-period datasets (e.g. BCA baseline 2017-2025): default to the
    # latest period; within one period load_records already merges to one row.
    target = max(targets, key=lambda r: r.reporting_period)

    names = sorted(set(registry.metrics) | set(target.metrics) | set(target.dropped))
    metric_entries = [
        _analyse_metric(target, records, registry.spec(m), selector) for m in names
    ]

    disclosed_gaps = [e["metric"] for e in metric_entries if e["gap_type"] == "disclosure_gap"]
    perf_gaps = [e["metric"] for e in metric_entries if e["gap_type"] == "performance_gap"]

    return {
        "engine_version": "0.1.0",
        "entity_id": target.entity_id,
        "scope": target.scope.value,
        "reporting_period": target.reporting_period,
        "provenance": {
            "data_source": str(data_path),
            "metrics_config": str(metrics_path),
            "peer_rules": str(peer_rules_path),
            "min_peer_size": selector.rules.min_peer_size,
            "fallback_rules": [r.name for r in selector.rules.fallback_rules],
            "gap_percentile_threshold_source": "config/metrics.yaml",
        },
        "summary": {
            "performance_gaps": perf_gaps,
            "disclosure_gaps": disclosed_gaps,
        },
        "metrics": metric_entries,
    }
