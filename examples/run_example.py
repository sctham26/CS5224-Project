"""End-to-end example: run gap analysis on synthetic data and write JSON output.

Usage (from the repository root):
    python examples/run_example.py [entity_id]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gap_analysis import run_gap_analysis  # noqa: E402


def main() -> None:
    entity_id = sys.argv[1] if len(sys.argv) > 1 else "A001"
    # Run from repo root so provenance paths stay relative and reproducible.
    result = run_gap_analysis(
        data_path="data/synthetic_esg.csv",
        metrics_path="config/metrics.yaml",
        peer_rules_path="config/peer_rules.yaml",
        entity_id=entity_id,
    )
    out = ROOT / "examples" / "output.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({len(result['metrics'])} metrics)")


if __name__ == "__main__":
    main()
