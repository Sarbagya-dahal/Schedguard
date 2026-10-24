"""Bounded, verifier-authoritative policy repair loop (Phase 3)."""
from dataclasses import dataclass, field
import json
import re
from typing import Callable, Any

from ..compiler import compile_source
from ..dsl.lexer import DSLError
from ..verify.properties import check_all, analyze, Verdict
from .classify import classify_violation
from .taxonomy import CauseTaxonomy

MAX_ITERATIONS = 5

@dataclass
class RepairIteration:
    iteration: int
    status: str
    cause: str | None = None
    message: str = ""
    verdicts: list[dict] = field(default_factory=list)

@dataclass
class RepairResult:
    success: bool
    source: str
    iterations: list[RepairIteration]
    max_iterations: int = MAX_ITERATIONS

    def to_dict(self) -> dict[str, Any]:
        return {"success": self.success, "source": self.source,
                "iterations": [i.__dict__ for i in self.iterations],
                "max_iterations": self.max_iterations}

def _preserves(original, revised) -> tuple[bool, str]:
    """Require every original guarantee to remain, equal or stricter."""
    for old in original.guarantees:
        matches = [g for g in revised.guarantees
                   if g.kind == old.kind and g.cls_name == old.cls_name]
        if not matches:
            return False, f"removed guarantee {old.pretty()}"
        if old.kind == "no_starvation" and min(g.value for g in matches) > old.value:
            return False, f"weakened guarantee {old.pretty()}"
        if old.kind == "min_share" and max(g.value for g in matches) < old.value:
            return False, f"weakened guarantee {old.pretty()}"
    return True, ""

def validate_explanation(value: str | dict) -> tuple[dict | None, str | None]:
    """Strictly validate an AI explanation; no repair of malformed output."""
    try:
        obj = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(obj, dict):
        return None, "explanation must be an object"
    required = {"cause", "explanation", "suggested_change"}
    if set(obj) != required:
        return None, "explanation must contain exactly cause, explanation, suggested_change"
    if obj["cause"] not in {c.value for c in CauseTaxonomy}:
        return None, "unknown cause taxonomy value"
    if not all(isinstance(obj[k], str) and obj[k].strip() for k in required):
        return None, "explanation fields must be non-empty strings"
    return obj, None

def _edit_class(source: str, name: str, field: str, value: int | None) -> str:
    """Edit one bounded class declaration without changing its identity."""
    pattern = rf"(class\s+{re.escape(name)}\s*\{{)([^}}]*)(\}})"
    def repl(match):
        body = match.group(2)
        suffix = "" if field == "prio" else " ms"
        field_pattern = rf"\b{field}\s+\d+{re.escape(suffix)}\s*;"
        if field == "aging" and value is None:
            body = re.sub(r"\s*aging\s+\d+\s+ms\s*;", "", body)
        elif re.search(field_pattern, body):
            body = re.sub(field_pattern, f"{field} {value}{suffix};", body)
        elif value is not None:
            body += f" {field} {value}{suffix};"
        return match.group(1) + body + match.group(3)
    return re.sub(pattern, repl, source, count=1, flags=re.S)

def _safe_aging(ir, guarantee) -> int:
    target = ir.cls(guarantee.cls_name)
    higher_load = ir.max_tasks * sum(c.quantum_ms for c in ir.classes if c.prio < target.prio)
    other_boosted = ir.max_tasks * sum(
        c.quantum_ms for c in ir.classes
        if c.name != target.name and c.aging_ms and c.prio >= target.prio
    )
    self_load = max(0, ir.max_tasks - 1) * target.quantum_ms
    return max(1, guarantee.value - higher_load - other_boosted - self_load)

def _set_max_tasks(source: str, value: int) -> str:
    return re.sub(r"(option\s+max_tasks\s*=\s*)\d+", rf"\g<1>{value}", source, count=1)

