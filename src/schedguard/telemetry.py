"""Versioned real-kernel trace schema and quality accounting."""
from dataclasses import dataclass, asdict, field
import json
from pathlib import Path
from typing import Any

TRACE_SCHEMA = "schedguard.real_trace.v1"


@dataclass
class TelemetryTrace:
    run_id: str
    policy_id: str
    workload_id: str
    seed: int
    kernel_release: str
    events: list[dict[str, Any]] = field(default_factory=list)
    dropped_events: int = 0
    status: str = "INCOMPLETE"
    provenance: str = "real_kernel_bpf"

    def to_dict(self) -> dict[str, Any]:
        return {"schema": TRACE_SCHEMA, **asdict(self),
                "telemetry_complete": self.status == "COMPLETE" and self.dropped_events == 0}

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_trace(path: str | Path) -> TelemetryTrace:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema") != TRACE_SCHEMA or raw.get("provenance") != "real_kernel_bpf":
        raise ValueError("trace is not a schedguard real-kernel v1 trace")
    return TelemetryTrace(raw["run_id"], raw["policy_id"], raw["workload_id"], int(raw["seed"]),
                          raw["kernel_release"], list(raw.get("events", [])), int(raw.get("dropped_events", 0)),
                          raw.get("status", "INCOMPLETE"), raw["provenance"])
