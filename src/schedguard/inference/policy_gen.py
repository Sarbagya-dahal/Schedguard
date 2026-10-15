"""Natural language to SchedLang policy proposer.
Translates plain English scheduling requirements into candidate SchedLang policies.
All AI-produced policies are explicitly marked as UNTRUSTED until compiled and verified."""
import os, re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProposedPolicyResult:
    source_code: str
    provider: str
    mode_label: str
    status: str = "UNTRUSTED_PROPOSAL"
    is_live_llm: bool = False
    rationale: str = ""
    extracted_classes: list[str] = field(default_factory=list)
    extracted_guarantees: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_code": self.source_code,
            "provider": self.provider,
            "mode_label": self.mode_label,
            "status": self.status,
            "is_live_llm": self.is_live_llm,
            "rationale": self.rationale,
            "extracted_classes": self.extracted_classes,
            "extracted_guarantees": self.extracted_guarantees,
        }


def _extract_number(text: str, pattern: str, default: int) -> int:
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            pass
    return default


def generate_by_rules(prompt_text: str) -> ProposedPolicyResult:
    """Deterministic offline rule-based translator for scheduling requirements."""
    p_lower = prompt_text.lower()
    classes = []
    guarantees = []
    adaptations = []
    extracted_class_names = []
    reasons = []

    # Detect RT / Realtime class
    if any(k in p_lower for k in ["realtime", "real-time", "rt", "audio", "sensor"]):
        q = _extract_number(p_lower, r"(?:rt|realtime)[^;\.\n]*?(\d+)\s*ms", 2)
        classes.append(f"  class rt {{\n    prio 0;\n    quantum {q} ms;\n    kind realtime;\n  }}")
        extracted_class_names.append("rt")
        reasons.append("Identified real-time workload: assigned priority 0 with short quantum.")

    # Detect Interactive / Web class
    has_web = any(k in p_lower for k in ["web", "interactive", "latency", "request", "ui", "frontend", "desktop"])
    web_prio = 1 if extracted_class_names else 0
    if has_web or not extracted_class_names:
        q = _extract_number(p_lower, r"(?:web|interactive)[^;\.\n]*?quantum[^;\.\n]*?(\d+)\s*ms", 5)
        classes.append(f"  class web {{\n    prio {web_prio};\n    quantum {q} ms;\n    kind interactive;\n  }}")
        extracted_class_names.append("web")
        reasons.append(f"Identified latency-sensitive web/interactive tier: assigned priority {web_prio}.")

    # Detect Batch / Background / ML class
    has_batch = any(k in p_lower for k in ["batch", "worker", "background", "computation", "long running", "ml", "starv"])
    batch_prio = web_prio + 1
    if has_batch or len(extracted_class_names) < 2:
        # Check if quantum specified for batch
        q_batch = _extract_number(p_lower, r"(?:batch|longer)[^;\.\n]*?quantum[^;\.\n]*?(\d+)\s*ms", 20)
        # Search for wait bound requirement
        wait_bound = _extract_number(p_lower, r"(?:waiting-time|starvation|wait)[^;\.\n]*?(\d+)\s*(?:ms|milliseconds)", 400)
        # Search for aging
        aging_val = _extract_number(p_lower, r"aging[^;\.\n]*?(\d+)\s*(?:ms|milliseconds)", 0)
        if aging_val == 0:
            # Set aging conservatively below wait bound to help satisfy guarantee
            aging_val = max(50, min(200, wait_bound // 2))

        classes.append(f"  class batch {{\n    prio {batch_prio};\n    quantum {q_batch} ms;\n    aging {aging_val} ms;\n    kind batch;\n  }}")
        extracted_class_names.append("batch")
        adaptations.append(f"  adapt batch.aging in 50ms..{max(300, aging_val * 2)}ms;")
        guarantees.append(f"  guarantee no_starvation(batch, {wait_bound} ms);")
        reasons.append(f"Identified batch tier: assigned lower priority {batch_prio}, quantum {q_batch}ms, and aging {aging_val}ms.")

    # Check for share guarantee
    share_val = _extract_number(p_lower, r"(\d+)\s*(?:%|percent)\s*(?:cpu|share)", 0)
    if share_val > 0 and "web" in extracted_class_names:
        guarantees.append(f"  guarantee min_share(web, {share_val} %);")
        reasons.append(f"Extracted minimum share guarantee: {share_val}% for web.")

    # Ensure web starvation guarantee if web exists
    if "web" in extracted_class_names and not any("web" in g for g in guarantees):
        guarantees.append("  guarantee no_starvation(web, 200 ms);")

    # Construct policy name
    policy_name = "ai_proposed_policy"
    if "aging" in p_lower or "starv" in p_lower:
        policy_name = "aging_fix_custom"

    code_lines = [f"// AI Proposal generated from natural language intent",
                  f"// Prompt: \"{prompt_text}\"",
                  f"// STATUS: UNTRUSTED PROPOSAL (Subject to deterministic verifier)",
                  f"policy {policy_name} {{",
                  f"  option max_tasks = 8;"]
    code_lines.extend(classes)
    code_lines.extend(adaptations)
    code_lines.extend(guarantees)
    code_lines.append("}\n")

    return ProposedPolicyResult(
        source_code="\n".join(code_lines),
        provider="offline_rules",
        mode_label="Deterministic Rule Engine (Offline)",
        status="UNTRUSTED_PROPOSAL",
        is_live_llm=False,
        rationale=" ".join(reasons),
        extracted_classes=extracted_class_names,
        extracted_guarantees=guarantees,
    )


def propose_policy(prompt_text: str, provider_name: str = "rules") -> ProposedPolicyResult:
    """Routes generation request to live Anthropic LLM (if key provided) or deterministic rules."""
    if provider_name == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                system_prompt = (
                    "You are an expert compiler engineer writing SchedLang CPU scheduling policies.\n"
                    "Output ONLY valid SchedLang DSL source code inside a ```schedlang code block.\n"
                    "Grammar:\n"
                    "policy <name> {\n"
                    "  option max_tasks = <int>;\n"
                    "  class <name> { prio <0..7>; quantum <int> ms; aging <int> ms; kind <ident>; }\n"
                    "  adapt <cls>.<param> in <min>ms..<max>ms;\n"
                    "  guarantee no_starvation(<cls>, <int> ms);\n"
                    "  guarantee min_share(<cls>, <int> %);\n"
                    "}\n"
                    "All proposals are untrusted and will be verified by a deterministic Z3 SMT solver."
                )
                msg = client.messages.create(
                    model=os.environ.get("SCHEDGUARD_MODEL", "claude-sonnet-5-5"),
                    max_tokens=600,
                    temperature=0.1,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt_text}],
                )
                raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
                m = re.search(r"```(?:schedlang|text)?\s*([\s\S]*?)\s*```", raw)
                clean_code = m.group(1).strip() if m else raw.strip()
                return ProposedPolicyResult(
                    source_code=clean_code,
                    provider="anthropic",
                    mode_label="Anthropic Claude (Live LLM)",
                    status="UNTRUSTED_PROPOSAL",
                    is_live_llm=True,
                    rationale="Generated by Claude Sonnet live model according to SchedLang DSL grammar.",
                    extracted_classes=[],
                    extracted_guarantees=[],
                )
            except Exception as e:
                # Honest fallback with notification
                res = generate_by_rules(prompt_text)
                res.mode_label = f"Offline Rules (Fallback: {type(e).__name__})"
                res.rationale = f"Live LLM unavailable ({e}). Fallback to rule engine: {res.rationale}"
                return res

    return generate_by_rules(prompt_text)
