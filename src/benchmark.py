"""Empirical percentile benchmarking against a peer group."""

import statistics

from schemas import MetricDirection


def summarize(values: list[float]) -> dict:
    """Descriptive stats for peer values (deterministic, no interpolation)."""
    return {
        "count": len(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
    }


def rank_in_group(value: float, values: list[float], direction: str) -> int:
    """1-based rank; best performer gets rank 1."""
    if direction == MetricDirection.LOWER_IS_BETTER:
        return sorted(values).index(value) + 1
    return sorted(values, reverse=True).index(value) + 1


def empirical_percentile(value: float, values: list[float], direction: str) -> float:
    """Percentile of `value` within `values` (target included); best = 100th."""
    n = len(values)
    if n <= 1:
        return 100.0
    if direction == MetricDirection.LOWER_IS_BETTER:
        worse = sum(1 for v in values if v > value)
    else:
        worse = sum(1 for v in values if v < value)
    return round(worse / (n - 1) * 100.0, 2)
