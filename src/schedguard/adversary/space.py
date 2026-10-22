"""Bounded parameter space for adversarial workloads and strict specification validation."""
import json
import random
from typing import Any
from ..ir import IRPolicy
from ..sim.workload import TaskSpec, Workload

BURST_CHOICES = (2, 5, 10, 20, 50, 100)
SLEEP_CHOICES = (0, 5, 10, 20, 50, 100, 200)
ARRIVAL_CHOICES = (0, 5, 10, 25, 50, 100, 200, 500)
MAX_TOTAL_TASKS = 24


def random_workload(rng: random.Random, ir: IRPolicy) -> Workload:
    """Sample a random dynamic workload respecting IR limits."""
    tasks = []
    total = 0
    # Pick counts per class
    for c in ir.classes:
        # Guarantee at least some classes have tasks
        max_allowed = min(ir.max_tasks, MAX_TOTAL_TASKS - total)
        if max_allowed <= 0:
            break
        # Random count between 0 and max_allowed
        count = rng.randint(0, max_allowed)
        if count > 0:
            burst = rng.choice(BURST_CHOICES) if rng.random() < 0.7 else None
            sleep = rng.choice(SLEEP_CHOICES) if burst is not None else 0
            arrival = rng.choice(ARRIVAL_CHOICES) if rng.random() < 0.4 else 0
            tasks.append(TaskSpec(
                cls=c.name,
                count=count,
                arrival_ms=arrival,
                burst_ms=burst,
                sleep_ms=sleep if sleep > 0 else None,
            ))
            total += count

    if not tasks:
        # Ensure at least 1 task
        c = rng.choice(ir.classes)
        tasks.append(TaskSpec(cls=c.name, count=1))

    return Workload(tuple(tasks))


def mutate_workload(workload: Workload, rng: random.Random, ir: IRPolicy) -> Workload:
    """Mutate an existing workload slightly, maintaining validity."""
    class_names = [c.name for c in ir.classes]
    tasks = list(workload.tasks)
    if not tasks:
        return random_workload(rng, ir)

    mutation_type = rng.choice(["tweak_count", "tweak_burst", "tweak_sleep", "tweak_arrival", "add_class"])

    if mutation_type == "tweak_count":
        idx = rng.randrange(len(tasks))
        t = tasks[idx]
        delta = rng.choice([-1, 1])
        new_cnt = max(1, min(ir.max_tasks, t.count + delta))
        tasks[idx] = TaskSpec(
            cls=t.cls, count=new_cnt, work_ms=t.work_ms,
            arrival_ms=t.arrival_ms, burst_ms=t.burst_ms, sleep_ms=t.sleep_ms,
        )

    elif mutation_type == "tweak_burst":
        idx = rng.randrange(len(tasks))
        t = tasks[idx]
        new_b = rng.choice(BURST_CHOICES)
        tasks[idx] = TaskSpec(
            cls=t.cls, count=t.count, work_ms=t.work_ms,
            arrival_ms=t.arrival_ms, burst_ms=new_b, sleep_ms=t.sleep_ms,
        )

    elif mutation_type == "tweak_sleep":
        idx = rng.randrange(len(tasks))
        t = tasks[idx]
        new_s = rng.choice(SLEEP_CHOICES)
        tasks[idx] = TaskSpec(
            cls=t.cls, count=t.count, work_ms=t.work_ms,
            arrival_ms=t.arrival_ms, burst_ms=t.burst_ms,
            sleep_ms=new_s if new_s > 0 else None,
        )

    elif mutation_type == "tweak_arrival":
        idx = rng.randrange(len(tasks))
        t = tasks[idx]
        new_arr = rng.choice(ARRIVAL_CHOICES)
        tasks[idx] = TaskSpec(
            cls=t.cls, count=t.count, work_ms=t.work_ms,
            arrival_ms=new_arr, burst_ms=t.burst_ms, sleep_ms=t.sleep_ms,
        )

    elif mutation_type == "add_class":
        existing_classes = {t.cls for t in tasks}
        missing = [c for c in class_names if c not in existing_classes]
        if missing:
            c_name = rng.choice(missing)
            tasks.append(TaskSpec(cls=c_name, count=rng.randint(1, min(ir.max_tasks, 4))))

    # Enforce total and per-class limits
    counts = {c: 0 for c in class_names}
    validated_tasks = []
    total = 0
    for t in tasks:
        if t.cls not in counts:
            continue
        allowed = min(ir.max_tasks - counts[t.cls], MAX_TOTAL_TASKS - total)
        if allowed > 0:
            actual_count = min(t.count, allowed)
            validated_tasks.append(TaskSpec(
                cls=t.cls, count=actual_count, work_ms=t.work_ms,
                arrival_ms=t.arrival_ms, burst_ms=t.burst_ms, sleep_ms=t.sleep_ms,
            ))
            counts[t.cls] += actual_count
            total += actual_count

    if not validated_tasks:
        return random_workload(rng, ir)

    return Workload(tuple(validated_tasks))


