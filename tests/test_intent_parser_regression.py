"""Regression tests for natural-language requirements used by the Studio."""
from schedguard.inference.policy_gen import extract_intent, generate_by_rules


EXACT = (
    "Create a CPU scheduling policy with two classes named web and batch. "
    "The web class is interactive and must have higher priority than the batch class. "
    "Set the web quantum to 6 ms and the batch quantum to 20 ms. "
    "Add aging of 162 ms to the batch class. Require that the maximum waiting time "
    "for batch is no more than 350 ms, with a no-starvation guarantee."
)


def test_explicit_studio_intent_extracts_all_requirements():
    intent = extract_intent(EXACT)
    assert intent.priority_order == ["web", "batch"]
    assert intent.quantum_values == {"web": 6, "batch": 20}
    assert intent.aging_values == {"batch": 162}
    assert intent.wait_requirements == {"batch": 350}
    assert intent.requested_guarantees == ["no_starvation"]
    assert not intent.unsupported

    result = generate_by_rules(EXACT)
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.consistency_status == "MATCH"
    assert "guarantee no_starvation(batch, 350 ms);" in result.source_code


def test_wait_bound_target_before_value_is_supported():
    intent = extract_intent("Batch maximum waiting time is no more than 350 milliseconds.")
    assert intent.wait_requirements == {"batch": 350}


def test_ambiguous_qualitative_no_starvation_stays_unsupported():
    intent = extract_intent("Create web and batch classes with no-starvation guarantees.")
    assert intent.requested_guarantees == ["no_starvation"]
    assert intent.wait_requirements == {}
    assert intent.unsupported
    assert not intent.supported


def test_contradictory_priority_remains_rejected():
    result = generate_by_rules("Prioritize web over batch and batch over web.")
    assert result.status == "UNSUPPORTED_INTENT"
    assert result.source_code == ""
    assert any("cycle" in c.lower() for c in result.intent["conflicts"])


def test_exact_p0_offline_rules_intent_workflow():
    prompt = (
        "Prioritize interactive web tasks, give batch tasks a longer time quantum, "
        "and prevent batch starvation with a maximum waiting-time requirement of 400 milliseconds."
    )
    from schedguard.inference.policy_gen import propose_policy
    from schedguard.compiler import compile_source

    # 1. Rule engine proposal
    result = propose_policy(prompt, provider_name="rules")
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.status == "UNTRUSTED_PROPOSAL"
    assert result.intent_status == "SUPPORTED"
    assert result.extracted_classes == ["web", "batch"]

    # 2. Source code checks
    source = result.source_code
    assert source != ""
    assert "guarantee no_starvation(batch, 400 ms);" in source

    # 3. Real compilation checks
    c_res = compile_source(source)
    assert c_res.ok and c_res.ir is not None
    classes = {c.name: c for c in c_res.ir.classes}
    assert "web" in classes and "batch" in classes

    # Lower numeric prio means higher priority in PolicyLang
    assert classes["web"].prio < classes["batch"].prio
    # Longer quantum for batch
    assert classes["batch"].quantum_ms > classes["web"].quantum_ms

    # 4. Intent consistency checks
    assert result.consistency_status == "MATCH"
    assert result.compilation_status == "COMPILATION_SUCCESS"
    assert result.consistency_errors == []

    from schedguard.verify.properties import check_all
    checked = check_all(c_res.ir)
    assert len(checked) == 1
    assert checked[0].status == "VERIFIED"


def test_explicitly_forbidden_guarantees_do_not_hide_positive_requirements():
    prompt = (
        "Create a scheduling policy that prioritizes interactive web tasks over batch tasks "
        "and gives batch tasks a longer time quantum. Do not add any formal guarantees."
    )
    intent = extract_intent(prompt)
    assert intent.priority_order == ["web", "batch"]
    assert intent.quantum_order == ["batch", "web"]
    assert intent.forbid_guarantees is True
    assert not intent.unsupported

    result = generate_by_rules(prompt)
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.consistency_status == "MATCH"
    assert "guarantee " not in result.source_code



def test_conjunctive_priority_cycle_is_rejected_before_policy_generation():
    result = generate_by_rules(
        "Web has higher priority than batch and batch has higher priority than web."
    )
    assert result.status == "UNSUPPORTED_INTENT"
    assert result.source_code == ""
    assert result.intent["conflicts"]


def test_three_class_priority_cycle_is_rejected_before_policy_generation():
    result = generate_by_rules(
        "Web has higher priority than batch; batch has higher priority than real-time; "
        "real-time has higher priority than web."
    )
    assert result.status == "UNSUPPORTED_INTENT"
    assert result.intent["conflicts"]


def test_explicit_equal_priority_is_valid_equal_tier_semantics():
    result = generate_by_rules("Web priority 0 and batch priority 0.")
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.intent["conflicts"] == []
    assert "prio 0;" in result.source_code
