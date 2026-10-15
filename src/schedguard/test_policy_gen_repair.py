from schedguard.compiler import compile_source
from schedguard.inference.policy_gen import extract_intent, generate_by_rules, propose_policy


def _compiled(prompt):
    result = generate_by_rules(prompt)
    assert result.status == "UNTRUSTED_PROPOSAL"
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.consistency_status == "MATCH"
    compiled = compile_source(result.source_code)
    assert compiled.ok and compiled.ir is not None
    return result, compiled.ir


def test_web_first_and_batch_longer_quantum_have_semantic_order():
    result, ir = _compiled("Prioritize web tasks and give batch tasks a longer quantum.")
    assert ir.cls("web").prio < ir.cls("batch").prio
    assert ir.cls("batch").quantum_ms > ir.cls("web").quantum_ms
    assert "Contradictory" not in result.rationale


def test_batch_first_and_web_longer_quantum_reverse_both_orders():
    _, ir = _compiled("Prioritize batch tasks and give web tasks a longer quantum.")
    assert ir.cls("batch").prio < ir.cls("web").prio
    assert ir.cls("web").quantum_ms > ir.cls("batch").quantum_ms


def test_explicit_wait_bound_targets_only_batch():
    result, ir = _compiled("Ensure batch tasks do not wait longer than 500 ms.")
    assert result.intent["wait_requirements"] == {"batch": 500}
    assert [(g.kind, g.cls_name, g.value) for g in ir.guarantees] == [("no_starvation", "batch", 500)]


def test_non_scheduling_prompt_is_rejected_without_candidate():
    result = propose_policy("just say hi no bye bye")
    assert result.status == "UNSUPPORTED_INTENT"
    assert result.intent_status == "CLARIFICATION_REQUIRED"
    assert result.source_code == ""
    assert "couldn't identify a scheduling requirement" in result.rationale


def test_conflicting_priority_and_quantum_requirements_are_rejected():
    result = propose_policy(
        "Prioritize web over batch and prioritize batch over web; give web a longer quantum than batch "
        "and give batch a longer quantum than web."
    )
    assert result.status == "UNSUPPORTED_INTENT"
    assert result.intent["conflicts"]


def test_ambiguous_wait_request_is_visible():
    intent = extract_intent("Ensure no task waits longer than 500 ms.")
    assert intent.unsupported
    assert not intent.supported


def test_explicit_values_are_preserved():
    result, ir = _compiled("Prioritize batch over web. Give batch quantum 12 ms and web quantum 7 ms.")
    assert result.intent["quantum_values"] == {"batch": 12, "web": 7}
    assert ir.cls("batch").quantum_ms == 12
    assert ir.cls("web").quantum_ms == 7


def test_missing_live_provider_is_disclosed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = propose_policy("Prioritize web tasks over batch tasks.", provider_name="anthropic")
    assert result.provider == "rules-fallback"
    assert result.provider_error
    assert "Fallback" in result.mode_label
    assert result.consistency_status == "MATCH"
