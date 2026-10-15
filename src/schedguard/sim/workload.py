import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSpec:
    cls: str
    count: int
    work_ms: int | None = None      # None = CPU-bound forever
    arrival_ms: int = 0


@dataclass(frozen=True)
class Workload:
    tasks: tuple[TaskSpec, ...]

    @staticmethod
    def from_counts(counts: dict[str, int]) -> "Workload":
        return Workload(tuple(TaskSpec(c, n) for c, n in counts.items() if n > 0))

    @staticmethod
    def from_json(path: str) -> "Workload":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return Workload(tuple(TaskSpec(t["class"], int(t["count"]),
                                       int(t["work_ms"]) if t.get("work_ms") is not None else None,
                                       int(t.get("arrival_ms", 0))) for t in raw["tasks"]))
