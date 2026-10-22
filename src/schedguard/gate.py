"""Pre-deployment regression gate: evaluates candidate policies against incumbents.

Requires:
1. Static formal verification of candidate guarantees.
2. No performance regression beyond tolerance on recorded traces.
3. No performance regression found by an adversarial search within the simulation budget.
"""
from dataclasses import dataclass, field
import glob
import os
import pathlib
from typing import Any
from .ir import IRPolicy
from .sim.workload import Workload
from .verify.properties import check_all
from .adversary.objectives import RegressionObjective, RegressionResult
from .adversary.attackers import Attacker, RandomAttacker, AttackResult


@dataclass
class GateDecision:
    decision: str                      # "ACCEPT" | "REJECT"
    reasons: list[str] = field(default_factory=list)
    static_verdicts: list[dict] = field(default_factory=list)
    recorded_trace_results: list[dict] = field(default_factory=list)
    attack_result: dict | None = None
    worst_workload: dict | None = None
    limitations: str = (
        "Notice: A failure to find a regression within a finite search budget "
        "is not a mathematical proof of universal dynamic safety."
    )

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reasons": self.reasons,
            "static_verdicts": self.static_verdicts,
            "recorded_trace_results": self.recorded_trace_results,
            "attack_result": self.attack_result,
            "worst_workload": self.worst_workload,
            "limitations": self.limitations,
        }


def _load_traces(traces_arg: Any) -> list[tuple[str, Workload]]:
    """Resolve recorded traces from list of objects, files, or a directory."""
    out = []
    if isinstance(traces_arg, str) and os.path.isdir(traces_arg):
        for f in sorted(glob.glob(os.path.join(traces_arg, "*.json"))):
            name = pathlib.Path(f).stem
            try:
                out.append((name, Workload.from_json(f)))
            except Exception:
                pass
    elif isinstance(traces_arg, list):
        for idx, item in enumerate(traces_arg):
            if isinstance(item, Workload):
                out.append((f"trace_{idx}", item))
            elif isinstance(item, str) and os.path.exists(item):
                out.append((pathlib.Path(item).stem, Workload.from_json(item)))
    return out


def evaluate_candidate(
    incumbent: IRPolicy,
    candidate: IRPolicy,
    recorded_traces: Any = "traces",
    budget: int = 50,
    tolerance: float = 5.0,
    attacker: Attacker | None = None,
    target_class: str | None = None,
    metric_name: str = "p99_dispatch_latency",
    horizon_ms: int = 10_000,
) -> GateDecision:
    """Evaluate whether candidate is safe to deploy against incumbent."""
    reasons: list[str] = []
    worst_wl: Workload | None = None
    max_reg_seen = -float("inf")

    # Pick default target class if not specified (prefer interactive/latency tier or first class)
    if not target_class:
        for c in incumbent.classes:
            if c.kind in ("interactive", "realtime"):
                target_class = c.name
                break
        if not target_class and incumbent.classes:
            target_class = incumbent.classes[0].name

    obj = RegressionObjective(target_class=target_class, metric_name=metric_name, tolerance=tolerance)

    # 1. Static formal verification gate
    verdicts = check_all(candidate)
    static_dicts = [v.to_dict() for v in verdicts]
    for v in verdicts:
        if v.status == "VIOLATED":
            reasons.append(f"Static guarantee violated: {v.guarantee.pretty()} ({v.replay})")

    # 2. Recorded traces gate
    traces = _load_traces(recorded_traces)
    trace_results: list[dict] = []
    known_inc = {c.name for c in incumbent.classes}
    known_cand = {c.name for c in candidate.classes}

    for name, wl in traces:
        # Check if workload classes are compatible with both policies
        wl_classes = {t.cls for t in wl.tasks}
        if not (wl_classes <= known_inc and wl_classes <= known_cand):
            continue

        res = obj.evaluate(incumbent, candidate, wl, horizon_ms=horizon_ms)
        trace_results.append({
            "trace": name,
            "result": res.to_dict(),
        })

        if res.regression > max_reg_seen:
            max_reg_seen = res.regression
            worst_wl = wl

        if res.is_regression:
            reasons.append(
                f"Regression on recorded trace '{name}': {res.metric_name} regressed by "
                f"{res.regression:.1f} (exceeds tolerance {tolerance})"
            )

    # 3. Adversarial search gate
    attacker = attacker or RandomAttacker()
    atk_res = attacker.search(incumbent, candidate, obj, budget=budget, horizon_ms=horizon_ms)

    if atk_res.worst_result and atk_res.worst_result.regression > max_reg_seen:
        max_reg_seen = atk_res.worst_result.regression
        worst_wl = atk_res.worst_workload

    if atk_res.worst_result and atk_res.worst_result.is_regression:
        reasons.append(
            f"Adversarial search ({attacker.__class__.__name__}) found regression of "
            f"{atk_res.best_regression:.1f} exceeding tolerance {tolerance}"
        )

    decision = "REJECT" if reasons else "ACCEPT"

    return GateDecision(
        decision=decision,
        reasons=reasons,
        static_verdicts=static_dicts,
        recorded_trace_results=trace_results,
        attack_result=atk_res.to_dict(),
        worst_workload=worst_wl.to_dict() if worst_wl else None,
    )
