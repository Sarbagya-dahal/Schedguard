"""Tests for Random, HillClimb, and LLM attackers."""
import random
import pytest
from unittest.mock import MagicMock
from schedguard.ir import IRClass, IRPolicy
from schedguard.sim.workload import TaskSpec, Workload
from schedguard.adversary.objectives import RegressionObjective


def _policies():
    c0 = IRClass(0, "web", 0, 5, 0, "interactive")
    c1 = IRClass(1, "batch", 1, 20, 100, "batch")
    p0 = IRPolicy("p0", (c0, c1), (), max_tasks=8)
    # p1 inflates batch quantum 5x
    c1_bad = IRClass(1, "batch", 1, 100, 100, "batch")
    p1 = IRPolicy("p1", (c0, c1_bad), (), max_tasks=8)
    return p0, p1


class TestAttackers:
    def test_random_attacker_budget_enforced(self):
        from schedguard.adversary.attackers import RandomAttacker
        p0, p1 = _policies()
        obj = RegressionObjective(target_class="web", metric_name="p99_dispatch_latency", tolerance=5.0)

        attacker = RandomAttacker()
        rng = random.Random(42)
        res = attacker.search(p0, p1, obj, budget=15, rng=rng)

        assert res.simulations_run == 15
        assert res.attacker_name == "random"
        assert res.worst_workload is not None
        assert res.best_regression is not None

    def test_hill_climb_attacker_budget_enforced(self):
        from schedguard.adversary.attackers import HillClimbAttacker
        p0, p1 = _policies()
        obj = RegressionObjective(target_class="web", metric_name="p99_dispatch_latency", tolerance=5.0)

        attacker = HillClimbAttacker()
        rng = random.Random(42)
        res = attacker.search(p0, p1, obj, budget=15, rng=rng)

        assert res.simulations_run == 15
        assert res.attacker_name == "hillclimb"
        assert res.worst_workload is not None

    def test_llm_attacker_with_mock_provider(self):
        from schedguard.adversary.attackers import LLMAttacker
        p0, p1 = _policies()
        obj = RegressionObjective(target_class="web", metric_name="p99_dispatch_latency", tolerance=5.0)

        # Mock provider returning 1 valid and 1 invalid specification
        mock_prov = MagicMock()
        mock_prov.name = "mock"
        mock_prov.complete.return_value = """
        {
          "workloads": [
            {"tasks": [{"class": "web", "count": 2, "burst_ms": 5, "sleep_ms": 10}, {"class": "batch", "count": 4}]},
            {"tasks": [{"class": "invalid_nonexistent_class", "count": 5}]}
          ]
        }
        """

        attacker = LLMAttacker(provider=mock_prov, batch_size=2)
        rng = random.Random(42)
        res = attacker.search(p0, p1, obj, budget=2, rng=rng)

        assert res.attacker_name == "llm"
        assert res.rejection_count >= 1
        assert res.simulations_run <= 2
