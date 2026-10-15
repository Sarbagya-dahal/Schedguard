"""Small, deterministic natural-language to SchedLang policy proposer."""
import os
import re
from dataclasses import dataclass, field
from typing import Any

CLASS_ALIASES = {
    "web": ("web", "interactive", "frontend", "front-end", "ui", "request", "latency"),
    "batch": ("batch", "background", "worker", "computation", "long-running", "long running", "ml"),
    "rt": ("real-time", "realtime", "audio", "sensor"),
}


@dataclass
class SchedulingIntent:
    classes: list[str] = field(default_factory=list)
    priority_order: list[str] = field(default_factory=list)
    quantum_order: list[str] = field(default_factory=list)
    quantum_values: dict[str, int] = field(default_factory=dict)
    aging_values: dict[str, int] = field(default_factory=dict)
    priority_values: dict[str, int] = field(default_factory=dict)
    wait_requirements: dict[str, int] = field(default_factory=dict)
    min_share_requirements: dict[str, int] = field(default_factory=dict)
    tuning_requested: bool = False
    assumptions: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return bool(self.classes or self.priority_order or self.quantum_order or self.quantum_values or
                    self.aging_values or self.wait_requirements or self.min_share_requirements) and not self.conflicts

    def to_dict(self) -> dict[str, Any]:
        return {"classes": self.classes, "priority_order": self.priority_order,
                "quantum_order": self.quantum_order, "quantum_values": self.quantum_values,
                "aging_values": self.aging_values, "priority_values": self.priority_values,
                "wait_requirements": self.wait_requirements,
                "min_share_requirements": self.min_share_requirements,
                "tuning_requested": self.tuning_requested, "assumptions": self.assumptions,
                "unsupported": self.unsupported, "conflicts": self.conflicts}


@dataclass
class ProposedPolicyResult:
    source_code: str
    provider: str
    mode_label: str
    status: str = "PROPOSAL_GENERATED"
    proposal_status: str = "PROPOSAL_GENERATED"
    is_live_llm: bool = False
    rationale: str = ""
    extracted_classes: list[str] = field(default_factory=list)
    extracted_guarantees: list[str] = field(default_factory=list)
    intent: dict[str, Any] = field(default_factory=dict)
    intent_status: str = "SUPPORTED"
    compilation_status: str = "NOT_RUN"
    consistency_status: str = "NOT_RUN"
    consistency_errors: list[str] = field(default_factory=list)
    guarantee_status: str = "NOT_RUN"
    provider_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"source_code": self.source_code, "provider": self.provider,
                "mode_label": self.mode_label, "status": self.status,
                "proposal_status": self.proposal_status,
                "is_live_llm": self.is_live_llm, "rationale": self.rationale,
                "extracted_classes": self.extracted_classes,
                "extracted_guarantees": self.extracted_guarantees, "intent": self.intent,
                "intent_status": self.intent_status, "compilation_status": self.compilation_status,
                "consistency_status": self.consistency_status,
                "consistency_errors": self.consistency_errors,
                "guarantee_status": self.guarantee_status, "provider_error": self.provider_error}


