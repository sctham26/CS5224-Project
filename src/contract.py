"""Adapter between the engine's internals and the team's output contract (PR #1).

Source of truth: schemas/analytics_output_contract.json + docs/metric_dictionary.csv.
Input accepts either the team's long CSV (metric_code / standardised_value /
comparability_status) or the engine's own long format. Output is their
SPIPCanonicalAnalyticsOutput. Boundary-only: the six core modules are untouched.
"""

from __future__ import annotations

import os
import tempfile

import pandas as pd

from gap_analysis import run_gap_analysis
from metrics import (
    IncompatibleUnitError,
    MetricRegistry,
    UnknownMetricError,
)
from peers import load_peer_rules
from schemas import ReportingScope

# Team CSV columns that identify their format.
THEIR_COLUMNS = ("metric_code", "reporting_year", "standardised_value", "reporting_scope")
# Disclosed but not benchmarkable (per data_handoff.md / contract enum).
NOT_COMPARABLE_INPUT = frozenset({"BOUNDARY_MISMATCH", "ANOMALY_FLAGGED"})
COMPARABLE_INPUT = frozenset({"COMPARABLE", "UNIT_CONVERTED"})
UNIT_CONVERTED = "UNIT_CONVERTED"


class ContractInputError(ValueError):
    """Input metric_code is not declared in the metric dictionary."""


class EntityNotFound(ValueError):
    """Target entity / reporting period is absent from the dataset."""


def _is_their_format(df: pd.DataFrame) -> bool:
    return set(THEIR_COLUMNS) <= set(df.columns)


def _validate_metric_codes(df: pd.DataFrame, registry: MetricRegistry) -> None:
    if not _is_their_format(df):
        return
    for code in sorted(set(df["metric_code"].dropna())):
        try:
            registry.spec(str(code))
        except UnknownMetricError:
            raise ContractInputError(
                f"unknown metric_code {code!r} (not in metric dictionary)"
            ) from None


def _engine_csv(df: pd.DataFrame) -> str:
    """Write their long format as the engine's long format (temp file).

    Rows that are not benchmarkable (boundary mismatch, anomaly, no value) are
    omitted, so the engine treats them as undisclosed and reports a gap.
    """
    ok = df["comparability_status"].isin(COMPARABLE_INPUT) & df["standardised_value"].notna()
    body = df[ok]
    eng = pd.DataFrame(
        {
            "entity_id": body["entity_id"].astype(str),
            "scope": body["reporting_scope"].astype(str).str.lower(),
            "reporting_period": body["reporting_year"].astype(str),
            "region": body["region"],
            "property_type": body["property_type"],
            "metric": body["metric_code"].astype(str),
            "value": body["standardised_value"].astype(float),
            "unit": body["canonical_unit"].astype(str),
        }
    )
    eng["certification"] = None
    eng["source"] = body["source_reference"] if "source_reference" in df.columns else None
    for col in ("region", "property_type", "source"):
        # Engine schema is Optional[str]; float NaN would fail validation.
        eng[col] = eng[col].astype(object).where(pd.notna(eng[col]), None)

    fd, path = tempfile.mkstemp(prefix="spip-in-", suffix=".csv")
    os.close(fd)
    eng.to_csv(path, index=False)
    return path


ENGINE_COLUMNS = (
    "entity_id",
    "scope",
    "reporting_period",
    "region",
    "property_type",
    "certification",
    "metric",
    "value",
    "unit",
    "source",
)


def _frame_to_engine_csv(df: pd.DataFrame) -> str:
    """Write an engine-format DataFrame to a unique temp CSV for the engine seam."""
    fd, path = tempfile.mkstemp(prefix="spip-engine-", suffix=".csv")
    os.close(fd)
    df.reindex(columns=list(ENGINE_COLUMNS)).to_csv(path, index=False)
    return path


