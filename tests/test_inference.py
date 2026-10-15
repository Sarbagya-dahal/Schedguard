import json
from schedguard.compiler import compile_source
from schedguard.inference import infer
from schedguard.inference.schema import validate
from schedguard.inference.providers import StubProvider
from schedguard.inference import rules

SRC = """policy p { option max_tasks = 8;
  class web { prio 0; quantum 5 ms; kind interactive; }
  class batch { prio 1; quantum 20 ms; aging 200 ms; } }"""
IR = compile_source(SRC).ir


def test_validate_accepts_good_and_rejects_bad():
    raw = json.dumps({"guarantees": [
        {"type": "no_starvation", "class": "batch", "bound_ms": 500},
        {"type": "no_starvation", "class": "ghost", "bound_ms": 500},
        {"type": "min_share", "class": "web", "percent": 500},
        {"type": "min_share", "class": "web", "percent": 12.5},
        {"type": "rm_rf", "class": "web", "percent": 5},
        {"type": "min_share", "class": "web", "percent": True},
        {"type": "no_starvation", "class": "batch", "bound_ms": 500}]})
    ok, bad, _ = validate(raw, IR)
    assert len(ok) == 1 and len(bad) == 6


def test_validate_handles_fences_and_garbage():
    ok, bad, _ = validate("```json\n" + json.dumps({"guarantees": [
        {"type": "min_share", "class": "web", "percent": 3}]}) + "\n```", IR)
    assert len(ok) == 1
    fenced_extra = ("Here is the proposal:\n```json\n"
                    + json.dumps({"guarantees": [{"type": "min_share", "class": "web", "percent": 3}]})
                    + "\n```\nNote: {class web was selected}")
    ok2, bad2, _ = validate(fenced_extra, IR)
    assert len(ok2) == 1
    raw_extra = 'Here is JSON: {"guarantees": [{"type": "min_share", "class": "web", "percent": 3}]} note: {abc}'
    ok3, bad3, _ = validate(raw_extra, IR)
    assert len(ok3) == 1
    assert validate("totally not json", IR)[0] == []
    assert validate('{"nope": 1}', IR)[0] == []


def test_proposal_cap():
    items = [{"type": "min_share", "class": "web", "percent": p} for p in range(1, 15)]
    ok, bad, _ = validate(json.dumps({"guarantees": items}), IR)
    assert len(ok) == 8 and len(bad) == 6


class Fake:
    name = "fake"
    def __init__(self, out): self.out = out
    def complete(self, p): return self.out


class Boom:
    name = "boom"
    def complete(self, p): raise RuntimeError("network down")


def test_ai_cannot_force_acceptance_verifier_decides():
    greedy = json.dumps({"guarantees": [{"type": "no_starvation", "class": "batch", "bound_ms": 1}]})
    rep = infer(IR, {}, Fake(greedy))
    assert rep.source == "fake" and rep.verdicts[0].status != "VERIFIED"


def test_fallback_to_rules_on_failure_and_on_garbage():
    for prov in (Boom(), Fake("garbage")):
        rep = infer(IR, {}, prov)
        assert rep.source == "rules-fallback" and rep.proposed == rules.propose(IR)
    assert "network down" in infer(IR, {}, Boom()).error


def test_stub_pipeline_end_to_end():
    intent = json.load(open("intents/web_batch.json"))
    rep = infer(IR, intent, StubProvider())
    assert rep.source == "stub" and len(rep.verdicts) >= 1
    assert any(v.status == "VERIFIED" for v in rep.verdicts)


def test_rule_baseline_blind_to_untagged_classes():
    ir = compile_source("policy q { class mystery { quantum 5 ms; } }").ir
    assert rules.propose(ir) == []
