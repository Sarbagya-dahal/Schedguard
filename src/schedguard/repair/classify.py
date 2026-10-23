"""Deterministic rule-based violation classifier.

Maps formal counterexamples, IR configuration, and closed-form wait-bound facts
to semantic causes in the CauseTaxonomy without requiring an LLM.
"""
from dataclasses import dataclass, field
from typing import Any
from ..ir import IRPolicy, IRGuarantee
from ..verify.properties import Verdict, analyze
from .taxonomy import CauseTaxonomy


@dataclass
class ClassificationResult:
    cause: CauseTaxonomy
    explanation: str
    suggested_fix: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause.value,
            "explanation": self.explanation,
            "suggested_fix": self.suggested_fix,
            "evidence": self.evidence,
        }


def classify_violation(ir: IRPolicy, verdict: Verdict, facts: dict | None = None) -> ClassificationResult:
    """Deterministically classify the root cause of a violated scheduling guarantee."""
    if verdict.status != "VIOLATED":
        return ClassificationResult(
            cause=CauseTaxonomy.UNKNOWN_CONSERVATIVE,
            explanation="Classification requires a formally VIOLATED guarantee; no cause is inferred.",
            suggested_fix="Do not repair a VERIFIED or UNKNOWN result without new evidence.",
            evidence={"status": verdict.status},
        )
    if facts is None:
        facts = analyze(ir)

    g = verdict.guarantee
    target_cls = ir.cls(g.cls_name)
    target_facts = facts.get(g.cls_name, {})
    tightest = target_facts.get("tightest_wait_ms")
    min_share = target_facts.get("guaranteed_min_share_pct", 0)

    higher_prio = [c for c in ir.classes if c.prio < target_cls.prio]
    same_prio = [c for c in ir.classes if c.prio == target_cls.prio]

    if g.kind == "no_starvation":
        # 1. Unbounded wait check (NO_AGING)
        if tightest is None:
            if target_cls.aging_ms == 0 and higher_prio:
                return ClassificationResult(
                    cause=CauseTaxonomy.NO_AGING,
                    explanation=(
                        f"Class '{target_cls.name}' has no aging (aging=0ms) and can be starved "
                        f"indefinitely by {len(higher_prio)} higher-priority class(es)."
                    ),
                    suggested_fix=f"Add aging to class '{target_cls.name}' (e.g., aging 100 ms;).",
                    evidence={
                        "target_class": target_cls.name,
                        "aging_ms": target_cls.aging_ms,
                        "higher_prio_classes": [c.name for c in higher_prio],
                    },
                )
            return ClassificationResult(
                cause=CauseTaxonomy.UNKNOWN_CONSERVATIVE,
                explanation=f"Wait bound for '{target_cls.name}' is unbounded under current priority configuration.",
                suggested_fix=f"Add aging or reduce priority tier of competing classes.",
                evidence={"tightest_wait_ms": None},
            )

        # 2. Overpromised bound (bound is smaller than minimum quantum / self round-robin)
        min_self_wait = target_cls.quantum_ms
        if g.value < min_self_wait:
            return ClassificationResult(
                cause=CauseTaxonomy.OVERPROMISED_BOUND,
                explanation=(
                    f"Declared bound ({g.value}ms) for '{target_cls.name}' is less than its own "
                    f"quantum ({target_cls.quantum_ms}ms)."
                ),
                suggested_fix=f"Increase declared bound to at least {tightest}ms, or reduce quantum.",
                evidence={"declared_bound": g.value, "quantum_ms": target_cls.quantum_ms, "tightest_wait_ms": tightest},
            )

        # 3. Quantum imbalance (higher-priority classes run large quanta).
        # This has precedence over a large aging interval: the counterexample's
        # distinguishing IR fact is head-of-line blocking by a competitor.
        heavy_quanta = [c for c in higher_prio if c.quantum_ms >= 50 or c.quantum_ms >= 3 * target_cls.quantum_ms]
        if heavy_quanta:
            names = ", ".join(f"{c.name} ({c.quantum_ms}ms)" for c in heavy_quanta)
            return ClassificationResult(
                cause=CauseTaxonomy.QUANTUM_IMBALANCE,
                explanation=f"Excessive quanta in competing class(es) {names} delay '{target_cls.name}'.",
                suggested_fix="Reduce quantum of competing classes to reduce head-of-line blocking.",
                evidence={"heavy_classes": [c.name for c in heavy_quanta], "tightest_wait_ms": tightest},
            )

        # 4. Tier contention is specifically multi-tier interference, not just
        # one slow aging parameter.
        if len(ir.classes) >= 3 and len(higher_prio) >= 2:
            return ClassificationResult(
                cause=CauseTaxonomy.TIER_CONTENTION,
                explanation=f"Multiple higher-priority tiers contend with '{target_cls.name}' before its bound.",
                suggested_fix=f"Tune the competing tiers or their aging while preserving {g.pretty()}.",
                evidence={"higher_prio_classes": [c.name for c in higher_prio], "tightest_wait_ms": tightest},
            )

        # 5. Aging too slow (aging is enabled, but aging threshold alone exceeds promised bound)
        if target_cls.aging_ms > 0 and target_cls.aging_ms >= g.value:
            return ClassificationResult(
                cause=CauseTaxonomy.AGING_TOO_SLOW,
                explanation=(
                    f"Aging interval ({target_cls.aging_ms}ms) for '{target_cls.name}' is greater than or equal "
                    f"to the declared bound ({g.value}ms)."
                ),
                suggested_fix=f"Decrease aging interval for '{target_cls.name}' below {g.value}ms (e.g., {max(1, g.value // 2)}ms).",
                evidence={"aging_ms": target_cls.aging_ms, "declared_bound": g.value, "tightest_wait_ms": tightest},
            )

        # 6. Remaining finite contention.
        if tightest > g.value:
            return ClassificationResult(
                cause=CauseTaxonomy.TIER_CONTENTION,
                explanation=(
                    f"Contention across {len(ir.classes)} classes results in worst-case wait of {tightest}ms, "
                    f"violating declared bound {g.value}ms."
                ),
                suggested_fix=f"Relax bound to {tightest}ms or tune aging and quanta.",
                evidence={"tightest_wait_ms": tightest, "declared_bound": g.value},
            )

    elif g.kind == "min_share":
        if g.value > min_share:
            return ClassificationResult(
                cause=CauseTaxonomy.SHARE_INFEASIBLE,
                explanation=(
                    f"Guaranteed share ({g.value}%) for '{target_cls.name}' exceeds the provable "
                    f"minimum share floor ({min_share}%) under full contention."
                ),
                suggested_fix=f"Reduce min_share guarantee to at most {min_share}%, or raise priority/quantum.",
                evidence={"declared_share": g.value, "provable_min_share": min_share},
            )

    return ClassificationResult(
        cause=CauseTaxonomy.UNKNOWN_CONSERVATIVE,
        explanation=f"Guarantee {g.pretty()} violated; analysis cannot isolate a single dominant cause.",
        suggested_fix="Review policy class definitions and relaxed bounds.",
        evidence={"verdict": verdict.to_dict()},
    )
