"""Feature 1 pipeline: AI proposes guarantees -> schema gate -> formal verification.
The AI never decides acceptance; the verifier does. On provider failure or when no
valid proposal survives, the rule-table baseline is used (flagged in the report)."""
from dataclasses import dataclass, field
from ..ir import IRPolicy, IRGuarantee
from ..verify.properties import analyze, check_guarantee, Verdict
from . import rules
from .prompts import build_prompt
from .schema import validate


@dataclass
class InferenceReport:
    source: str                              # provider name, or "rules-fallback"
    facts: dict
    proposed: list[IRGuarantee] = field(default_factory=list)
    rejected: list = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    rationale: str = ""
    error: str = ""
    raw_output: str = ""

    @property
    def verified(self): return [v for v in self.verdicts if v.status == "VERIFIED"]
    @property
    def violated(self): return [v for v in self.verdicts if v.status == "VIOLATED"]

    def to_dict(self):
        return {"source": self.source, "error": self.error, "rationale": self.rationale,
                "proposed": [g.pretty() for g in self.proposed],
                "rejected": [{"item": str(i), "reason": r} for i, r in self.rejected],
                "verdicts": [v.to_dict() for v in self.verdicts]}


def infer(ir: IRPolicy, intent: dict, provider, fallback: bool = True) -> InferenceReport:
    facts = analyze(ir)
    rep = InferenceReport(provider.name, facts)
    try:
        raw = provider.complete(build_prompt(ir, facts, intent))
        rep.raw_output = raw
        rep.proposed, rep.rejected, rep.rationale = validate(raw, ir)
    except Exception as e:                    # network/API/parse failure
        rep.error = f"{type(e).__name__}: {e}"
    if not rep.proposed and fallback:
        rep.source = "rules-fallback"
        rep.proposed = rules.propose(ir)
    rep.verdicts = [check_guarantee(ir, g) for g in rep.proposed]
    return rep
