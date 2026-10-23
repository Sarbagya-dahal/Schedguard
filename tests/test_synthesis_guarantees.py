"""Guarantee extraction and honest offline synthesis behavior."""
from schedguard.inference.policy_gen import generate_by_rules
from schedguard.synth.agent import synthesize_policy


def test_explicit_wait_bound_extracts_no_starvation_guarantee():
    result = generate_by_rules(
        "Prioritize interactive over batch; batch must not wait longer than 350 ms."
    )
    assert result.extracted_guarantees == ["  guarantee no_starvation(batch, 350 ms);"]
    assert "no_starvation" in result.source_code
    assert result.consistency_status == "MATCH"

    synthesized = synthesize_policy(
        "Prioritize interactive over batch; batch must not wait longer than 350 ms.",
        provider_name="stub",
    )
    assert synthesized.success is True
    assert synthesized.proposal["guarantee_status"] == "VERIFIED"


def test_qualitative_no_starvation_is_reported_unsupported_without_bound():
    result = generate_by_rules(
        "Create interactive and batch classes while maintaining no-starvation guarantees."
    )
    assert result.status == "UNSUPPORTED_INTENT"
    assert result.source_code == ""
    assert result.extracted_guarantees == ["no_starvation"]
    assert "explicit maximum wait bound" in result.rationale
    assert result.guarantee_status == "NOT_RUN"


def test_synthesis_never_claims_unverified_requested_guarantee():
    result = synthesize_policy(
        "Create interactive and batch classes while maintaining no-starvation guarantees.",
        provider_name="stub",
    )
    assert result.success is False
    assert result.proposal["proposal_status"] == "UNSUPPORTED_INTENT"
    assert result.proposal["extracted_guarantees"] == ["no_starvation"]
