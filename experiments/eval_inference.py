"""Phase 1b evaluation harness: comparing rule baseline vs AI proposer on >=12 intents.
Metrics: classes covered, schema-reject rate, verified/violated/unknown rates,
distance to provable frontier (proposed bound / tightest bound).
Outputs results to experiments/results/eval_inference.json.

Usage:
  PYTHONPATH=src .venv/Scripts/python.exe experiments/eval_inference.py
"""
import glob
import json
import os
import pathlib
import statistics
import sys
import time
from typing import Any

# Ensure imports work when run directly
sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

from schedguard.compiler import compile_file
from schedguard.inference import infer
from schedguard.inference import rules
from schedguard.inference.providers import get_provider, StubProvider
from schedguard.inference.pipeline import InferenceReport
from schedguard.verify.properties import analyze, check_guarantee


def select_policy_for_intent(intent: dict) -> str:
    """Select the policy that matches classes mentioned in the intent."""
    classes = intent.get("classes", {})
    if "rt" in classes or "ml" in classes:
        return "examples/three_tier.sched"
    return "examples/aging_fix.sched"


def compute_metrics(reports: list[InferenceReport]) -> dict[str, Any]:
    """Compute formal evaluation metrics across a list of inference reports."""
    total_proposed = sum(len(r.proposed) for r in reports)
    total_rejected = sum(len(r.rejected) for r in reports)
    total_attempts = total_proposed + total_rejected

    schema_rejection_rate = (total_rejected / total_attempts) if total_attempts > 0 else 0.0

    classes_covered = sorted(list({g.cls_name for r in reports for g in r.proposed}))
    classes_covered_count = len(classes_covered)

    verdicts = [v for r in reports for v in r.verdicts]
    total_verdicts = len(verdicts)

    verified_count = sum(1 for v in verdicts if v.status == "VERIFIED")
    violated_count = sum(1 for v in verdicts if v.status == "VIOLATED")
    unknown_count = sum(1 for v in verdicts if v.status == "UNKNOWN")

    verified_rate = (verified_count / total_verdicts) if total_verdicts > 0 else 0.0
    violated_rate = (violated_count / total_verdicts) if total_verdicts > 0 else 0.0
    unknown_rate = (unknown_count / total_verdicts) if total_verdicts > 0 else 0.0

    frontier_ratios: list[float] = []
    unbounded_count = 0

    for r in reports:
        facts = r.facts or {}
        for g in r.proposed:
            if g.kind == "no_starvation":
                tight = facts.get(g.cls_name, {}).get("tightest_wait_ms")
                if tight is None:
                    unbounded_count += 1
                elif tight > 0:
                    frontier_ratios.append(g.value / tight)

    frontier_mean = statistics.mean(frontier_ratios) if frontier_ratios else None
    frontier_std = statistics.stdev(frontier_ratios) if len(frontier_ratios) > 1 else 0.0

    return {
        "classes_covered": classes_covered,
        "classes_covered_count": classes_covered_count,
        "total_proposed": total_proposed,
        "total_rejected": total_rejected,
        "total_attempts": total_attempts,
        "schema_rejection_rate": round(schema_rejection_rate, 4),
        "total_verdicts": total_verdicts,
        "verified_count": verified_count,
        "violated_count": violated_count,
        "unknown_count": unknown_count,
        "verified_rate": round(verified_rate, 4),
        "violated_rate": round(violated_rate, 4),
        "unknown_rate": round(unknown_rate, 4),
        "frontier_distance_mean": round(frontier_mean, 4) if frontier_mean is not None else None,
        "frontier_distance_std": round(frontier_std, 4) if frontier_mean is not None else None,
        "unbounded_proposals_count": unbounded_count,
    }


def evaluate_rules_baseline(intents: list[tuple[str, dict]]) -> dict[str, Any]:
    """Run the deterministic rule-table baseline."""
    reports = []
    per_intent = []
    t0 = time.perf_counter()

    for name, intent in intents:
        pol_path = select_policy_for_intent(intent)
        ir = compile_file(pol_path).ir
        facts = analyze(ir)
        proposed = rules.propose(ir)
        verdicts = [check_guarantee(ir, g) for g in proposed]
        rep = InferenceReport(
            source="rules",
            facts=facts,
            proposed=proposed,
            rejected=[],
            verdicts=verdicts,
        )
        reports.append(rep)
        per_intent.append({
            "intent": name,
            "policy": pol_path,
            "proposed_count": len(proposed),
            "verdicts": [v.status for v in verdicts],
        })

    elapsed_ms = (time.perf_counter() - t0) * 1e3
    metrics = compute_metrics(reports)
    return {
        "status": "COMPLETED",
        "provider": "rules",
        "elapsed_ms": round(elapsed_ms, 2),
        "metrics": metrics,
        "per_intent": per_intent,
    }


