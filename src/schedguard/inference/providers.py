import json, os
from .prompts import Prompt


class StubProvider:
    """Deterministic OFFLINE stand-in used for tests/demos. It is NOT an AI model
    and must never be reported as LLM performance. It deliberately proposes a mix of
    valid and over-ambitious guarantees so the verification gate has work to do."""
    name = "stub"

    def complete(self, p: Prompt) -> str:
        facts, intent = p.context["facts"], p.context["intent"]
        out = []
        for name, f in facts.items():
            desc = json.dumps(intent.get("classes", {}).get(name, {})).lower()
            tight = f["tightest_wait_ms"]
            if any(w in desc for w in ("batch", "background")):
                out.append({"type": "no_starvation", "class": name,
                            "bound_ms": 2000 if tight is None else max(1, int(tight * 1.1))})
            if any(w in desc for w in ("interactive", "latency", "bursty")):
                pct = int(intent["classes"][name].get("cpu_pct", 10))
                out.append({"type": "min_share", "class": name, "percent": max(1, min(100, pct))})
        return json.dumps({"guarantees": out, "rationale": "offline heuristic stub"})


class AnthropicProvider:
    """Real LLM provider. Needs `pip install anthropic` and ANTHROPIC_API_KEY.
    Model comes from SCHEDGUARD_MODEL (default below)."""
    name = "anthropic"

    def __init__(self, model: str | None = None):
        import anthropic  # lazy: optional dependency
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("SCHEDGUARD_MODEL", "claude-sonnet-5-5")

    def complete(self, p: Prompt) -> str:
        msg = self.client.messages.create(model=self.model, max_tokens=1000, temperature=0,
                                          system=p.system,
                                          messages=[{"role": "user", "content": p.user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def get_provider(name: str):
    if name == "stub":
        return StubProvider()
    if name == "anthropic":
        return AnthropicProvider()
    raise ValueError(f"unknown provider {name!r}")
