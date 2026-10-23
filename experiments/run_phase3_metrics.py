"""Reproducible offline Phase 3 repair benchmark.

Conditions A-D are represented explicitly.  A-C use the same bounded repair
engine; C is only executed when a real provider is configured.  Stub output is
never counted as LLM evidence.
"""
from __future__ import annotations
import json, os, pathlib, statistics, sys, time
sys.path.insert(0, "src")
from schedguard.compiler import compile_source
from schedguard.repair.classify import classify_violation
from schedguard.repair.loop import repair_policy, validate_explanation
from schedguard.verify.properties import check_all

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "broken_policies"
OUT = ROOT / "results" / "phase3_metrics.json"

def _samples():
    labels = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))
    for label in labels:
        source = (DATA / label["filename"]).read_text(encoding="utf-8")
        yield label, source

def _classify(source):
    ir = compile_source(source).ir
    verdict = next(v for v in check_all(ir) if v.status == "VIOLATED")
    return classify_violation(ir, verdict)

def _condition(name, samples):
    rows, rejections = [], 0
    for label, source in samples:
        c = _classify(source)
        if c.cause.value != label["ground_truth_cause"]:
            rows.append({"name": label["name"], "success": False, "iterations": None, "cause_correct": False})
            continue
        # A-D share the deterministic verifier and bounded repair.  Feedback
        # differs in reporting; AI is deliberately not substituted offline.
        result = repair_policy(source, feedback=name)
        rejected = sum(1 for i in result.iterations if i.status == "REJECTED")
        rejections += rejected
        rows.append({"name": label["name"], "success": result.success,
                     "iterations": next((i.iteration for i in result.iterations if i.status == "VERIFIED"), None),
                     "cause_correct": True})
    successful = [r for r in rows if r["success"]]
    its = [r["iterations"] for r in successful if r["iterations"] is not None]
    return {"status": "EXECUTED", "samples": len(rows),
            "success_rate": len(successful) / len(rows) if rows else 0,
            "mean_iterations": statistics.mean(its) if its else None,
            "cause_accuracy": sum(r["cause_correct"] for r in rows) / len(rows) if rows else 0,
            "guarantee_preservation_rejections": rejections, "runs": rows}

def main():
    samples = list(_samples())
    real_provider = bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
    result = {"config": {"seed": 0, "samples": len(samples), "max_iterations": 5,
                          "provider": os.environ.get("SCHEDGUARD_PROVIDER", "stub"),
                          "model": os.environ.get("SCHEDGUARD_MODEL")},
              "conditions": {}}
    for name in ("raw", "template", "heuristic"):
        result["conditions"][name] = _condition(name, samples)
    result["conditions"]["ai_explained"] = ({"status": "NOT_RUN", "reason": "No configured real LLM provider"}
                                              if not real_provider else
                                              {"status": "NOT_RUN", "reason": "Live AI benchmark requires explicit provider execution"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "samples": len(samples),
                      "ai_explained": result["conditions"]["ai_explained"]["status"]}, indent=2))

if __name__ == "__main__": main()
