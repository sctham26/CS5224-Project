"""End-to-end example: building-level benchmark on the team's public baseline.

Usage (from the repository root):
    python examples/run_example.py [entity_id] [reporting_year]

Defaults to an office building in 2024; the CSV is in the team's long format,
so the result is projected onto the team's output contract.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from contract import analyse_to_contract  # noqa: E402


def main() -> None:
    entity_id = sys.argv[1] if len(sys.argv) > 1 else "SG_228218_LATEST_6"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2024
    # Run from repo root so provenance paths stay relative and reproducible.
    result = analyse_to_contract(
        data_path="data/cleaned/public_esg_baseline.csv",
        entity_id=entity_id,
        metrics_path="config/metrics.yaml",
        peer_rules_path="config/peer_rules.yaml",
        reporting_year=year,
        scope="asset",
    )
    out = ROOT / "examples" / "output.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({len(result['metrics'])} metrics, n={result['peer_cohort']['sample_size_n']})")


if __name__ == "__main__":
    main()
