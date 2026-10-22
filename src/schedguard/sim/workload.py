import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSpec:
    cls: str
    count: int
    work_ms: int | None = None      # None = CPU-bound forever
    arrival_ms: int = 0
    burst_ms: int | None = None     # None = CPU-bound without voluntary yield
    sleep_ms: int | None = None     # None or 0 = no sleep after burst


@dataclass(frozen=True)
class Workload:
    tasks: tuple[TaskSpec, ...]

    @staticmethod
    def from_counts(counts: dict[str, int]) -> "Workload":
        return Workload(tuple(TaskSpec(c, n) for c, n in counts.items() if n > 0))

    @staticmethod
    def from_dict(raw: dict) -> "Workload":
        tasks = []
        for t in raw.get("tasks", []):
            tasks.append(TaskSpec(
                cls=t["class"],
                count=int(t["count"]),
                work_ms=int(t["work_ms"]) if t.get("work_ms") is not None else None,
                arrival_ms=int(t.get("arrival_ms", 0)),
                burst_ms=int(t["burst_ms"]) if t.get("burst_ms") is not None else None,
                sleep_ms=int(t["sleep_ms"]) if t.get("sleep_ms") is not None else None,
            ))
        return Workload(tuple(tasks))

    @staticmethod
    def from_json(path: str) -> "Workload":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return Workload.from_dict(raw)

    def to_dict(self) -> dict:
        tasks = []
        for t in self.tasks:
            d = {"class": t.cls, "count": t.count}
            if t.work_ms is not None:
                d["work_ms"] = t.work_ms
            if t.arrival_ms:
                d["arrival_ms"] = t.arrival_ms
            if t.burst_ms is not None:
                d["burst_ms"] = t.burst_ms
            if t.sleep_ms is not None:
                d["sleep_ms"] = t.sleep_ms
            tasks.append(d)
        return {"tasks": tasks}

    def to_json(self, path: str, indent: int = 2) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=indent)