def validate_spec(raw: Any, ir: IRPolicy) -> tuple[bool, str, Workload | None]:
    """Strictly validate an untrusted workload specification dict or JSON string.

    Returns:
        (is_valid: bool, reason: str, workload: Workload | None)
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception as e:
            return False, f"Invalid JSON string: {e}", None

    if not isinstance(raw, dict):
        return False, "Workload specification must be a JSON object", None

    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, list):
        return False, "Missing or invalid 'tasks' array in specification", None

    if len(tasks_raw) == 0:
        return False, "'tasks' array cannot be empty", None

    known_classes = {c.name for c in ir.classes}
    per_class_counts = {c.name: 0 for c in ir.classes}
    parsed_tasks: list[TaskSpec] = []
    total_tasks = 0

    for i, t in enumerate(tasks_raw):
        if not isinstance(t, dict):
            return False, f"Task item at index {i} is not an object", None

        cls = t.get("class")
        if not isinstance(cls, str):
            return False, f"Task at index {i} has missing or non-string 'class'", None

        if cls not in known_classes:
            return False, f"Task at index {i} references unknown class {cls!r}", None

        count = t.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            return False, f"Task at index {i} count must be a positive integer, got {count!r}", None

        per_class_counts[cls] += count
        total_tasks += count

        if per_class_counts[cls] > ir.max_tasks:
            return False, f"Total tasks for class {cls!r} ({per_class_counts[cls]}) exceeds max_tasks ({ir.max_tasks})", None

        if total_tasks > MAX_TOTAL_TASKS:
            return False, f"Total tasks ({total_tasks}) exceeds MAX_TOTAL_TASKS limit ({MAX_TOTAL_TASKS})", None

        work_ms = t.get("work_ms")
        if work_ms is not None:
            if isinstance(work_ms, bool) or not isinstance(work_ms, int) or work_ms <= 0:
                return False, f"Task at index {i} work_ms must be a positive integer or null", None

        arrival_ms = t.get("arrival_ms", 0)
        if isinstance(arrival_ms, bool) or not isinstance(arrival_ms, int) or arrival_ms < 0:
            return False, f"Task at index {i} arrival_ms must be a non-negative integer", None

        burst_ms = t.get("burst_ms")
        if burst_ms is not None:
            if isinstance(burst_ms, bool) or not isinstance(burst_ms, int) or burst_ms <= 0:
                return False, f"Task at index {i} burst_ms must be a positive integer", None

        sleep_ms = t.get("sleep_ms")
        if sleep_ms is not None:
            if isinstance(sleep_ms, bool) or not isinstance(sleep_ms, int) or sleep_ms < 0:
                return False, f"Task at index {i} sleep_ms must be a non-negative integer", None

        parsed_tasks.append(TaskSpec(
            cls=cls,
            count=count,
            work_ms=work_ms,
            arrival_ms=arrival_ms,
            burst_ms=burst_ms,
            sleep_ms=sleep_ms,
        ))

    return True, "OK", Workload(tuple(parsed_tasks))
