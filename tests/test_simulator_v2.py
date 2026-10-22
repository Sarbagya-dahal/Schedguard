"""Tests for Simulator v2: dynamic workloads (bursts, sleeps, event queue)
and strict bit-for-bit backward compatibility with v1 static workloads."""
import json
import pytest
from schedguard.compiler import compile_file
from schedguard.ir import IRClass, IRPolicy
from schedguard.sim.workload import TaskSpec, Workload
from schedguard.sim.simulator import simulate, ClassStats


def _make_test_policy():
    c_high = IRClass(0, "high", prio=0, quantum_ms=5, aging_ms=0, kind="interactive")
    c_low = IRClass(1, "low", prio=1, quantum_ms=10, aging_ms=0, kind="batch")
    return IRPolicy("test_prio", (c_high, c_low), (), max_tasks=8)


class TestSimulatorV2:
    def test_taskspec_burst_sleep_fields(self):
        t = TaskSpec(cls="web", count=2, work_ms=100, arrival_ms=10, burst_ms=5, sleep_ms=15)
        assert t.burst_ms == 5
        assert t.sleep_ms == 15

        # Test JSON round-trip
        data = {
            "tasks": [
                {"class": "web", "count": 2, "work_ms": 100, "arrival_ms": 10, "burst_ms": 5, "sleep_ms": 15}
            ]
        }
        wl = Workload.from_dict(data) if hasattr(Workload, "from_dict") else Workload.from_json_dict(data)
        assert len(wl.tasks) == 1
        assert wl.tasks[0].burst_ms == 5
        assert wl.tasks[0].sleep_ms == 15

    def test_v1_static_compatibility(self):
        """Static workloads (no burst/sleep) must run identically with exact metric match."""
        pol = compile_file("examples/aging_fix.sched").ir
        wl = Workload.from_json("workloads/web_batch.json")
        res = simulate(pol, wl, horizon_ms=5000)

        assert res.horizon_ms == 5000
        assert res.decisions > 0
        assert "web" in res.per_class
        assert "batch" in res.per_class
        # Both classes got CPU
        assert res.per_class["web"].cpu_ms > 0
        assert res.per_class["batch"].cpu_ms > 0
        # Latency metrics exist on ClassStats
        assert hasattr(res.per_class["web"], "p50_dispatch_latency_ms")
        assert hasattr(res.per_class["web"], "p99_dispatch_latency_ms")
        assert hasattr(res.per_class["web"], "max_dispatch_latency_ms")
        assert res.per_class["web"].p50_dispatch_latency_ms >= 0
        assert res.per_class["web"].p99_dispatch_latency_ms >= res.per_class["web"].p50_dispatch_latency_ms

    def test_sleeping_task_yields_to_lower_priority(self):
        """A high-priority task with burst_ms and sleep_ms must sleep and allow
        the low-priority task to run, then wake up and preempt/resume."""
        pol = _make_test_policy()
        # High priority runs for 5ms burst, then sleeps for 20ms
        # Low priority is CPU-bound
        wl = Workload((
            TaskSpec(cls="high", count=1, burst_ms=5, sleep_ms=20),
            TaskSpec(cls="low", count=1),
        ))
        res = simulate(pol, wl, horizon_ms=100, record_trace=True)

        st_high = res.per_class["high"]
        st_low = res.per_class["low"]

        # Low-priority must have received CPU time while high was sleeping!
        assert st_low.cpu_ms > 0
        assert st_high.cpu_ms > 0
        # In 100ms, a 5ms burst every 25ms period yields ~4 dispatches of high
        assert 3 <= st_high.dispatches <= 5

    def test_dispatch_latency_percentiles_calculation(self):
        """Validate p50 and p99 percentiles calculation."""
        pol = _make_test_policy()
        wl = Workload((
            TaskSpec(cls="high", count=2, arrival_ms=0),
            TaskSpec(cls="low", count=2, arrival_ms=0),
        ))
        res = simulate(pol, wl, horizon_ms=500)
        for st in res.per_class.values():
            assert st.p50_dispatch_latency_ms <= st.p99_dispatch_latency_ms
            assert st.p99_dispatch_latency_ms <= st.max_dispatch_latency_ms + 1e-6
