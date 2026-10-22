"""Tests for bounded workload space, mutation, and strict schema validation."""
import random
import pytest
from schedguard.compiler import compile_file
from schedguard.ir import IRClass, IRPolicy
from schedguard.sim.workload import TaskSpec, Workload


def _test_ir():
    c0 = IRClass(0, "web", 0, 5, 0, "interactive")
    c1 = IRClass(1, "batch", 1, 20, 200, "batch")
    return IRPolicy("test_policy", (c0, c1), (), max_tasks=8)


class TestAdversarySpace:
    def test_random_workload_within_bounds(self):
        from schedguard.adversary.space import random_workload, MAX_TOTAL_TASKS
        ir = _test_ir()
        rng = random.Random(42)
        for _ in range(50):
            wl = random_workload(rng, ir)
            assert isinstance(wl, Workload)
            assert len(wl.tasks) > 0
            counts = {c.name: 0 for c in ir.classes}
            total = 0
            for t in wl.tasks:
                assert t.cls in counts
                counts[t.cls] += t.count
                total += t.count
            assert total <= MAX_TOTAL_TASKS
            for name, cnt in counts.items():
                assert cnt <= ir.max_tasks

    def test_mutate_workload_preserves_validity(self):
        from schedguard.adversary.space import random_workload, mutate_workload, validate_spec
        ir = _test_ir()
        rng = random.Random(123)
        wl = random_workload(rng, ir)
        for _ in range(30):
            wl = mutate_workload(wl, rng, ir)
            ok, msg, validated_wl = validate_spec(wl.to_dict(), ir)
            assert ok, f"Mutation produced invalid workload: {msg}"
            assert validated_wl is not None

    def test_validate_spec_rejections(self):
        from schedguard.adversary.space import validate_spec
        ir = _test_ir()

        # 1. Missing tasks
        ok, msg, _ = validate_spec({"not_tasks": []}, ir)
        assert not ok
        assert "tasks" in msg.lower()

        # 2. Unknown class
        bad_class = {"tasks": [{"class": "unknown_class", "count": 2}]}
        ok, msg, _ = validate_spec(bad_class, ir)
        assert not ok
        assert "unknown" in msg.lower()

        # 3. Count exceeds max_tasks
        too_many = {"tasks": [{"class": "web", "count": 999}]}
        ok, msg, _ = validate_spec(too_many, ir)
        assert not ok
        assert "exceeds" in msg.lower() or "bound" in msg.lower()

        # 4. Negative count or arrival
        negative = {"tasks": [{"class": "web", "count": -1}]}
        ok, msg, _ = validate_spec(negative, ir)
        assert not ok

        # 5. Non-integer burst
        bad_burst = {"tasks": [{"class": "web", "count": 2, "burst_ms": "fast"}]}
        ok, msg, _ = validate_spec(bad_burst, ir)
        assert not ok
