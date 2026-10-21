"""Rule-based, deterministic peer-group selection with configurable fallbacks."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from harmonisation import HarmonisedRecord


@dataclass(frozen=True)
class FallbackRule:
    name: str
    match: tuple[str, ...]


@dataclass(frozen=True)
class PeerRules:
    min_peer_size: int
    fallback_rules: tuple[FallbackRule, ...]


@dataclass(frozen=True)
class PeerGroup:
    """Peers compatible with the target on scope, period, metric and unit."""

    peer_ids: tuple[str, ...]
    applied_rule: Optional[str]
    compatibility: dict[str, str]
    unavailable_reason: Optional[str] = None


def load_peer_rules(path: str | Path) -> PeerRules:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return PeerRules(
        min_peer_size=int(raw["min_peer_size"]),
        fallback_rules=tuple(
            FallbackRule(name=r["name"], match=tuple(r.get("match", [])))
            for r in raw["fallback_rules"]
        ),
    )


class PeerSelector:
    def __init__(self, rules: PeerRules):
        self.rules = rules

    def select(
        self,
        target: HarmonisedRecord,
        candidates: list[HarmonisedRecord],
        metric: str,
    ) -> PeerGroup:
        """Select peers for `metric`; only records reporting the metric qualify."""
        t_metric = target.metrics.get(metric)
        compatibility = {
            "scope": target.scope.value,
            "reporting_period": target.reporting_period,
            "unit": t_metric.canonical_unit if t_metric else "n/a",
        }
        if t_metric is None:
            return PeerGroup(
                peer_ids=(),
                applied_rule=None,
                compatibility=compatibility,
                unavailable_reason="target_metric_missing",
            )

        base = [
            c
            for c in candidates
            if c.entity_id != target.entity_id
            and c.scope == target.scope
            and c.reporting_period == target.reporting_period
            and metric in c.metrics
        ]

        for rule in self.rules.fallback_rules:
            peers = [
                c
                for c in base
                if all(getattr(c, f) == getattr(target, f) for f in rule.match)
            ]
            if len(peers) >= self.rules.min_peer_size:
                return PeerGroup(
                    peer_ids=tuple(sorted(p.entity_id for p in peers)),
                    applied_rule=rule.name,
                    compatibility=compatibility,
                )

        return PeerGroup(
            peer_ids=(),
            applied_rule=None,
            compatibility=compatibility,
            unavailable_reason="insufficient_peers",
        )
