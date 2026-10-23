"""Regression coverage for the bounded deterministic repair heuristic."""
from pathlib import Path

from schedguard.repair.loop import repair_policy
from schedguard.compiler import compile_source
from schedguard.verify.properties import check_all


def test_no_aging_repair_selects_verified_aging_ceiling():
    root = Path(__file__).parents[1]
    source = (root / "experiments" / "broken_policies" / "broken_no_aging_01.sched").read_text()

    result = repair_policy(source, feedback="heuristic")

    assert result.success is True
    repaired = compile_source(result.source)
    assert repaired.ok
    verdicts = check_all(repaired.ir)
    assert [v.status for v in verdicts] == ["VERIFIED"]
    assert repaired.ir.cls("batch").aging_ms == 162
    assert all("repeated candidate" not in i.message for i in result.iterations)


def test_repair_loop_stops_on_repeated_candidate():
    source = """policy repeated {
      option max_tasks = 8;
      class web { prio 0; quantum 5 ms; kind interactive; }
      class batch { prio 1; quantum 20 ms; kind batch; }
      guarantee no_starvation(batch, 350 ms);
    }"""

    result = repair_policy(source, repairer=lambda current, facts: current)

    assert result.success is False
    assert any("repeated candidate" in i.message for i in result.iterations)
    assert len(result.iterations) < 6
