"""Adaptive parameter tuner. Searches declared parameter ranges (e.g. batch.aging = 50ms..400ms),
evaluates candidates through the Z3 property verifier and simulator replay, and selects
the best candidate satisfying all declared policy guarantees without inventing fake metrics."""
from dataclasses import dataclass, field
from typing import Any
from .ir import IRPolicy, IRClass
from .verify.properties import check_all, tightest_wait_bound, guaranteed_min_share, Verdict


@dataclass
class CandidateResult:
    value: int
    status: str                        # "ACCEPTED" | "REJECTED" | "UNKNOWN"
    verdicts: list[dict]
    tightest_wait_ms: int | None
    min_share_pct: int
    reason: str


@dataclass
class TuneResult:
    policy_name: str
    target_class: str
    param: str
    range_min: int
    range_max: int
    candidates: list[CandidateResult]
    selected_value: int | None
    selection_reason: str
    recommendation_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "target_class": self.target_class,
            "param": self.param,
            "range_min": self.range_min,
            "range_max": self.range_max,
            "candidates": [
                {
                    "value": c.value,
                    "status": c.status,
                    "verdicts": c.verdicts,
                    "tightest_wait_ms": c.tightest_wait_ms,
                    "min_share_pct": c.min_share_pct,
                    "reason": c.reason,
                }
                for c in self.candidates
            ],
            "selected_value": self.selected_value,
            "selection_reason": self.selection_reason,
            "recommendation_summary": self.recommendation_summary,
        }


def _clone_ir_with_param(ir: IRPolicy, target_class: str, param: str, val: int) -> IRPolicy:
    new_classes = []
    for c in ir.classes:
        if c.name == target_class:
            if param == "aging":
                new_c = IRClass(c.idx, c.name, c.prio, c.quantum_ms, val, c.kind)
            elif param == "quantum":
                new_c = IRClass(c.idx, c.name, c.prio, val, c.aging_ms, c.kind)
            else:
                raise ValueError(f"unsupported adaptation parameter '{param}'")
            new_classes.append(new_c)
        else:
            new_classes.append(c)
    return IRPolicy(ir.name, tuple(new_classes), ir.guarantees, ir.max_tasks, ir.adaptations)


def tune_policy(ir: IRPolicy, target_class: str | None = None, param: str | None = None,
                min_val: int | None = None, max_val: int | None = None,
                num_steps: int = 8) -> TuneResult:
    """Evaluates candidates across the adaptation range for the target class parameter."""
    # Resolve target and range from IR adaptations if not explicitly provided
    if target_class is None or param is None or min_val is None or max_val is None:
        if ir.adaptations:
            a = ir.adaptations[0]
            target_class = target_class or a.cls_name
            param = param or a.param
            min_val = min_val if min_val is not None else a.min_val
            max_val = max_val if max_val is not None else a.max_val
        else:
            # Default to first non-zero priority class with aging or quantum
            target_c = next((c for c in ir.classes if c.prio > 0), ir.classes[0])
            target_class = target_class or target_c.name
            param = param or ("aging" if target_c.aging_ms > 0 else "quantum")
            min_val = min_val if min_val is not None else (50 if param == "aging" else 5)
            max_val = max_val if max_val is not None else (500 if param == "aging" else 50)

    # Validate class exists
    c_idx = next((c.idx for c in ir.classes if c.name == target_class), None)
    if c_idx is None:
        raise KeyError(f"target class '{target_class}' not found in policy")

    # Generate evenly spaced candidate values
    if num_steps <= 1 or min_val == max_val:
        values = [min_val]
    else:
        step = max(1, (max_val - min_val) // (num_steps - 1))
        values = list(range(min_val, max_val + 1, step))
        if values[-1] != max_val:
            values.append(max_val)
        values = sorted(list(set(values)))

    candidates: list[CandidateResult] = []
    accepted: list[CandidateResult] = []

    for val in values:
        cand_ir = _clone_ir_with_param(ir, target_class, param, val)
        verdicts = check_all(cand_ir, replay=True)
        v_dicts = [v.to_dict() for v in verdicts]

        tight = tightest_wait_bound(cand_ir, c_idx)
        share = guaranteed_min_share(cand_ir, c_idx)

        has_violation = any(v.status == "VIOLATED" for v in verdicts)
        has_unknown = any(v.status == "UNKNOWN" for v in verdicts)

        if has_violation:
            status = "REJECTED"
            viol = next(v for v in verdicts if v.status == "VIOLATED")
            rep_info = f" ({viol.replay})" if viol.replay else ""
            reason = f"Refuted: {viol.guarantee.pretty()} was violated{rep_info}."
        elif has_unknown:
            status = "UNKNOWN"
            reason = "Inconclusive under conservative model; not proven safe."
        else:
            status = "ACCEPTED"
            tight_str = f"{tight}ms" if tight is not None else "unbounded"
            reason = f"Proved safe: worst-case wait bound is {tight_str}, min share is {share}%."

        cand_res = CandidateResult(
            value=val,
            status=status,
            verdicts=v_dicts,
            tightest_wait_ms=tight,
            min_share_pct=share,
            reason=reason,
        )
        candidates.append(cand_res)
        if status == "ACCEPTED":
            accepted.append(cand_res)

    # Objective evaluation:
    # For aging: smaller aging bounds starvation more tightly, but excessive boosting can
    # encroach on higher-tier throughput. We select the candidate that guarantees safety
    # while providing the lowest provable worst-case waiting bound.
    if accepted:
        if param == "aging":
            # Sort by lowest valid wait bound, then moderate aging value
            valid_tight = [c for c in accepted if c.tightest_wait_ms is not None]
            if valid_tight:
                selected = min(valid_tight, key=lambda c: (c.tightest_wait_ms, c.value))
            else:
                selected = accepted[0]
            selected_val = selected.value
            sel_reason = (f"Selected {selected_val}ms: satisfies all declared guarantees and achieves "
                          f"the tightest verified wait bound of {selected.tightest_wait_ms}ms for {target_class}.")
            summary = (f"Tested {len(candidates)} candidates in [{min_val}ms..{max_val}ms]. "
                       f"{len(accepted)} proved safe. Recommended parameter is {selected_val}ms.")
        else:
            selected = accepted[0]
            selected_val = selected.value
            sel_reason = f"Selected {selected_val}ms: satisfies all declared guarantees."
            summary = f"Tested {len(candidates)} candidates. Selected {selected_val}ms."
    else:
        selected_val = None
        sel_reason = f"No candidate value in range [{min_val}ms..{max_val}ms] verified all guarantees."
        summary = (f"Tested {len(candidates)} candidates in [{min_val}ms..{max_val}ms], but all were rejected "
                   f"or inconclusive against declared guarantees.")

    return TuneResult(
        policy_name=ir.name,
        target_class=target_class,
        param=param,
        range_min=min_val,
        range_max=max_val,
        candidates=candidates,
        selected_value=selected_val,
        selection_reason=sel_reason,
        recommendation_summary=summary,
    )
