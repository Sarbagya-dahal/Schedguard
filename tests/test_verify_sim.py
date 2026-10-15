import random
import z3
from schedguard.compiler import compile_source
from schedguard.sim import simulate, Workload
from schedguard.verify.model import wait_bound, NUM, SMT
from schedguard.verify.properties import check_guarantee, check_all, tightest_wait_bound, guaranteed_min_share
from schedguard.ir import IRGuarantee
from experiments_path import soundness

def ir_of(src): return compile_source(src).ir

STRICT = "policy p { option max_tasks = 8; class w { prio 0; quantum 5 ms; } class b { prio 1; quantum 20 ms; } }"
AGED = "policy p { option max_tasks = 8; class w { prio 0; quantum 5 ms; } class b { prio 1; quantum 20 ms; aging 200 ms; } }"
SAME = "policy p { option max_tasks = 8; class w { prio 0; quantum 5 ms; } class b { prio 0; quantum 20 ms; } }"


def test_equal_tier_round_robin_shares_follow_quanta():
    r = simulate(ir_of(SAME), Workload.from_counts({"w": 1, "b": 1}), 10_000)
    assert abs(r.per_class["w"].share_pct - 20.0) < 1 and abs(r.per_class["b"].share_pct - 80.0) < 1


def test_strict_priority_starves_lower_tier():
    r = simulate(ir_of(STRICT), Workload.from_counts({"w": 2, "b": 1}), 10_000)
    assert r.per_class["b"].cpu_ms == 0 and r.per_class["b"].max_wait_ms >= 9_000


def test_aging_prevents_starvation():
    r = simulate(ir_of(AGED), Workload.from_counts({"w": 2, "b": 1}), 10_000)
    assert r.per_class["b"].cpu_ms > 0 and r.per_class["b"].max_wait_ms <= 300


def test_unbounded_and_bounded_tightest():
    assert tightest_wait_bound(ir_of(STRICT), 1) is None
    assert tightest_wait_bound(ir_of(AGED), 1) == 380


def test_violation_is_confirmed_by_replay():
    ir = ir_of(STRICT)
    v = check_guarantee(ir, IRGuarantee("no_starvation", 1, "b", 1000))
    assert v.status == "VIOLATED" and v.counterexample["w"] >= 1 and "simulated" in v.replay


def test_verified_when_provable():
    ir = ir_of(AGED)
    assert check_guarantee(ir, IRGuarantee("no_starvation", 1, "b", 380)).status == "VERIFIED"
    assert check_guarantee(ir, IRGuarantee("no_starvation", 1, "b", 379)).status != "VERIFIED"


def test_min_share_search_is_monotone_and_consistent():
    ir = ir_of(SAME)
    p = guaranteed_min_share(ir, 0)
    assert check_guarantee(ir, IRGuarantee("min_share", 0, "w", p), replay=False).status == "VERIFIED"
    assert check_guarantee(ir, IRGuarantee("min_share", 0, "w", p + 1), replay=False).status != "VERIFIED"


def test_numeric_and_smt_backends_agree():
    rng = random.Random(1)
    ir = soundness.random_policy(rng)
    for _ in range(25):
        counts = [rng.randint(0, 8) for _ in ir.classes]
        for c in ir.classes:
            if counts[c.idx] == 0:
                continue
            nv = [z3.IntVal(x) for x in counts]
            sym = z3.simplify(wait_bound(ir, c.idx, nv, SMT)).as_long()
            assert sym == wait_bound(ir, c.idx, counts, NUM)


def test_bound_is_sound_against_simulator():
    out = soundness.run(trials=120, seed=3)
    assert out["bound_violations"] == 0 and out["share_floor_violations"] == 0
    assert out["starved_confirmed"] == out["starved_class_checks"]


def test_example_files_have_expected_verdicts():
    import glob, os
    from schedguard.compiler import compile_file
    exp = {"balanced": ["VERIFIED", "VIOLATED"], "strict_starves": ["VIOLATED"],
           "aging_fix": ["VERIFIED", "VERIFIED"], "three_tier": ["UNKNOWN", "UNKNOWN", "VERIFIED"]}
    for name, want in exp.items():
        got = [v.status for v in check_all(compile_file(f"examples/{name}.sched").ir)]
        assert got == want, name