def _mentioned_classes(text: str) -> list[str]:
    found = []
    for name, aliases in CLASS_ALIASES.items():
        if any(re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", text, re.I) for alias in aliases):
            found.append(name)
    return found


def _class_in_phrase(phrase: str) -> str | None:
    names = _mentioned_classes(phrase)
    return names[0] if len(names) == 1 else None


def _add_order(order: list[str], high: str, low: str, conflicts: list[str], label: str) -> None:
    if high == low:
        conflicts.append(f"A class cannot be both sides of the {label} relationship.")
        return
    if high in order and low in order and order.index(high) > order.index(low):
        conflicts.append(f"Contradictory {label} requirements for {high} and {low}.")
        return
    if high not in order:
        order.append(high)
    if low not in order:
        order.append(low)


def extract_intent(prompt_text: str) -> SchedulingIntent:
    """Extract the small supported scheduling language before synthesis."""
    text = " ".join(prompt_text.strip().split())
    lower = text.lower()
    intent = SchedulingIntent(classes=_mentioned_classes(lower))

    priority_patterns = [
        r"(?:priorit(?:ize|ise)|prefer|favor|favour)\s+(?P<high>.+?)\s+(?:over|above|ahead of)\s+(?P<low>.+?)(?=\s+and\s+(?:priorit|give|make|let)|;|\.|$)",
        r"(?P<high>[^,.]+?)\s+(?:has|have)\s+(?:strict\s+)?higher\s+priority\s+than\s+(?P<low>[^,.]+)",
    ]
    for pattern in priority_patterns:
        for match in re.finditer(pattern, lower):
            high, low = _class_in_phrase(match.group("high")), _class_in_phrase(match.group("low"))
            if high and low:
                _add_order(intent.priority_order, high, low, intent.conflicts, "priority")
    for match in re.finditer(r"(?:priorit(?:ize|ise)|prefer|favor|favour)\s+(?P<high>[^,.]+?)(?:\s+and\b|[,.;]|$)", lower):
        high = _class_in_phrase(match.group("high"))
        others = [name for name in intent.classes if name != high]
        if high and len(others) == 1:
            _add_order(intent.priority_order, high, others[0], intent.conflicts, "priority")

    for match in re.finditer(r"(?P<name>[\w -]+?)\s+(?:at\s+)?priority\s+(?P<value>\d+)", lower):
        name = _class_in_phrase(match.group("name"))
        if name:
            value = int(match.group("value"))
            if value > 7:
                intent.unsupported.append(f"Priority {value} for {name} is outside the DSL range 0..7.")
            if value in intent.priority_values.values() and intent.priority_values.get(name) != value:
                intent.conflicts.append(f"Classes request the same explicit priority {value}.")
            intent.priority_values[name] = value

    quantum_patterns = [
        r"(?:give|make|let)\s+(?P<long>.+?)\s+(?:a\s+)?longer\s+(?:time\s+)?quantum\s+than\s+(?P<short>.+?)(?=\s+and\s+(?:give|make|let)|;|\.|$)",
        r"(?P<long>.+?)\s+(?:time\s+)?quantum\s+(?:is|be)\s+longer\s+than\s+(?P<short>.+?)(?=\s+and\s+(?:give|make|let)|;|\.|$)",
    ]
    for pattern in quantum_patterns:
        for match in re.finditer(pattern, lower):
            long_name, short_name = _class_in_phrase(match.group("long")), _class_in_phrase(match.group("short"))
            if long_name and short_name:
                _add_order(intent.quantum_order, long_name, short_name, intent.conflicts, "quantum")
    for match in re.finditer(r"(?:give|make|let)\s+(?P<long>[^,.]+?)\s+(?:a\s+)?longer\s+(?:time\s+)?quantum(?:\s+than\s+(?P<short>[^,.]+))?", lower):
        long_name = _class_in_phrase(match.group("long"))
        short_name = _class_in_phrase(match.groupdict().get("short") or "")
        if long_name and not short_name:
            others = [name for name in intent.classes if name != long_name]
            if len(others) == 1:
                short_name = others[0]
        if long_name and short_name:
            _add_order(intent.quantum_order, long_name, short_name, intent.conflicts, "quantum")

    for match in re.finditer(r"(?P<phrase>[^.;,]+?)\bquantum\s*(?:of|=|at|is|be)?\s*(?P<value>\d+)\s*(?:ms|milliseconds)", lower):
        name = _class_in_phrase(match.group("phrase"))
        if name:
            intent.quantum_values[name] = int(match.group("value"))
    for match in re.finditer(r"(?P<phrase>[^.;,]+?)\baging\s*(?:of|=|at|is|be)?\s*(?P<value>\d+)\s*(?:ms|milliseconds)", lower):
        name = _class_in_phrase(match.group("phrase"))
        if name:
            intent.aging_values[name] = int(match.group("value"))

    wait_patterns = [
        r"(?P<target>[^.;,]+?)\s+(?:do not|don't|must not|should not)\s+wait\s+(?:longer|more)\s+than\s+(?P<value>\d+)\s*(?:ms|milliseconds)",
        r"(?:maximum|max)\s+(?:waiting[- ]time|wait)\s+(?:requirement|bound)?\s*(?:of|=)?\s*(?P<value>\d+)\s*(?:ms|milliseconds)(?:\s+for\s+(?P<target>[^.;,]+))?",
        r"(?:prevent|avoid|stop)\s+(?P<target>[^.;,]+?)\s+starvation[^\d]*(?P<value>\d+)\s*(?:ms|milliseconds)",
    ]
    for pattern in wait_patterns:
        for match in re.finditer(pattern, lower):
            target = _class_in_phrase(match.groupdict().get("target") or "")
            if not target:
                context = lower[max(0, match.start() - 60):match.end()]
                target = _class_in_phrase(context)
            if target:
                intent.wait_requirements[target] = int(match.group("value"))
            else:
                intent.unsupported.append("A maximum wait requirement needs one explicit target class.")

    for match in re.finditer(r"(?P<target>[^.;,]+?)\s+(?:must have|needs|require)\s+(?P<value>\d+)\s*%\s*(?:minimum\s+)?(?:cpu\s+)?share", lower):
        target = _class_in_phrase(match.group("target"))
        if target:
            intent.min_share_requirements[target] = int(match.group("value"))
    intent.tuning_requested = bool(re.search(r"\b(?:tune|tuning|optimi[sz]e|sweep|range)\b", lower))

    if not intent.classes and not (intent.priority_order or intent.quantum_order):
        if not re.search(r"\b(?:schedul\w*|priority|quantum|aging|starvation|wait|share)\b", lower):
            intent.unsupported.append("No actionable scheduling requirement was detected.")
        else:
            intent.unsupported.append("No supported workload class was identified.")
    if intent.classes and not (intent.priority_order or intent.quantum_order or intent.quantum_values or
                               intent.aging_values or intent.wait_requirements or intent.min_share_requirements):
        intent.unsupported.append("Workload names were found, but no supported scheduling requirement was specified.")
    return intent


def _policy_source(intent: SchedulingIntent, prompt_text: str) -> tuple[str, list[str], list[str], str]:
    classes = list(intent.classes)
    for name in intent.priority_order + intent.quantum_order + list(intent.quantum_values) + list(intent.wait_requirements):
        if name not in classes:
            classes.append(name)
    if not classes:
        return "", [], [], ""
    if len(classes) > 8:
        intent.unsupported.append("The request mentions more classes than the fixed-size DSL supports.")
        return "", classes, [], ""

    if intent.priority_values:
        prios = dict(intent.priority_values)
        next_prio = 0
        for name in classes:
            while next_prio in prios.values():
                next_prio += 1
            prios.setdefault(name, next_prio)
    else:
        ordered = intent.priority_order or classes
        prios = {name: index for index, name in enumerate(ordered)}
        if not intent.priority_order and len(classes) > 1:
            intent.assumptions.append("No priority relationship was requested; listed class order was used.")

    quantum_values = dict(intent.quantum_values)
    if len(intent.quantum_order) >= 2:
        long_name, short_name = intent.quantum_order[:2]
        quantum_values.setdefault(long_name, 20)
        quantum_values.setdefault(short_name, 5)
    for name in classes:
        quantum_values.setdefault(name, 5 if name in ("web", "rt") else 20)
    if not intent.quantum_values and not intent.quantum_order:
        intent.assumptions.append("Quantum values were not specified; class defaults were applied.")

    aging_values = dict(intent.aging_values)
    for name, bound in intent.wait_requirements.items():
        if name not in aging_values:
            aging_values[name] = max(50, min(200, bound // 2))
            intent.assumptions.append(f"Aging {aging_values[name]}ms was added for {name} to support its {bound}ms wait requirement.")

    guarantees = [f"  guarantee no_starvation({name}, {bound} ms);" for name, bound in intent.wait_requirements.items()]
    guarantees += [f"  guarantee min_share({name}, {share} %);" for name, share in intent.min_share_requirements.items()]
    adaptations = []
    if intent.tuning_requested:
        adaptations = [f"  adapt {name}.aging in 50ms..{max(300, aging * 2)}ms;" for name, aging in aging_values.items()]

    kinds = {"web": "interactive", "batch": "batch", "rt": "realtime"}
    lines = ["// AI Proposal generated from structured scheduling intent", f"// Prompt: {prompt_text!r}",
             "// STATUS: UNTRUSTED PROPOSAL (Subject to deterministic compiler/verifier)",
             "policy ai_proposed_policy {", "  option max_tasks = 8;"]
    for name in classes:
        lines += [f"  class {name} {{", f"    prio {prios[name]};", f"    quantum {quantum_values[name]} ms;"]
        if aging_values.get(name, 0):
            lines.append(f"    aging {aging_values[name]} ms;")
        lines += [f"    kind {kinds.get(name, name)};", "  }"]
    lines += adaptations + guarantees + ["}\n"]

    reasons = [f"Recognized classes: {', '.join(classes)}."]
    if intent.priority_order:
        reasons.append(f"Priority order (highest first): {' > '.join(intent.priority_order)}.")
    if intent.quantum_order:
        reasons.append(f"Quantum order (longest first): {' > '.join(intent.quantum_order)}.")
    reasons += [f"Explicit quantum: {name}={value}ms." for name, value in intent.quantum_values.items()]
    reasons += [f"Explicit maximum wait: {name}={value}ms." for name, value in intent.wait_requirements.items()]
    reasons += [f"Assumption: {item}" for item in intent.assumptions]
    reasons += [f"Unsupported: {item}" for item in intent.unsupported]
    return "\n".join(lines), classes, guarantees, " ".join(reasons)


def check_intent_consistency(intent: SchedulingIntent, source_code: str) -> tuple[str, list[str], str]:
    """Compile and compare normalized IR semantics with the extracted intent."""
    if not source_code:
        return "NOT_RUN", ["No candidate policy was generated."], "NOT_RUN"
    from ..compiler import compile_source
    result = compile_source(source_code)
    if not result.ok or result.ir is None:
        return "MISMATCH", [str(d) for d in result.diagnostics], "COMPILATION_FAILED"
    errors = []
    by_name = {c.name: c for c in result.ir.classes}
    for name, value in intent.priority_values.items():
        if name in by_name and by_name[name].prio != value:
            errors.append(f"{name} priority is {by_name[name].prio}, requested {value}.")
    if len(intent.priority_order) >= 2 and all(n in by_name for n in intent.priority_order[:2]):
        a, b = (by_name[n] for n in intent.priority_order[:2])
        if not a.prio < b.prio:
            errors.append(f"{intent.priority_order[0]} is not higher priority than {intent.priority_order[1]}.")
    if len(intent.quantum_order) >= 2 and all(n in by_name for n in intent.quantum_order[:2]):
        a, b = (by_name[n] for n in intent.quantum_order[:2])
        if not a.quantum_ms > b.quantum_ms:
            errors.append(f"{intent.quantum_order[0]} does not have a longer quantum than {intent.quantum_order[1]}.")
    for name, value in intent.quantum_values.items():
        if name in by_name and by_name[name].quantum_ms != value:
            errors.append(f"{name} quantum is {by_name[name].quantum_ms}ms, requested {value}ms.")
    for name, value in intent.aging_values.items():
        if name in by_name and by_name[name].aging_ms != value:
            errors.append(f"{name} aging is {by_name[name].aging_ms}ms, requested {value}ms.")
    guarantees = {(g.kind, g.cls_name, g.value) for g in result.ir.guarantees}
    for name, value in intent.wait_requirements.items():
        if ("no_starvation", name, value) not in guarantees:
            errors.append(f"Missing no_starvation({name}, {value}ms) guarantee.")
    for name, value in intent.min_share_requirements.items():
        if ("min_share", name, value) not in guarantees:
            errors.append(f"Missing min_share({name}, {value}%) guarantee.")
    return ("MATCH" if not errors else "MISMATCH"), errors, "COMPILATION_SUCCESS"


def _unsupported_result(intent: SchedulingIntent, provider: str = "offline_rules") -> ProposedPolicyResult:
    detail = " ".join(intent.conflicts or intent.unsupported)
    return ProposedPolicyResult(
        source_code="", provider=provider, mode_label="No supported scheduling intent",
        status="UNSUPPORTED_INTENT", proposal_status="UNSUPPORTED_INTENT",
        intent_status="CLARIFICATION_REQUIRED",
        rationale=("I couldn't identify a scheduling requirement in that request. Try describing workload priority, "
                   "time quanta, aging, maximum waiting time or another supported scheduling objective. " + detail),
        intent=intent.to_dict(), extracted_classes=intent.classes)


def generate_by_rules(prompt_text: str) -> ProposedPolicyResult:
    intent = extract_intent(prompt_text)
    if not intent.supported:
        return _unsupported_result(intent)
    source, classes, guarantees, rationale = _policy_source(intent, prompt_text)
    consistency, errors, compilation = check_intent_consistency(intent, source)
    return ProposedPolicyResult(source, "offline_rules", "Deterministic Rule Engine (Offline)",
                                status="UNTRUSTED_PROPOSAL",
                                proposal_status="PROPOSAL_GENERATED" if consistency == "MATCH" else "PROPOSAL_REJECTED",
                                rationale=rationale, extracted_classes=classes,
                                extracted_guarantees=guarantees, intent=intent.to_dict(),
                                compilation_status=compilation, consistency_status=consistency,
                                consistency_errors=errors)


def propose_policy(prompt_text: str, provider_name: str = "rules") -> ProposedPolicyResult:
    """Reject unsupported prompts before routing; validate live candidates too."""
    intent = extract_intent(prompt_text)
    if not intent.supported:
        return _unsupported_result(intent)
    if provider_name != "anthropic":
        return generate_by_rules(prompt_text)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        result = generate_by_rules(prompt_text)
        result.mode_label = "Offline Rules (Fallback: missing ANTHROPIC_API_KEY)"
        result.provider = "rules-fallback"
        result.provider_error = "ANTHROPIC_API_KEY is not configured."
        return result
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=os.environ.get("SCHEDGUARD_MODEL", "claude-sonnet-5-5"), max_tokens=600,
            temperature=0.1,
            system=("Write only valid SchedLang DSL. Lower prio means higher priority. Preserve every explicit "
                    "requirement and do not invent guarantees; a deterministic checker will validate the result."),
            messages=[{"role": "user", "content": prompt_text}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        match = re.search(r"```(?:schedlang|text)?\s*([\s\S]*?)\s*```", raw)
        source = match.group(1).strip() if match else raw.strip()
        consistency, errors, compilation = check_intent_consistency(intent, source)
        return ProposedPolicyResult(source, "anthropic", "Anthropic Claude (Live LLM)",
                                    status="UNTRUSTED_PROPOSAL",
                                    proposal_status="PROPOSAL_GENERATED" if consistency == "MATCH" else "PROPOSAL_REJECTED",
                                    is_live_llm=True, rationale="Live LLM candidate checked against extracted intent.",
                                    extracted_classes=intent.classes, intent=intent.to_dict(),
                                    compilation_status=compilation, consistency_status=consistency,
                                    consistency_errors=errors)
    except Exception as exc:
        result = generate_by_rules(prompt_text)
        result.mode_label = f"Offline Rules (Fallback: {type(exc).__name__})"
        result.provider = "rules-fallback"
        result.provider_error = str(exc)
        result.rationale = f"Live LLM unavailable ({exc}). Offline fallback: {result.rationale}"
        return result
