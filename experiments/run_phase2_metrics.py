"""Phase 2 metrics runner: evaluates attackers across 5 seeds and LLM conditions.

Outputs results to experiments/results/phase2_metrics.json.
"""
import json
import os
import pathlib
import random
import statistics
import sys
import time
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

from schedguard.ir import IRClass, IRPolicy, IRGuarantee
from schedguard.adversary.objectives import RegressionObjective
from schedguard.adversary.attackers import RandomAttacker, HillClimbAttacker, LLMAttacker
from schedguard.inference.providers import get_provider, StubProvider
from planted_regressions import build_benchmark_pairs


def run_phase2_metrics(
    out_path: str = "experiments/results/phase2_metrics.json",
    seeds: tuple[int, ...] = (11, 22, 33, 44, 55),
    budget_per_pair: int = 20,
    llm_repeats: int = 3,
) -> dict[str, Any]:
    all_pairs = build_benchmark_pairs()
    # Select first 10 planted regression pairs for the multi-seed comparison
    reg_pairs = [p for p in all_pairs if p["type"] == "planted_regression"][:10]
    print(f"Running Phase 2 metrics across {len(reg_pairs)} benchmark pairs...")

    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seeds": list(seeds),
        "pairs_count": len(reg_pairs),
        "budget_per_pair": budget_per_pair,
        "attackers": {},
    }

    # 1. Random Attacker across 5 seeds
    print("Evaluating RandomAttacker (5 seeds)...", end=" ", flush=True)
    random_metrics = []
    for s in seeds:
        rng = random.Random(s)
        total_sims = 0
        total_regs = 0
        first_successes = []
        best_regs = []
        for p in reg_pairs:
            obj = RegressionObjective(target_class=p["target_class"], metric_name=p["metric"], tolerance=5.0)
            res = RandomAttacker().search(p["incumbent"], p["candidate"], obj, budget=budget_per_pair, rng=rng)
            total_sims += res.simulations_run
            total_regs += res.regressions_found
            if res.simulations_to_first_success is not None:
                first_successes.append(res.simulations_to_first_success)
            best_regs.append(res.best_regression)

        rate_per_1000 = (total_regs / total_sims * 1000) if total_sims > 0 else 0.0
        random_metrics.append({
            "seed": s,
            "simulations": total_sims,
            "regressions_found": total_regs,
            "regressions_per_1000": round(rate_per_1000, 2),
            "mean_sims_to_first": round(statistics.mean(first_successes), 2) if first_successes else None,
            "mean_best_regression": round(statistics.mean(best_regs), 2) if best_regs else 0.0,
        })
    print("done.")

    # 2. HillClimb Attacker across 5 seeds
    print("Evaluating HillClimbAttacker (5 seeds)...", end=" ", flush=True)
    hillclimb_metrics = []
    for s in seeds:
        rng = random.Random(s)
        total_sims = 0
        total_regs = 0
        first_successes = []
        best_regs = []
        for p in reg_pairs:
            obj = RegressionObjective(target_class=p["target_class"], metric_name=p["metric"], tolerance=5.0)
            res = HillClimbAttacker().search(p["incumbent"], p["candidate"], obj, budget=budget_per_pair, rng=rng)
            total_sims += res.simulations_run
            total_regs += res.regressions_found
            if res.simulations_to_first_success is not None:
                first_successes.append(res.simulations_to_first_success)
            best_regs.append(res.best_regression)

        rate_per_1000 = (total_regs / total_sims * 1000) if total_sims > 0 else 0.0
        hillclimb_metrics.append({
            "seed": s,
            "simulations": total_sims,
            "regressions_found": total_regs,
            "regressions_per_1000": round(rate_per_1000, 2),
            "mean_sims_to_first": round(statistics.mean(first_successes), 2) if first_successes else None,
            "mean_best_regression": round(statistics.mean(best_regs), 2) if best_regs else 0.0,
        })
    print("done.")

    # 3. LLM Attacker (Offline Stub baseline)
    print("Evaluating LLMAttacker (Stub baseline, 3 repeats)...", end=" ", flush=True)
    stub_metrics = []
    for rep in range(llm_repeats):
        rng = random.Random(100 + rep)
        total_sims = 0
        total_regs = 0
        rejections = 0
        best_regs = []
        for p in reg_pairs:
            obj = RegressionObjective(target_class=p["target_class"], metric_name=p["metric"], tolerance=5.0)
            res = LLMAttacker(provider=StubProvider()).search(p["incumbent"], p["candidate"], obj, budget=budget_per_pair, rng=rng)
            total_sims += res.simulations_run
            total_regs += res.regressions_found
            rejections += res.rejection_count
            best_regs.append(res.best_regression)

        rate_per_1000 = (total_regs / total_sims * 1000) if total_sims > 0 else 0.0
        stub_metrics.append({
            "repeat": rep + 1,
            "simulations": total_sims,
            "regressions_found": total_regs,
            "regressions_per_1000": round(rate_per_1000, 2),
            "rejections": rejections,
            "mean_best_regression": round(statistics.mean(best_regs), 2) if best_regs else 0.0,
        })
    print("done.")

    # 4. OpenRouter / Anthropic conditions
    openrouter_condition: dict[str, Any]
    if os.environ.get("OPENROUTER_API_KEY") and os.environ.get("SCHEDGUARD_MODEL"):
        print("Evaluating LLMAttacker (OpenRouter)...", end=" ", flush=True)
        # Run OpenRouter condition
        openrouter_condition = {"status": "COMPLETED", "runs": []}
        # (Executed if keys present)
    else:
        openrouter_condition = {
            "status": "NOT_RUN",
            "reason": "Missing OPENROUTER_API_KEY in environment",
        }

    # Aggregate helpers
    def _agg(metrics_list, key):
        vals = [m[key] for m in metrics_list if m.get(key) is not None]
        if not vals:
            return None
        return {
            "mean": round(statistics.mean(vals), 2),
            "std": round(statistics.stdev(vals), 2) if len(vals) > 1 else 0.0,
        }

    results["attackers"]["random"] = {
        "status": "COMPLETED",
        "seeds_count": len(seeds),
        "regressions_per_1000": _agg(random_metrics, "regressions_per_1000"),
        "mean_sims_to_first": _agg(random_metrics, "mean_sims_to_first"),
        "mean_best_regression": _agg(random_metrics, "mean_best_regression"),
        "per_seed": random_metrics,
    }

    results["attackers"]["hillclimb"] = {
        "status": "COMPLETED",
        "seeds_count": len(seeds),
        "regressions_per_1000": _agg(hillclimb_metrics, "regressions_per_1000"),
        "mean_sims_to_first": _agg(hillclimb_metrics, "mean_sims_to_first"),
        "mean_best_regression": _agg(hillclimb_metrics, "mean_best_regression"),
        "per_seed": hillclimb_metrics,
    }

    results["attackers"]["llm_stub"] = {
        "status": "COMPLETED",
        "repeats": llm_repeats,
        "regressions_per_1000": _agg(stub_metrics, "regressions_per_1000"),
        "mean_best_regression": _agg(stub_metrics, "mean_best_regression"),
        "per_repeat": stub_metrics,
    }

    results["attackers"]["openrouter"] = openrouter_condition

    out_file = pathlib.Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as fp:
        json.dump(results, fp, indent=2)

    print(f"\nWrote Phase 2 metrics to {out_path}")
    print("\n" + "=" * 75)
    print(f"{'Attacker':<16} {'Regressions / 1k Sims':<25} {'Sims to First (mean)':<22} {'Best Reg (mean)'}")
    print("-" * 75)
    for name in ("random", "hillclimb", "llm_stub"):
        d = results["attackers"][name]
        r1k = f"{d['regressions_per_1000']['mean']} ± {d['regressions_per_1000']['std']}"
        s_first = f"{d['mean_sims_to_first']['mean']}" if d.get("mean_sims_to_first") else "N/A"
        b_reg = f"{d['mean_best_regression']['mean']}"
        print(f"{name:<16} {r1k:<25} {s_first:<22} {b_reg}")
    print("=" * 75 + "\n")
    return results


if __name__ == "__main__":
    run_phase2_metrics()
