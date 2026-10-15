"""Differential test: is the closed-form wait bound (model.py) an UPPER bound on
what the simulator actually produces? Random policies x random static workloads."""
import random, sys, statistics
sys.path.insert(0, "src")
from schedguard.ir import IRPolicy, IRClass
from schedguard.sim import simulate, Workload
from schedguard.verify.model import wait_bound, share_lower_bound_holds, NUM
from schedguard.limits import INF


def random_policy(rng: random.Random) -> IRPolicy:
    k = rng.randint(1, 5)
    cls = tuple(IRClass(i, f"c{i}", rng.randint(0, 3), rng.choice([1, 2, 5, 10, 20, 50]),
                        rng.choice([0, 0, 50, 100, 300]), "") for i in range(k))
    return IRPolicy("rnd", cls, (), 8)


def run(trials: int = 400, seed: int = 7) -> dict:
    rng = random.Random(seed)
    checked = viol = starved_ok = starved_n = share_viol = 0
    ratios = []
    for _ in range(trials):
        ir = random_policy(rng)
        counts = {c.name: rng.randint(0, 8) for c in ir.classes}
        if sum(counts.values()) == 0:
            counts["c0"] = 1
        n = [counts[c.name] for c in ir.classes]
        rnd = sum(n[c.idx] * c.quantum_ms for c in ir.classes)
        horizon = min(300_000, max(20_000, 8 * rnd + 8 * 300))
        res = simulate(ir, Workload.from_counts(counts), horizon)
        for c in ir.classes:
            if counts[c.name] == 0:
                continue
            w = wait_bound(ir, c.idx, n, NUM)
            st = res.per_class[c.name]
            if w >= INF:
                starved_n += 1
                starved_ok += st.max_wait_ms >= horizon - 2 * max(x.quantum_ms for x in ir.classes) or st.cpu_ms == 0
                continue
            checked += 1
            if st.max_wait_ms > w:
                viol += 1
            else:
                ratios.append(st.max_wait_ms / w if w else 1.0)
            # share claim: if bound-derived share floor is P, sim share must be >= P (allow 1% horizon slack)
            floor = 100.0 * n[c.idx] * c.quantum_ms / (w + c.quantum_ms)
            if st.share_pct + 1.0 < floor:
                share_viol += 1
    return {"trials": trials, "finite_class_checks": checked, "bound_violations": viol,
            "share_floor_violations": share_viol, "starved_class_checks": starved_n,
            "starved_confirmed": int(starved_ok),
            "mean_tightness": round(statistics.mean(ratios), 3) if ratios else None,
            "median_tightness": round(statistics.median(ratios), 3) if ratios else None}


if __name__ == "__main__":
    print(run())
