import json
import sys

sys.path.insert(0, "src")
from contract import analyse_to_contract

out = analyse_to_contract(
    data_path="data/synthetic_esg.csv",
    entity_id="A001",
    metrics_path="config/metrics.yaml",
    peer_rules_path="config/peer_rules.yaml",
    reporting_year=2024,
    scope="asset",
    tenant_id=None,
)
print("cohort:", json.dumps(out["peer_cohort"]))
for m in out["metrics"]:
    b = m["benchmark"]
    print(
        f"{m['metric_code']:32} value={m['standardised_value']} unit={m['canonical_unit']:14}"
        f" median={None if b is None else b['peer_median']}"
        f" pct={None if b is None else b['empirical_percentile']}"
        f" status={m['comparability_status']}"
        f" gap={m['gap_analysis']['gap_type']}"
    )
