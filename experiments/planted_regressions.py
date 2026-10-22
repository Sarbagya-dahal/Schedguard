"""Planted-regression benchmark suite.

Generates:
- >=20 policy pairs with known planted regressions
- >=10 benign policy pairs without regressions
Establishes ground truth via extensive simulation sweep.
Evaluates and compares:
1. Static check only
2. Gate + RandomAttacker
3. Gate + HillClimbAttacker
4. Gate + LLMAttacker
Outputs results to experiments/results/planted_regressions.json.
"""
import json
import os
import pathlib
import random
import sys
import time
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

from schedguard.ir import IRClass, IRPolicy, IRGuarantee
from schedguard.gate import evaluate_candidate
from schedguard.verify.properties import check_all
from schedguard.adversary.objectives import RegressionObjective
from schedguard.adversary.attackers import RandomAttacker, HillClimbAttacker, LLMAttacker
from schedguard.adversary.space import random_workload


def build_benchmark_pairs() -> list[dict[str, Any]]:
    """Builds at least 20 pairs with planted regressions and 10 clean pairs."""
    pairs = []

    # Base policies
    def p_base_2tier():
        c0 = IRClass(0, "web", 0, 5, 0, "interactive")
        c1 = IRClass(1, "batch", 1, 20, 100, "batch")
        g0 = IRGuarantee("no_starvation", 0, "web", 200)
        g1 = IRGuarantee("no_starvation", 1, "batch", 500)
        return IRPolicy("p_base_2tier", (c0, c1), (g0, g1), max_tasks=8)

    def p_base_3tier():
        c0 = IRClass(0, "rt", 0, 2, 0, "realtime")
        c1 = IRClass(1, "web", 1, 5, 50, "interactive")
        c2 = IRClass(2, "batch", 2, 25, 200, "batch")
        g0 = IRGuarantee("no_starvation", 0, "rt", 100)
        g1 = IRGuarantee("no_starvation", 1, "web", 300)
        g2 = IRGuarantee("no_starvation", 2, "batch", 800)
        return IRPolicy("p_base_3tier", (c0, c1, c2), (g0, g1, g2), max_tasks=8)

    # --- 20 Planted Regression Pairs ---
    # 1-4: Quantum inflation of higher tier (causes latency regressions on web/batch)
    for q in (50, 80, 100, 150):
        inc = p_base_2tier()
        c0_bad = IRClass(0, "web", 0, q, 0, "interactive")
        cand = IRPolicy(f"cand_quantum_{q}", (c0_bad, inc.classes[1]), inc.guarantees, max_tasks=8)
        pairs.append({
            "name": f"quantum_inflation_{q}",
            "type": "planted_regression",
            "desc": f"Web quantum inflated to {q}ms",
            "incumbent": inc,
            "candidate": cand,
            "target_class": "batch",
            "metric": "p99_dispatch_latency",
        })

    # 5-8: Removed or slowed aging
    for aging in (0, 500, 1000, 2000):
        inc = p_base_2tier()
        c1_bad = IRClass(1, "batch", 1, 20, aging, "batch")
        cand = IRPolicy(f"cand_aging_{aging}", (inc.classes[0], c1_bad), inc.guarantees, max_tasks=8)
        pairs.append({
            "name": f"aging_slowed_{aging}",
            "type": "planted_regression",
            "desc": f"Batch aging changed to {aging}ms",
            "incumbent": inc,
            "candidate": cand,
            "target_class": "batch",
            "metric": "p99_dispatch_latency",
        })

    # 9-12: Demoted priority of latency critical tier
    for prio_web in (1, 2, 3, 4):
        inc = p_base_2tier()
        c0_bad = IRClass(0, "web", prio_web, 5, 0, "interactive")
        c1_good = IRClass(1, "batch", 0, 20, 100, "batch")
        cand = IRPolicy(f"cand_prio_{prio_web}", (c0_bad, c1_good), inc.guarantees, max_tasks=8)
        pairs.append({
            "name": f"demoted_prio_web_{prio_web}",
            "type": "planted_regression",
            "desc": f"Web priority demoted to {prio_web}",
            "incumbent": inc,
            "candidate": cand,
            "target_class": "web",
            "metric": "p99_dispatch_latency",
        })

    # 13-16: 3-tier regressions (inflated batch or RT quantum)
    for q_rt in (10, 20, 40, 80):
        inc = p_base_3tier()
        c0_bad = IRClass(0, "rt", 0, q_rt, 0, "realtime")
        cand = IRPolicy(f"cand_3tier_rt_{q_rt}", (c0_bad, inc.classes[1], inc.classes[2]), inc.guarantees, max_tasks=8)
        pairs.append({
            "name": f"3tier_rt_inflation_{q_rt}",
            "type": "planted_regression",
            "desc": f"RT quantum inflated to {q_rt}ms",
            "incumbent": inc,
            "candidate": cand,
            "target_class": "web",
            "metric": "p99_dispatch_latency",
        })

    # 17-20: Guarantee breakages or extreme tier demotions
    for bound in (10, 20, 30, 40):
        inc = p_base_2tier()
        g_unreal = IRGuarantee("no_starvation", 1, "batch", bound)
        cand = IRPolicy(f"cand_tight_fail_{bound}", inc.classes, (inc.guarantees[0], g_unreal), max_tasks=8)
        pairs.append({
            "name": f"impossible_guarantee_{bound}",
            "type": "planted_regression",
            "desc": f"Batch guarantee tightened to impossible {bound}ms",
            "incumbent": inc,
            "candidate": cand,
            "target_class": "batch",
            "metric": "p99_dispatch_latency",
        })

    # --- 10 Benign / Clean Pairs ---
    # 21-24: Identical policies
    for i in range(4):
        inc = p_base_2tier() if i % 2 == 0 else p_base_3tier()
        pairs.append({
            "name": f"identical_pair_{i}",
            "type": "clean",
            "desc": "Candidate is identical to incumbent",
            "incumbent": inc,
            "candidate": inc,
            "target_class": "web",
            "metric": "p99_dispatch_latency",
        })

    # 25-27: Harmless quantum reduction on batch (improves latency without hurting floor)
    for q_batch in (15, 12, 10):
        inc = p_base_2tier()
        c1_safe = IRClass(1, "batch", 1, q_batch, 100, "batch")
        cand = IRPolicy(f"cand_safe_q_{q_batch}", (inc.classes[0], c1_safe), inc.guarantees, max_tasks=8)
        pairs.append({
            "name": f"safe_batch_quantum_{q_batch}",
            "type": "clean",
            "desc": f"Batch quantum safely decreased to {q_batch}ms",
            "incumbent": inc,
            "candidate": cand,
            "target_class": "web",
            "metric": "p99_dispatch_latency",
        })

    # 28-30: Tightened provable guarantee that still verifies
    for b_safe in (450, 400, 350):
        inc = p_base_2tier()
        g1_safe = IRGuarantee("no_starvation", 1, "batch", b_safe)
        cand = IRPolicy(f"cand_safe_tight_{b_safe}", inc.classes, (inc.guarantees[0], g1_safe), max_tasks=8)
        pairs.append({
            "name": f"safe_tight_guarantee_{b_safe}",
            "type": "clean",
            "desc": f"Batch bound tightened safely to {b_safe}ms",
            "incumbent": inc,
            "candidate": cand,
            "target_class": "batch",
            "metric": "p99_dispatch_latency",
        })

    return pairs


