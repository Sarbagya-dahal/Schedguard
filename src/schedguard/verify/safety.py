"""Safety pass: static well-formedness + fixed-size/bounds checks, run BEFORE any
semantic verification. Mirrors the limits a bounded eBPF backend would impose."""
from dataclasses import dataclass
from .. import limits as L
from ..dsl.ast_nodes import PolicyAST


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    line: int = 0

    def __str__(self):
        return f"[{self.code}] line {self.line}: {self.message}" if self.line else f"[{self.code}] {self.message}"


def _rng(v, r):
    return r[0] <= v <= r[1]


def check(ast: PolicyAST) -> list[Diagnostic]:
    d: list[Diagnostic] = []
    if not ast.classes:
        d.append(Diagnostic("E001", "policy declares no classes"))
    if len(ast.classes) > L.MAX_CLASSES:
        d.append(Diagnostic("E002", f"{len(ast.classes)} classes exceeds fixed table size {L.MAX_CLASSES}"))
    if ast.max_tasks is not None and not _rng(ast.max_tasks, L.MAX_TASKS_RANGE):
        d.append(Diagnostic("E003", f"max_tasks {ast.max_tasks} outside {L.MAX_TASKS_RANGE}"))
    seen = set()
    for c in ast.classes:
        if c.name in seen:
            d.append(Diagnostic("E004", f"duplicate class '{c.name}'", c.line))
        seen.add(c.name)
        if c.quantum_ms is None:
            d.append(Diagnostic("E005", f"class '{c.name}' missing required 'quantum'", c.line))
        elif not _rng(c.quantum_ms, L.QUANTUM_MS_RANGE):
            d.append(Diagnostic("E006", f"quantum {c.quantum_ms}ms outside {L.QUANTUM_MS_RANGE}", c.line))
        if c.prio is not None and not _rng(c.prio, L.PRIO_RANGE):
            d.append(Diagnostic("E007", f"prio {c.prio} outside {L.PRIO_RANGE}", c.line))
        if c.aging_ms is not None and not _rng(c.aging_ms, L.AGING_MS_RANGE):
            d.append(Diagnostic("E008", f"aging {c.aging_ms}ms outside {L.AGING_MS_RANGE}", c.line))
    for g in ast.guarantees:
        if g.cls not in seen:
            d.append(Diagnostic("E009", f"guarantee references unknown class '{g.cls}'", g.line))
        rng = L.BOUND_MS_RANGE if g.kind == "no_starvation" else L.SHARE_PCT_RANGE
        if not _rng(g.value, rng):
            d.append(Diagnostic("E010", f"{g.kind} value {g.value} outside {rng}", g.line))
    for a in getattr(ast, "adaptations", []):
        if a.cls not in seen:
            d.append(Diagnostic("E011", f"adaptation references unknown class '{a.cls}'", a.line))
        if a.min_val > a.max_val:
            d.append(Diagnostic("E012", f"adaptation range [{a.min_val}, {a.max_val}] inverted", a.line))
        rng = L.AGING_MS_RANGE if a.param == "aging" else L.QUANTUM_MS_RANGE
        if not _rng(a.min_val, rng) or not _rng(a.max_val, rng):
            d.append(Diagnostic("E013", f"adaptation {a.param} range [{a.min_val}, {a.max_val}] outside {rng}", a.line))
    return d
