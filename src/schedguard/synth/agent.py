"""Small synthesis facade that composes existing proposal and repair APIs."""
from dataclasses import dataclass
from typing import Any
from ..inference.policy_gen import propose_policy
from ..repair.loop import repair_policy, MAX_ITERATIONS

@dataclass
class SynthesisResult:
    success: bool
    source: str
    proposal: dict[str, Any]
    repair: dict[str, Any] | None

    def to_dict(self):
        return {"success": self.success, "source": self.source,
                "proposal": self.proposal, "repair": self.repair}

def synthesize_policy(intent: str, *, provider_name: str | None = None,
                      repair: bool = True) -> SynthesisResult:
    proposal = propose_policy(intent, provider_name=provider_name)
    source = proposal.source_code
    if not source:
        return SynthesisResult(False, "", proposal.to_dict(), None)
    if not repair:
        from ..compiler import compile_source
        c = compile_source(source)
        return SynthesisResult(bool(c.ok), source, proposal.to_dict(), None)
    result = repair_policy(source)
    proposal_dict = proposal.to_dict()
    if result.iterations:
        final = result.iterations[-1]
        if final.status == "VERIFIED":
            proposal_dict["guarantee_status"] = "VERIFIED"
        elif final.status == "UNKNOWN":
            proposal_dict["guarantee_status"] = "UNKNOWN"
        elif final.verdicts:
            proposal_dict["guarantee_status"] = "VIOLATED"
    return SynthesisResult(result.success, result.source, proposal_dict, result.to_dict())
