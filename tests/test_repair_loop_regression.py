"""Regression coverage for the bounded deterministic repair heuristic."""
from pathlib import Path

from schedguard.repair.loop import repair_policy
from schedguard.compiler import compile_source
from schedguard.verify.properties import check_all, analyze


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


def test_exact_one_ms_request_is_reported_infeasible_without_weakening_guarantee():
    source = """policy ai_proposed_policy {
      option max_tasks = 8;
      class web { prio 0; quantum 5 ms; kind interactive; }
      class batch { prio 1; quantum 20 ms; aging 50 ms; kind batch; }
      guarantee no_starvation(batch, 1 ms);
    }"""
    initial = compile_source(source)
    assert initial.ok
    assert [v.status for v in check_all(initial.ir)] == ["VIOLATED"]

    result = repair_policy(source)

    assert result.success is False
    assert result.status == "INFEASIBLE"
    assert "minimum supported bound" in result.diagnostic
    assert result.source == source
    assert "no_starvation(batch, 1 ms)" in result.source


def test_tight_wait_fixture_reaches_verified_with_real_source_change():
    root = Path(__file__).parents[1]
    source = (root / "examples" / "repairable_tight_wait.sched").read_text()
    initial = compile_source(source)
    assert initial.ok
    assert analyze(initial.ir)["batch"]["tightest_wait_ms"] == 230
    assert [v.status for v in check_all(initial.ir)] == ["VIOLATED"]

    result = repair_policy(source)

    assert result.success is True
    assert result.status == "VERIFIED"
    assert result.source != source
    assert "aging 20 ms;" in result.source
    assert "quantum 5 ms;" in result.source
    assert "quantum 20 ms;" in result.source
    assert "no_starvation(batch, 200 ms);" in result.source
    repaired = compile_source(result.source)
    assert repaired.ok
    assert [v.status for v in check_all(repaired.ir)] == ["VERIFIED"]


def test_existing_repairable_starvation_fixture_still_reaches_verified():
    root = Path(__file__).parents[1]
    source = (root / "src" / "schedguard" / "demo_policies" / "repairable_starvation.sched").read_text()
    result = repair_policy(source)
    assert result.success is True
    assert result.status == "VERIFIED"
    assert "no_starvation(batch, 400 ms);" in result.source
    assert [v.status for v in check_all(compile_source(result.source).ir)] == ["VERIFIED"]


def test_joint_aging_and_quantum_search_finds_feasible_repair():
    source = """policy repair_aging_and_quantum {
      option max_tasks = 8;
      class web { prio 0; quantum 25 ms; kind interactive; }
      class batch { prio 1; quantum 30 ms; aging 50 ms; kind batch; }
      guarantee no_starvation(batch, 400 ms);
    }"""
    initial = compile_source(source)
    assert initial.ok
    assert analyze(initial.ir)["batch"]["tightest_wait_ms"] == 460
    assert [v.status for v in check_all(initial.ir)] == ["VIOLATED"]

    result = repair_policy(source)

    assert result.success is True
    assert result.status == "VERIFIED"
    assert result.source != source
    assert "quantum 25 ms;" not in result.source
    assert "aging 50 ms;" not in result.source
    assert "prio 0;" in result.source and "prio 1;" in result.source
    assert "no_starvation(batch, 400 ms);" in result.source
    repaired = compile_source(result.source)
    assert repaired.ok
    assert repaired.ir.cls("batch").quantum_ms > repaired.ir.cls("web").quantum_ms
    assert [v.status for v in check_all(repaired.ir)] == ["VERIFIED"]
    assert analyze(repaired.ir)["batch"]["tightest_wait_ms"] <= 400