def _deterministic_edit(source: str, ir, verdict: Verdict) -> str:
    result = classify_violation(ir, verdict)
    cls = re.escape(verdict.guarantee.cls_name)
    cause = result.cause
    if cause in (CauseTaxonomy.NO_AGING, CauseTaxonomy.AGING_TOO_SLOW):
        # For a lower-priority target, the model's worst case is
        #   aging + max_tasks*sum(higher quanta)
        #          + (max_tasks-1)*target quantum
        #          + max_tasks*other boosted/lower-tier quanta.
        # Choose the largest aging value that can still satisfy the declared
        # bound, rather than an arbitrary fraction of it.
        g = verdict.guarantee
        target = ir.cls(g.cls_name)
        candidate_source = source
        # If the quantum load alone exceeds the promise, reduce the target
        # quantum before choosing aging. This is still a policy edit, not a
        # guarantee edit, and is required by the fixed-size model.
        if g.value <= ir.max_tasks * sum(c.quantum_ms for c in ir.classes if c.prio < target.prio) + max(0, ir.max_tasks - 1) * target.quantum_ms:
            candidate_source = _edit_class(candidate_source, target.name, "quantum", 1)
            revised = compile_source(candidate_source)
            if revised.ok:
                ir = revised.ir
        safe_aging = _safe_aging(ir, g)
        pattern = rf"(class\s+{cls}\s*\{{[^}}]*?)(\}})"
        def add(m):
            body = m.group(1)
            if re.search(r"\baging\s+\d+\s+ms", body):
                body = re.sub(r"\baging\s+\d+\s+ms", f"aging {safe_aging} ms", body)
            else:
                body += f" aging {safe_aging} ms;"
            return body + m.group(2)
        return re.sub(pattern, add, candidate_source, count=1, flags=re.S)
    if cause == CauseTaxonomy.QUANTUM_IMBALANCE:
        candidate = source
        for c in ir.classes:
            if c.prio < ir.cls(verdict.guarantee.cls_name).prio and (c.quantum_ms >= 50 or c.quantum_ms >= 3 * ir.cls(verdict.guarantee.cls_name).quantum_ms):
                candidate = _edit_class(candidate, c.name, "quantum", 1)
        revised = compile_source(candidate)
        if revised.ok:
            candidate = _edit_class(candidate, verdict.guarantee.cls_name, "aging", _safe_aging(revised.ir, verdict.guarantee))
        return candidate
    if cause == CauseTaxonomy.OVERPROMISED_BOUND:
        g = verdict.guarantee
        candidate = _set_max_tasks(source, 1)
        candidate = _edit_class(candidate, g.cls_name, "quantum", 1)
        for c in ir.classes:
            if c.name != g.cls_name and c.prio >= ir.cls(g.cls_name).prio:
                candidate = _edit_class(candidate, c.name, "aging", None)
        return candidate
    if cause == CauseTaxonomy.SHARE_INFEASIBLE:
        target = ir.cls(verdict.guarantee.cls_name)
        candidate = source
        # Promote the claimed class and demote the former higher tiers. The
        # requested share remains unchanged and is rechecked formally.
        for c in ir.classes:
            if c.name == target.name:
                candidate = _edit_class(candidate, c.name, "prio", 0)
            elif c.prio <= target.prio:
                candidate = _edit_class(candidate, c.name, "prio", c.prio + 1)
        return candidate
    if cause == CauseTaxonomy.TIER_CONTENTION:
        g = verdict.guarantee
        candidate = source
        for c in ir.classes:
            candidate = _edit_class(candidate, c.name, "quantum", 1)
        revised = compile_source(candidate)
        if revised.ok:
            candidate = _edit_class(candidate, g.cls_name, "aging", _safe_aging(revised.ir, g))
        return candidate
    return source

def repair_policy(source: str, *, feedback: str = "template",
                  repairer: Callable[[str, dict], str] | None = None,
                  max_iterations: int = MAX_ITERATIONS) -> RepairResult:
    """Repair only through parse/safety/formal verification, bounded to five rounds."""
    max_iterations = min(MAX_ITERATIONS, max(0, max_iterations))
    current = source
    try:
        first = compile_source(source)
    except DSLError as exc:
        return RepairResult(False, source, [RepairIteration(0, "REJECTED", message=str(exc))])
    if not first.ok:
        return RepairResult(False, source, [RepairIteration(0, "REJECTED", message="initial policy failed compilation")])
    original = first.ir
    history = []
    seen_candidates = {current}
    for n in range(max_iterations + 1):
        compiled = compile_source(current)
        if not compiled.ok:
            history.append(RepairIteration(n, "REJECTED", message="candidate failed compilation")); return RepairResult(False, current, history)
        verdicts = check_all(compiled.ir)
        vd = [v.to_dict() for v in verdicts]
        if verdicts and all(v.status == "VERIFIED" for v in verdicts):
            history.append(RepairIteration(n, "VERIFIED", verdicts=vd)); return RepairResult(True, current, history)
        violated = next((v for v in verdicts if v.status == "VIOLATED"), None)
        if violated is None:
            history.append(RepairIteration(n, "UNKNOWN", message="no violated guarantee; UNKNOWN is not success", verdicts=vd)); return RepairResult(False, current, history)
        if n == max_iterations:
            history.append(RepairIteration(n, "BUDGET_EXHAUSTED", verdicts=vd)); break
        classification = classify_violation(compiled.ir, violated)
        data = classification.to_dict()
        try:
            candidate = repairer(current, data) if repairer else _deterministic_edit(current, compiled.ir, violated)
        except Exception as exc:
            history.append(RepairIteration(n, "REJECTED", classification.cause.value, str(exc), vd)); continue
        revised = compile_source(candidate)
        if candidate in seen_candidates:
            history.append(RepairIteration(n, "REJECTED", classification.cause.value,
                                           "repeated candidate; no progress", vd))
            break
        if not revised.ok:
            history.append(RepairIteration(n, "REJECTED", classification.cause.value, "candidate failed parse/safety", vd)); continue
        ok, why = _preserves(original, revised.ir)
        if not ok:
            history.append(RepairIteration(n, "REJECTED", classification.cause.value, "guarantee preservation: " + why, vd)); continue
        history.append(RepairIteration(n, "REPAIRED", classification.cause.value, feedback, vd))
        seen_candidates.add(candidate)
        current = candidate
    return RepairResult(False, current, history)
