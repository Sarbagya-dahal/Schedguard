"""Discrete-event, single-CPU simulator implementing the semantics in
docs/MODEL.md: strict-priority tiers, FIFO round-robin inside the top queue,
non-preemptive quanta, aging that boosts a long-waiting task into the top
queue at the moment it becomes eligible, and dynamic bursts/sleeps (Simulator v2)."""
from collections import deque
from dataclasses import dataclass, field
import heapq
from ..ir import IRPolicy
from .workload import Workload

BIG = 10**18


def _percentile(sorted_vals: list[int | float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    weight = idx - lo
    return float(sorted_vals[lo] * (1.0 - weight) + sorted_vals[hi] * weight)


@dataclass
class ClassStats:
    cpu_ms: int = 0
    max_wait_ms: int = 0        # includes tasks still waiting when the run ended
    dispatches: int = 0
    share_pct: float = 0.0
    p50_dispatch_latency_ms: float = 0.0
    p99_dispatch_latency_ms: float = 0.0
    max_dispatch_latency_ms: int = 0
    dispatch_count: int = 0


@dataclass
class SimResult:
    horizon_ms: int
    configured_horizon_ms: int
    end_ms: int
    idle_ms: int
    decisions: int
    per_class: dict[str, ClassStats] = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)
    trace_truncated: bool = False
    trace_limit: int | None = None
    task_counts: dict[str, int] = field(default_factory=dict)
    overview_buckets: list[dict] = field(default_factory=list)


def simulate(ir: IRPolicy, wl: Workload, horizon_ms: int = 60_000,
             record_trace: bool = False, max_trace_events: int = 1000) -> SimResult:
    cs = ir.classes
    idx = {c.name: c.idx for c in cs}
    # Ready queues entries: (ready_since, tid, remaining_work, remaining_burst, burst_cfg, sleep_cfg)
    queues = [deque() for _ in cs]
    stats = [ClassStats() for _ in cs]
    dispatch_latencies: list[list[int]] = [[] for _ in cs]
    timeline: list[dict] = []
    bucket_count = min(100, max(20, horizon_ms // 100))
    bucket_ms = max(1, (horizon_ms + bucket_count - 1) // bucket_count)
    overview = [
        {"start_ms": i * bucket_ms, "end_ms": min(horizon_ms, (i + 1) * bucket_ms), "cpu_ms": {c.name: 0 for c in cs}}
        for i in range((horizon_ms + bucket_ms - 1) // bucket_ms)
    ]
    pending = []
    tid = 0
    task_counts = {c.name: 0 for c in cs}
    for ts in wl.tasks:
        if ts.cls not in idx:
            raise KeyError(f"workload references unknown class {ts.cls}")
        for _ in range(ts.count):
            rem_work = BIG if ts.work_ms is None else ts.work_ms
            pending.append((ts.arrival_ms, tid, idx[ts.cls], rem_work, ts.burst_ms, ts.sleep_ms))
            tid += 1
        task_counts[ts.cls] += ts.count
    pending.sort(key=lambda x: (x[0], x[1]))

    # Event queue for sleeping tasks: min-heap of (wake_time, tid, class_idx, rem_work, rem_burst, burst_cfg, sleep_cfg)
    sleeping_events: list[tuple[int, int, int, int, int, int | None, int | None]] = []

    pi, t, idle, decisions = 0, 0, 0, 0

    def admit():
        nonlocal pi
        # 1. Admit new arrivals
        while pi < len(pending) and pending[pi][0] <= t:
            arr, k, c, rem, b_cfg, s_cfg = pending[pi]
            q = queues[c]
            pos = len(q)
            while pos > 0 and q[pos - 1][0] > arr:
                pos -= 1
            rem_burst = b_cfg if b_cfg is not None else BIG
            q.insert(pos, (arr, k, rem, rem_burst, b_cfg, s_cfg))
            pi += 1

        # 2. Admit waking tasks from sleep
        while sleeping_events and sleeping_events[0][0] <= t:
            wake_t, k, c, rem, rem_b, b_cfg, s_cfg = heapq.heappop(sleeping_events)
            q = queues[c]
            pos = len(q)
            while pos > 0 and q[pos - 1][0] > wake_t:
                pos -= 1
            q.insert(pos, (wake_t, k, rem, rem_b, b_cfg, s_cfg))

    while t < horizon_ms:
        admit()
        populated = [c for c in range(len(cs)) if queues[c]]
        if not populated:
            nxt_pending = pending[pi][0] if pi < len(pending) else BIG
            nxt_sleep = sleeping_events[0][0] if sleeping_events else BIG
            nxt_event = min(nxt_pending, nxt_sleep)
            if nxt_event >= BIG:
                break
            nxt = min(nxt_event, horizon_ms)
            idle += nxt - t
            t = nxt
            continue

        top = min(cs[c].prio for c in populated)
        best, best_key = None, None
        for c in populated:
            rs = queues[c][0][0]
            if cs[c].prio == top:
                key = (rs, c)
            elif cs[c].aging_ms and rs + cs[c].aging_ms <= t:
                key = (rs + cs[c].aging_ms, c)
            else:
                continue
            if best_key is None or key < best_key:
                best, best_key = c, key

        rs, k, rem, rem_b, b_cfg, s_cfg = queues[best].popleft()
        st = stats[best]
        wait_time = t - rs
        st.max_wait_ms = max(st.max_wait_ms, wait_time)
        st.dispatches += 1
        dispatch_latencies[best].append(wait_time)

        is_boosted = bool(cs[best].prio > top and cs[best].aging_ms and rs + cs[best].aging_ms <= t)
        run = min(cs[best].quantum_ms, rem, rem_b, horizon_ms - t)
        st.cpu_ms += run

        # Aggregate the complete execution, independently of bounded trace capture
        left = t
        right = t + run
        while left < right and left < horizon_ms:
            bucket = overview[min(len(overview) - 1, left // bucket_ms)]
            overlap_end = min(right, bucket["end_ms"])
            bucket["cpu_ms"][cs[best].name] += overlap_end - left
            left = overlap_end

        if record_trace and len(timeline) < max_trace_events:
            q_state = {cs[c].name: len(queues[c]) for c in range(len(cs))}
            timeline.append({
                "start_ms": t,
                "end_ms": t + run,
                "duration_ms": run,
                "class_name": cs[best].name,
                "class_idx": best,
                "task_id": k,
                "prio": cs[best].prio,
                "wait_ms": wait_time,
                "boosted": is_boosted,
                "queue_sizes": q_state,
            })

        t += run
        decisions += 1
        rem_after = rem - run
        rem_b_after = rem_b - run

        if rem_after > 0:
            if rem_b_after <= 0 and s_cfg and s_cfg > 0:
                # Task finished its active burst, goes to sleep
                wake_time = t + s_cfg
                new_burst = b_cfg if b_cfg is not None else BIG
                heapq.heappush(sleeping_events, (wake_time, k, best, rem_after, new_burst, b_cfg, s_cfg))
            else:
                # Task remains ready (quantum expired or burst not exhausted)
                next_rem_b = rem_b_after if rem_b_after > 0 else (b_cfg if b_cfg is not None else BIG)
                queues[best].append((t, k, rem_after, next_rem_b, b_cfg, s_cfg))

    # Account for tasks still waiting in ready queues at simulation end
    for c in range(len(cs)):
        for rs, _, _, _, _, _ in queues[c]:
            stats[c].max_wait_ms = max(stats[c].max_wait_ms, t - rs)

    elapsed = max(t, 1)
    res = SimResult(
        horizon_ms=t, configured_horizon_ms=horizon_ms, end_ms=t,
        idle_ms=idle, decisions=decisions, timeline=timeline,
        trace_truncated=bool(record_trace and decisions > len(timeline)),
        trace_limit=max_trace_events if record_trace else None,
        task_counts=task_counts,
        overview_buckets=overview,
    )
    for c in cs:
        stats[c.idx].share_pct = 100.0 * stats[c.idx].cpu_ms / elapsed
        lats = dispatch_latencies[c.idx]
        if lats:
            s_lats = sorted(lats)
            stats[c.idx].p50_dispatch_latency_ms = round(_percentile(s_lats, 50), 2)
            stats[c.idx].p99_dispatch_latency_ms = round(_percentile(s_lats, 99), 2)
            stats[c.idx].max_dispatch_latency_ms = max(s_lats)
            stats[c.idx].dispatch_count = len(s_lats)
        else:
            stats[c.idx].p50_dispatch_latency_ms = 0.0
            stats[c.idx].p99_dispatch_latency_ms = 0.0
            stats[c.idx].max_dispatch_latency_ms = 0
            stats[c.idx].dispatch_count = 0
        res.per_class[c.name] = stats[c.idx]
    return res
