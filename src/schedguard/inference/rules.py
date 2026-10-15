"""Rule-table BASELINE: fixed templates keyed by the optional `kind` hint.
It cannot handle untagged or novel classes; that coverage gap is what the AI
proposer is evaluated against."""
from ..ir import IRPolicy, IRGuarantee

TEMPLATES = {
    "interactive": [("no_starvation", 500), ("min_share", 10)],
    "realtime":    [("no_starvation", 100)],
    "batch":       [("no_starvation", 5000), ("min_share", 5)],
    "background":  [("no_starvation", 10000)],
}


def propose(ir: IRPolicy) -> list[IRGuarantee]:
    out = []
    for c in ir.classes:
        for kind, val in TEMPLATES.get(c.kind, []):
            out.append(IRGuarantee(kind, c.idx, c.name, val))
    return out
