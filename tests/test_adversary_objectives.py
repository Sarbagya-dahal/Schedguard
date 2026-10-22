"""Tests for regression and scope-violation objectives."""
import pytest
from schedguard.compiler import compile_file
from schedguard.ir import IRClass, IRPolicy, IRGuarantee
from schedguard.sim.workload import TaskSpec, Workload


def _policies():
    c0 = IRClass(0, "web", 0, 5, 0, "interactive")
    c1 = IRClass(1, "batch", 1, 20, 100, "batch")
    p0 = IRPolicy("incumbent", (c0, c1), (), max_tasks=8)
    # Candidate increases batch quantum to 100ms, starving web
    c1_bad = IRClass(1, "batch", 1, 100, 100, "batch")
    p1 = IRPolicy("candidate", (c0, c1_bad), (), max_tasks=8)
    return p0, p1


class TestObjectives:
    def test_regression_objective_latency(self):
        from schedguard.adversary.objectives import RegressionObjective
        p0, p1 = _policies()
        obj = RegressionObjective(target_class="web", metric_name="p99_dispatch_latency", tolerance=10.0)

        wl = Workload((
            TaskSpec("web", count=1, burst_ms=5, sleep_ms=5),
            TaskSpec("batch", count=4),
        ))

        res = obj.evaluate(p0, p1, wl, horizon_ms=1000)
        assert res.target_class == "web"
        assert res.metric_name == "p99_dispatch_latency"
        assert res.tolerance == 10.0
        # Under p1 with 100ms quantum for batch, web latency should be higher
        assert res.candidate_val >= res.incumbent_val
        assert res.regression == pytest.approx(res.candidate_val - res.incumbent_val)

    def test_regression_objective_share(self):
        from schedguard.adversary.objectives import RegressionObjective
        p0, p1 = _policies()
        obj = RegressionObjective(target_class="web", metric_name="share_pct", tolerance=5.0)

        wl = Workload((
            TaskSpec("web", count=2),
            TaskSpec("batch", count=2),
        ))
        res = obj.evaluate(p0, p1, wl, horizon_ms=1000)
        assert res.metric_name == "share_pct"
        assert res.regression == pytest.approx(res.incumbent_val - res.candidate_val)

    def test_scope_violation_objective(self):
        from schedguard.adversary.objectives import ScopeViolationObjective
        # Policy promises no_starvation(batch, 400ms)
        c0 = IRClass(0, "web", 0, 5, 0, "interactive")
        c1 = IRClass(1, "batch", 1, 20, 200, "batch")
        g = IRGuarantee("no_starvation", 1, "batch", 400)
        pol = IRPolicy("aging_fix", (c0, c1), (g,), max_tasks=8)

        obj = ScopeViolationObjective()
        # Normal static workload - guarantee holds
        wl_normal = Workload((
            TaskSpec("web", count=4),
            TaskSpec("batch", count=2),
        ))
        results = obj.evaluate(pol, wl_normal, horizon_ms=2000)
        assert len(results) == 1
        assert results[0].status == "HELD"