def establish_ground_truth(pairs: list[dict], sweep_trials: int = 40, tolerance: float = 5.0) -> list[bool]:
    """Runs a dense workload simulation sweep to verify true regression status."""
    rng = random.Random(999)
    labels = []

    for item in pairs:
        inc = item["incumbent"]
        cand = item["candidate"]
        target_cls = item["target_class"]
        metric = item["metric"]

        # Check static verification first
        static_vs = check_all(cand)
        if any(v.status == "VIOLATED" for v in static_vs):
            labels.append(True)  # True regression (violates static specification)
            continue

        obj = RegressionObjective(target_class=target_cls, metric_name=metric, tolerance=tolerance)
        regressed = False
        for _ in range(sweep_trials):
            wl = random_workload(rng, inc)
            res = obj.evaluate(inc, cand, wl, horizon_ms=5000)
            if res.is_regression:
                regressed = True
                break

        labels.append(regressed)

    return labels


def evaluate_gate_configuration(
    config_name: str,
    pairs: list[dict],
    ground_truth: list[bool],
    budget: int = 20,
    tolerance: float = 5.0,
) -> dict[str, Any]:
    """Evaluates a gate configuration against the planted regression benchmark."""
    tp, fp, tn, fn = 0, 0, 0, 0
    t0 = time.perf_counter()

    for idx, item in enumerate(pairs):
        inc = item["incumbent"]
        cand = item["candidate"]
        gt_is_reg = ground_truth[idx]

        if config_name == "static_only":
            # Only check static guarantees
            vs = check_all(cand)
            rejected = any(v.status == "VIOLATED" for v in vs)
        elif config_name == "random_gate":
            dec = evaluate_candidate(inc, cand, recorded_traces="traces", budget=budget,
                                     tolerance=tolerance, attacker=RandomAttacker(),
                                     target_class=item["target_class"], metric_name=item["metric"])
            rejected = (dec.decision == "REJECT")
        elif config_name == "hillclimb_gate":
            dec = evaluate_candidate(inc, cand, recorded_traces="traces", budget=budget,
                                     tolerance=tolerance, attacker=HillClimbAttacker(),
                                     target_class=item["target_class"], metric_name=item["metric"])
            rejected = (dec.decision == "REJECT")
        elif config_name == "llm_gate":
            dec = evaluate_candidate(inc, cand, recorded_traces="traces", budget=budget,
                                     tolerance=tolerance, attacker=LLMAttacker(),
                                     target_class=item["target_class"], metric_name=item["metric"])
            rejected = (dec.decision == "REJECT")
        else:
            raise ValueError(f"Unknown config: {config_name}")

        if rejected and gt_is_reg:
            tp += 1
        elif rejected and not gt_is_reg:
            fp += 1
        elif not rejected and not gt_is_reg:
            tn += 1
        else:
            fn += 1

    elapsed_ms = (time.perf_counter() - t0) * 1e3
    total_pos = tp + fn
    total_neg = fp + tn

    detection_rate = (tp / total_pos) if total_pos > 0 else 0.0
    false_alarm_rate = (fp / total_neg) if total_neg > 0 else 0.0

    return {
        "config": config_name,
        "elapsed_ms": round(elapsed_ms, 2),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "total_pairs": len(pairs),
        "detection_rate": round(detection_rate, 4),
        "false_alarm_rate": round(false_alarm_rate, 4),
    }