def _target_rows(df: pd.DataFrame, entity_id: str, period: str, their: bool) -> pd.DataFrame:
    col = "reporting_year" if their else "reporting_period"
    if col not in df.columns or "entity_id" not in df.columns:
        return df.iloc[0:0]
    mask = (df["entity_id"].astype(str) == entity_id) & (df[col].astype(str) == period)
    return df[mask]


def _to_contract(
    result: dict,
    df: pd.DataFrame,
    entity_id: str,
    registry: MetricRegistry,
    peer_rules_path: str | Path,
    tenant_id: str | None = None,
) -> dict:
    their = _is_their_format(df)
    rows = _target_rows(df, entity_id, result["reporting_period"], their)

    name = tenant = prop = region = None
    statuses: dict[str, str] = {}
    converted_in: set[str] = set()  # metrics whose raw_unit differs from canonical
    values: dict[str, tuple[float, float]] = {}  # code -> (canonical value, factor)

    for _, r in rows.iterrows():
        if their:
            code = str(r.get("metric_code"))
            if not name and isinstance(r.get("entity_name"), str):
                name = r["entity_name"]
            if not tenant and isinstance(r.get("tenant_id"), str):
                tenant = r["tenant_id"]
            st = r.get("comparability_status")
            if code not in statuses and isinstance(st, str):
                statuses[code] = st
            raw, unit = r.get("standardised_value"), r.get("canonical_unit")
            raw_unit = r.get("raw_unit")
            if isinstance(raw_unit, str) and isinstance(unit, str) and raw_unit != unit:
                converted_in.add(code)
        else:
            code = str(r.get("metric"))
            raw, unit = r.get("value"), r.get("unit")
        if prop is None and isinstance(r.get("property_type"), str):
            prop = r["property_type"]
        if region is None and isinstance(r.get("region"), str):
            region = r["region"]
        if not isinstance(unit, str) or raw is None or pd.isna(raw):
            continue
        try:
            spec = registry.spec(code)
            values[code] = (float(raw) * spec.factors[unit], spec.factors[unit])
        except (UnknownMetricError, KeyError):
            pass

    min_n = result["provenance"]["min_peer_size"]
    metrics = []
    for e in result["metrics"]:
        code = e["metric"]
        spec = registry.spec(code)
        unit = spec.canonical_unit
        st_in = statuses.get(code)

        if e["status"] == "available":
            value = e["value"]
            conv = e.get("conversion_factor") or 1.0
            converted = conv != 1.0 or code in converted_in or st_in == UNIT_CONVERTED
            status = UNIT_CONVERTED if converted else "COMPARABLE"
            benchmark = {
                "peer_median": e["benchmark"]["median"],
                "relative_rank": e["rank"],
                "empirical_percentile": e["percentile"],
            }
            delta = e["gap_to_median"]
            if e["gap_flag"]:
                gap_type, flagged = "PERFORMANCE_GAP", True
                signal = (
                    f"{code}: at {e['percentile']:g}th percentile "
                    f"(< {spec.gap_percentile_threshold:g}); close {delta:g} {unit} "
                    "to reach the peer median."
                )
            else:
                gap_type, flagged = "NONE", False
                signal = (
                    f"{code}: meets the {spec.gap_percentile_threshold:g}th-percentile "
                    f"threshold against the peer median of {benchmark['peer_median']:g} {unit}."
                )
        elif e.get("reason") == "insufficient_peers":
            # Disclosed, but no peer cohort could be formed.
            hit = values.get(code)
            value = hit[0] if hit else None
            conv = hit[1] if hit else 1.0
            converted = conv != 1.0 or code in converted_in or st_in == UNIT_CONVERTED
            status = UNIT_CONVERTED if converted else "COMPARABLE"
            benchmark = None
            # Not benchmarked: neither "no gap" nor a flag (INTERFACES.md: null).
            gap_type, flagged, delta = None, None, None
            signal = f"{code}: peer cohort unavailable (n < {min_n} after fallback); benchmark not asserted."
        else:
            value, benchmark, delta = None, None, None
            if e["reason"] == "incomparable_unit":
                status = "BOUNDARY_MISMATCH"
                signal = (
                    f"{code}: disclosed value is not comparable at {unit}; "
                    "confirm the measurement boundary or supply a convertible unit."
                )
            else:
                status = st_in if st_in in NOT_COMPARABLE_INPUT else "INCOMPLETE_DATA"
                signal = (
                    f"{code}: not disclosed for {result['reporting_period']}; "
                    "request disclosure to enable benchmarking."
                )
            gap_type, flagged = "DISCLOSURE_GAP", True

        gap_block = {
            "gap_type": gap_type,
            "is_flagged": flagged,
            "threshold_percentile": spec.gap_percentile_threshold,
            "recommendation_signal": signal,
        }
        if delta is not None:
            gap_block["delta_to_peer_median"] = delta

        metrics.append(
            {
                "metric_code": code,
                "standardised_value": value,
                "canonical_unit": unit,
                "performance_direction": spec.direction.value.upper(),
                "comparability_status": status,
                "benchmark": benchmark,
                "gap_analysis": gap_block,
            }
        )

    # One cohort per entity; reported from the metric with the largest peer group.
    avail = [e for e in result["metrics"] if e["status"] == "available"]
    rules = load_peer_rules(peer_rules_path)
    strict = rules.fallback_rules[0].name if rules.fallback_rules else None
    if avail:
        primary = max(avail, key=lambda e: e["peer_count"])  # first max = deterministic
        n = primary["peer_count"]
        rule = primary.get("applied_fallback_rule")
        relaxed = bool(rule and strict and rule != strict)
        reason = rule if relaxed else None
    else:
        n, relaxed, reason = 0, False, "insufficient_peers"

    return {
        "entity_id": result["entity_id"],
        "entity_name": name or entity_id,
        # The authenticated tenant always wins over a client-supplied column.
        "tenant_id": tenant_id or tenant or "PUBLIC",
        "reporting_year": int(result["reporting_period"]),
        "peer_cohort": {
            "property_type": prop or "",
            "region": region or "",
            "sample_size_n": n,
            "fallback_applied": relaxed,
            "fallback_reason": reason,
        },
        "metrics": metrics,
    }


