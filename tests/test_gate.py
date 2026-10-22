"""Tests for the Regression Gate."""
import pytest
from schedguard.compiler import compile_file
from schedguard.ir import IRClass, IRPolicy, IRGuarantee
from schedguard.sim.workload import TaskSpec, Workload
from schedguard.adversary.attackers import RandomAttacker


def _policies():
    c0 = IRClass(0, "web", 0, 5, 0, "interactive")
    c1 = IRClass(1, "batch", 1, 20, 100, "batch")
    g = IRGuarantee("no_starvation", 1, "batch", 500)
    p0 = IRPolicy("p0", (c0, c1), (g,), max_tasks=8)
    return p0


class TestRegressionGate:
    def test_gate_accepts_identical_policy(self):
        from schedguard.gate import evaluate_candidate
        p0 = _policies()
        dec = evaluate_candidate(
            incumbent=p0,
            candidate=p0,
            recorded_traces=[],
            budget=10,
            tolerance=5.0,
            attacker=RandomAttacker(),
        )
        assert dec.decision == "ACCEPT"
        assert len(dec.reasons) == 0

    def test_gate_rejects_static_violation(self):
        from schedguard.gate import evaluate_candidate
        p0 = _policies()
        # Candidate with unprovable/violated guarantee
        c0 = IRClass(0, "web", 0, 5, 0, "interactive")
        c1 = IRClass(1, "batch", 1, 20, 0, "batch") # no aging -> starves
        g = IRGuarantee("no_starvation", 1, "batch", 100)
        p1_bad = IRPolicy("p1_bad", (c0, c1), (g,), max_tasks=8)

        dec = evaluate_candidate(
            incumbent=p0,
            candidate=p1_bad,
            recorded_traces=[],
            budget=5,
            tolerance=5.0,
        )
        assert dec.decision == "REJECT"
        assert any("static" in r.lower() for r in dec.reasons)

    def test_gate_rejects_trace_regression(self):
        from schedguard.gate import evaluate_candidate
        c0 = IRClass(0, "web", 0, 5, 0, "interactive")
        c1 = IRClass(1, "batch", 1, 20, 200, "batch")
        p0 = IRPolicy("p0", (c0, c1), (), max_tasks=8)

        # Candidate inflates batch quantum to 100ms
        c1_bad = IRClass(1, "batch", 1, 100, 200, "batch")
        p1 = IRPolicy("p1", (c0, c1_bad), (), max_tasks=8)

        # Trace that exposes the regression
        trace = Workload((
            TaskSpec("web", count=1, burst_ms=5, sleep_ms=10),
            TaskSpec("batch", count=4),
        ))

        dec = evaluate_candidate(
            incumbent=p0,
            candidate=p1,
            recorded_traces=[trace],
            budget=5,
            tolerance=5.0,
            target_class="web",
            metric_name="p99_dispatch_latency",
        )
        assert dec.decision == "REJECT"
        assert any("recorded trace" in r.lower() or "regression" in r.lower() for r in dec.reasons)
        assert dec.worst_workload is not None