def run_benchmark(out_path: str = "experiments/results/planted_regressions.json"):
    pairs = build_benchmark_pairs()
    print(f"Built {len(pairs)} benchmark pairs (20 planted regressions, 10 clean pairs).")

    print("Establishing ground truth with dense simulation sweep...", end=" ", flush=True)
    gt = establish_ground_truth(pairs)
    reg_count = sum(1 for g in gt if g)
    print(f"done. {reg_count} true regressions confirmed.")

    configs = ["static_only", "random_gate", "hillclimb_gate", "llm_gate"]
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_pairs": len(pairs),
        "ground_truth_regressions": reg_count,
        "ground_truth_clean": len(pairs) - reg_count,
        "configurations": {},
    }

    print("\n" + "=" * 70)
    print(f"{'Gate Configuration':<20} {'Detection Rate':<18} {'False Alarm Rate':<18} {'Time (s)'}")
    print("-" * 70)

    for cfg in configs:
        res = evaluate_gate_configuration(cfg, pairs, gt)
        results["configurations"][cfg] = res
        print(f"{cfg:<20} {res['detection_rate']*100:>5.1f}%             {res['false_alarm_rate']*100:>5.1f}%             {res['elapsed_ms']/1e3:>5.2f}s")

    print("=" * 70 + "\n")

    out_file = pathlib.Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as fp:
        json.dump(results, fp, indent=2)

    print(f"Saved benchmark results to {out_path}")
    return results


if __name__ == "__main__":
    run_benchmark()