def analyse_to_contract(
    data_path: str | Path,
    entity_id: str,
    metrics_path: str | Path,
    peer_rules_path: str | Path,
    reporting_year: int | None = None,
    scope: str = "asset",
    tenant_id: str | None = None,
) -> dict:
    """Read a CSV and project the engine result onto the team's output contract."""
    try:
        df = pd.read_csv(data_path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise ContractInputError(f"unreadable CSV: {exc}") from None
    return analyse_dataframe_to_contract(
        df=df,
        entity_id=entity_id,
        metrics_path=metrics_path,
        peer_rules_path=peer_rules_path,
        reporting_year=reporting_year,
        scope=scope,
        tenant_id=tenant_id,
    )


def analyse_dataframe_to_contract(
    df: pd.DataFrame,
    entity_id: str,
    metrics_path: str | Path,
    peer_rules_path: str | Path,
    reporting_year: int | None = None,
    scope: str = "asset",
    tenant_id: str | None = None,
) -> dict:
    """Same contract projection for an already-loaded long-format DataFrame.

    Used by the database-backed API so the engine keeps its no-database boundary.
    """
    registry = MetricRegistry.from_yaml(metrics_path)
    _validate_metric_codes(df, registry)

    engine_path = _engine_csv(df) if _is_their_format(df) else _frame_to_engine_csv(df)
    period = None if reporting_year is None else str(int(reporting_year))
    try:
        result = run_gap_analysis(
            data_path=engine_path,
            metrics_path=metrics_path,
            peer_rules_path=peer_rules_path,
            entity_id=entity_id,
            reporting_period=period,
            scope=ReportingScope(scope),
        )
    except ValueError as exc:  # entity not found in this scope/period
        raise EntityNotFound(str(exc)) from None
    finally:
        try:
            os.unlink(engine_path)
        except OSError:
            pass

    return _to_contract(result, df, entity_id, registry, peer_rules_path, tenant_id)
