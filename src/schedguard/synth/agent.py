"""Small synthesis facade that composes existing proposal and repair APIs."""
from dataclasses import dataclass
import re
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


def apply_clarification(prompt: str, answer: str) -> str:
    """Validate and append a user clarification without inventing a value."""
    match = re.fullmatch(r"\s*(\d+)\s*(?:ms|milliseconds?)\s*", answer or "", re.I)
    if not match or int(match.group(1)) <= 0 or int(match.group(1)) > 2147483647:
        raise ValueError("Enter a positive whole-number bound in milliseconds, for example 400 ms.")
    return f"{prompt.strip()}\nClarification: the maximum acceptable waiting time for background tasks is {int(match.group(1))} ms."

def synthesize_policy(intent: str, *, provider_name: str | None = None,
                      repair: bool = True, clarification_answer: str | None = None) -> SynthesisResult:
    if clarification_answer is not None:
        intent = apply_clarification(intent, clarification_answer)
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