def evaluate_provider(
    provider_name: str,
    intents: list[tuple[str, dict]],
    repeats: int = 1,
) -> dict[str, Any]:
    """Evaluate a provider across all intents, repeating `repeats` times for LLM conditions."""
    if provider_name == "rules":
        return evaluate_rules_baseline(intents)

    # Check required API keys before execution
    if provider_name == "openrouter":
        if not os.environ.get("OPENROUTER_API_KEY"):
            return {
                "status": "NOT_RUN",
                "provider": "openrouter",
                "reason": "Missing OPENROUTER_API_KEY in environment",
                "metrics": {},
            }
        if not os.environ.get("SCHEDGUARD_MODEL"):
            return {
                "status": "NOT_RUN",
                "provider": "openrouter",
                "reason": "Missing SCHEDGUARD_MODEL in environment",
                "metrics": {},
            }
    elif provider_name == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return {
                "status": "NOT_RUN",
                "provider": "anthropic",
                "reason": "Missing ANTHROPIC_API_KEY in environment",
                "metrics": {},
            }

    try:
        prov = get_provider(provider_name)
    except Exception as e:
        return {
            "status": "NOT_RUN",
            "provider": provider_name,
            "reason": f"Provider initialization failed: {e}",
            "metrics": {},
        }

    repeat_metrics = []
    all_runs = []
    t0 = time.perf_counter()

    for r_idx in range(repeats):
        rep_reports = []
        rep_per_intent = []
        for name, intent in intents:
            pol_path = select_policy_for_intent(intent)
            ir = compile_file(pol_path).ir
            rep = infer(ir, intent, prov, fallback=False)
            rep_reports.append(rep)
            rep_per_intent.append({
                "intent": name,
                "policy": pol_path,
                "proposed_count": len(rep.proposed),
                "rejected_count": len(rep.rejected),
                "verdicts": [v.status for v in rep.verdicts],
                "error": rep.error,
            })
        m = compute_metrics(rep_reports)
        repeat_metrics.append(m)
        all_runs.append(rep_per_intent)

    elapsed_ms = (time.perf_counter() - t0) * 1e3

    # Aggregate across repeats
    def _agg(key):
        vals = [rm[key] for rm in repeat_metrics if rm.get(key) is not None]
        if not vals:
            return None
        return {
            "mean": round(statistics.mean(vals), 4),
            "std": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
        }

    agg_metrics = {
        "classes_covered_count": _agg("classes_covered_count"),
        "total_proposed": _agg("total_proposed"),
        "total_rejected": _agg("total_rejected"),
        "schema_rejection_rate": _agg("schema_rejection_rate"),
        "verified_rate": _agg("verified_rate"),
        "violated_rate": _agg("violated_rate"),
        "unknown_rate": _agg("unknown_rate"),
        "frontier_distance_mean": _agg("frontier_distance_mean"),
    }

    return {
        "status": "COMPLETED",
        "provider": provider_name,
        "repeats": repeats,
        "elapsed_ms": round(elapsed_ms, 2),
        "metrics": repeat_metrics[0] if repeats == 1 else agg_metrics,
        "per_repeat_metrics": repeat_metrics,
        "runs": all_runs,
    }


def run_evaluation(
    intents_dir: str = "intents",
    out_path: str = "experiments/results/eval_inference.json",
    repeats_per_llm: int = 3,
) -> dict[str, Any]:
    """Main evaluation runner for Phase 1b."""
    intent_files = sorted(glob.glob(os.path.join(intents_dir, "*.json")))
    if not intent_files:
        raise RuntimeError(f"No intent JSON files found in {intents_dir}")

    intents: list[tuple[str, dict]] = []
    for f in intent_files:
        name = pathlib.Path(f).stem
        with open(f, "r", encoding="utf-8") as fp:
            intents.append((name, json.load(fp)))

    print(f"Loaded {len(intents)} intents from {intents_dir}/")

    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "intents_count": len(intents),
        "intents": [name for name, _ in intents],
        "providers": {},
    }

    providers_to_test = [
        ("rules", 1),
        ("stub", 1),
        ("openrouter", repeats_per_llm),
        ("anthropic", repeats_per_llm),
    ]

    for p_name, reps in providers_to_test:
        print(f"Evaluating provider: {p_name} (repeats={reps})...", end=" ", flush=True)
        res = evaluate_provider(p_name, intents, repeats=reps)
        results["providers"][p_name] = res
        print(f"{res['status']}")

    out_file = pathlib.Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as fp:
        json.dump(results, fp, indent=2)

    print(f"\nWrote evaluation report to {out_path}")
    _print_summary_table(results)
    return results


def _print_summary_table(results: dict[str, Any]):
    print("\n" + "=" * 80)
    print(f"{'Provider':<14} {'Status':<11} {'Classes':<9} {'Rej Rate':<10} {'Verified':<10} {'Violated':<10} {'Frontier'}")
    print("-" * 80)
    for p_name, data in results["providers"].items():
        st = data.get("status", "UNKNOWN")
        if st != "COMPLETED":
            print(f"{p_name:<14} {st:<11} {'-':<9} {'-':<10} {'-':<10} {'-':<10} {data.get('reason', '')}")
            continue
        m = data.get("metrics", {})
        # handle repeats agg vs single dict
        classes = m.get("classes_covered_count")
        if isinstance(classes, dict):
            classes_str = f"{classes['mean']:.1f}"
            rej_str = f"{m['schema_rejection_rate']['mean']*100:.1f}%"
            ver_str = f"{m['verified_rate']['mean']*100:.1f}%"
            viol_str = f"{m['violated_rate']['mean']*100:.1f}%"
            fd = m.get("frontier_distance_mean")
            fd_str = f"{fd['mean']:.2f}x" if fd and fd.get("mean") is not None else "N/A"
        else:
            classes_str = str(classes)
            rej_str = f"{m.get('schema_rejection_rate', 0)*100:.1f}%"
            ver_str = f"{m.get('verified_rate', 0)*100:.1f}%"
            viol_str = f"{m.get('violated_rate', 0)*100:.1f}%"
            fd = m.get("frontier_distance_mean")
            fd_str = f"{fd:.2f}x" if fd is not None else "N/A"

        print(f"{p_name:<14} {st:<11} {classes_str:<9} {rej_str:<10} {ver_str:<10} {viol_str:<10} {fd_str}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_evaluation()
