"""AST -> IR (syllabus Module 3: syntax-directed translation). Assumes the safety
pass accepted the AST; resolves names to indices and normalises defaults."""
from ..dsl.ast_nodes import PolicyAST
from ..limits import DEFAULT_MAX_TASKS
from .ir import IRClass, IRGuarantee, IRPolicy, IRAdaptation


def lower(ast: PolicyAST) -> IRPolicy:
    classes = tuple(IRClass(i, c.name, c.prio if c.prio is not None else 0,
                            c.quantum_ms, c.aging_ms or 0, c.kind or "")
                    for i, c in enumerate(ast.classes))
    index = {c.name: c.idx for c in classes}
    guarantees = tuple(IRGuarantee(g.kind, index[g.cls], g.cls, g.value) for g in ast.guarantees)
    adaptations = tuple(IRAdaptation(index[a.cls], a.cls, a.param, a.min_val, a.max_val)
                        for a in getattr(ast, "adaptations", []) if a.cls in index)
    return IRPolicy(ast.name, classes, guarantees, ast.max_tasks or DEFAULT_MAX_TASKS, adaptations,
                    getattr(ast, "sched_ext_map", None))
