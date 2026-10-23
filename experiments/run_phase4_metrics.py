"""Generate the Phase 4 evaluation status without fabricating real data."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments" / "results" / "phase4_metrics.json"


def main() -> None:
    result = {
        "schema": "schedguard.phase4_metrics.v1",
        "status": "NOT_RUN",
        "reason": "No genuine paired Linux sched_ext simulator/real-kernel observations are available in this environment.",
        "environment": {"host": "Windows", "target_kernel": "Linux 6.12+", "seed": 0},
        "conditions": {name: {"status": "NOT_RUN", "samples": 0} for name in
                       ("existing_gate", "constant_error_baseline", "learned_predictor", "full_gate")},
        "limitations": ["kernel compilation/load not run", "real telemetry not collected", "predictor accuracy not validated"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "status": result["status"]}, indent=2))


if __name__ == "__main__":
    main()
