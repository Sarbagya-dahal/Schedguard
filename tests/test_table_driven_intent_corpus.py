"""Table-driven test suite for the natural-language scheduling intent corpus.

Validates >= 50 positive and negative/ambiguous/conflicting/out-of-range cases
loaded from intents/table_driven_corpus.json, ensuring the deterministic offline
rule engine correctly parses, extracts, rejects or generates valid PolicyLang.
"""
import json
from pathlib import Path
import pytest

from schedguard.inference.policy_gen import extract_intent, generate_by_rules
from schedguard.compiler import compile_source

CORPUS_PATH = Path(__file__).parent.parent / "intents" / "table_driven_corpus.json"


def _load_corpus():
    with open(CORPUS_PATH, encoding="utf-8") as f:
        return json.load(f)


CORPUS = _load_corpus()


def test_corpus_size_requirement():
    """Verify that the version-controlled corpus contains at least 50 test cases."""
    assert len(CORPUS) >= 50


@pytest.mark.parametrize("item", CORPUS, ids=lambda x: x["id"])
def test_table_driven_intent_corpus_case(item):
    prompt = item["prompt"]
    expected_status = item["expected_status"]

    intent = extract_intent(prompt)
    res = generate_by_rules(prompt)

    if expected_status == "SUPPORTED":
        assert intent.supported is True, f"Intent not supported for prompt: {prompt!r}, errors: {intent.unsupported + intent.conflicts}"
        assert res.proposal_status == "PROPOSAL_GENERATED"
        assert res.consistency_status == "MATCH"
        assert res.source_code.strip() != ""

        # Verify classes
        if "expected_classes" in item:
            for c in item["expected_classes"]:
                assert c in intent.classes

        # Verify priority order if specified
        if "expected_priority_order" in item:
            assert intent.priority_order == item["expected_priority_order"]

        # Verify priority values if specified
        if "expected_priority_values" in item:
            for k, v in item["expected_priority_values"].items():
                assert intent.priority_values.get(k) == v

        # Verify quantum values if specified
        if "expected_quantum_values" in item:
            for k, v in item["expected_quantum_values"].items():
                assert intent.quantum_values.get(k) == v

        # Verify quantum order if specified
        if "expected_quantum_order" in item:
            assert intent.quantum_order == item["expected_quantum_order"]

        # Verify aging values if specified
        if "expected_aging_values" in item:
            for k, v in item["expected_aging_values"].items():
                assert intent.aging_values.get(k) == v

        # Verify wait requirements if specified
        if "expected_wait_requirements" in item:
            for k, v in item["expected_wait_requirements"].items():
                assert intent.wait_requirements.get(k) == v

        # Verify min share requirements if specified
        if "expected_min_share_requirements" in item:
            for k, v in item["expected_min_share_requirements"].items():
                assert intent.min_share_requirements.get(k) == v

        # Verify tuning if specified
        if "expected_tuning" in item:
            assert intent.tuning_requested == item["expected_tuning"]

        # Verify that generated source compiles with the real compiler
        c = compile_source(res.source_code)
        assert c.ok is True, f"Generated source failed compilation: {c.diagnostics}"
        assert c.ir is not None

    else:
        # Expected negative / unsupported / conflict
        assert (not intent.supported) or (res.proposal_status != "PROPOSAL_GENERATED")
        assert res.status == "UNSUPPORTED_INTENT"
        assert res.source_code == ""

        if "expected_conflict_substr" in item and item["expected_conflict_substr"]:
            sub = item["expected_conflict_substr"].lower()
            all_text = " ".join(intent.conflicts + [res.rationale]).lower()
            assert sub in all_text, f"Expected conflict substring {sub!r} in {all_text!r}"

        if "expected_unsupported_substr" in item and item["expected_unsupported_substr"]:
            sub = item["expected_unsupported_substr"].lower()
            all_text = " ".join(intent.unsupported + [res.rationale]).lower()
            assert sub in all_text, f"Expected unsupported substring {sub!r} in {all_text!r}"
