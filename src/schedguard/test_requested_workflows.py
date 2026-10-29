from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from schedguard.compiler import compile_source
from schedguard.inference.policy_gen import extract_intent, generate_by_rules, propose_policy
from schedguard.repair.loop import repair_policy
from schedguard.server import app
from schedguard.synth.agent import apply_clarification
from schedguard.verify.properties import check_all


def test_conversational_intent_preserves_priority_quantum_and_wait_bound():
    intent = extract_intent(
        "Keep web requests responsive, but don't let background jobs get stuck. "
        "They should get a chance to run within 400 ms."
    )
    assert intent.supported
    assert intent.priority_order[:2] == ["web", "batch"]
    assert intent.quantum_order == []
    assert intent.wait_requirements == {"batch": 400}


def test_prompt_one_preserves_all_explicit_requirements():
    prompt = (
        "Prioritize interactive web tasks over batch tasks. Give batch tasks a longer time quantum "
        "than web tasks. Require that batch tasks do not wait longer than 400 milliseconds."
    )
    result = generate_by_rules(prompt)
    intent = extract_intent(prompt)
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert intent.priority_order[:2] == ["web", "batch"]
    assert intent.quantum_order == ["batch", "web"]
    assert intent.wait_requirements == {"batch": 400}
    assert "guarantee no_starvation(batch, 400 ms);" in result.source_code


def test_prompt_two_composes_cpu_turn_and_time_slice_language():
    prompt = (
        "Keep web requests responsive, but make sure background jobs get CPU time within 400 ms. "
        "Background jobs can use longer time slices than UI requests."
    )
    result = generate_by_rules(prompt)
    intent = extract_intent(prompt)
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert intent.wait_requirements == {"batch": 400}
    assert intent.quantum_order == ["batch", "web"]
    assert "guarantee no_starvation(batch, 400 ms);" in result.source_code


def test_prompt_d_preserves_wait_bound_and_pronoun_quantum_relation():
    prompt = (
        "Web tasks take priority over batch tasks. Background jobs need to run within 400 milliseconds, "
        "and their quantum should be longer than the web quantum."
    )
    result = generate_by_rules(prompt)
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.intent["priority_order"][:2] == ["web", "batch"]
    assert result.intent["wait_requirements"] == {"batch": 400}
    assert result.intent["quantum_order"] == ["batch", "web"]
    assert "guarantee no_starvation(batch, 400 ms);" in result.source_code
    compiled = compile_source(result.source_code)
    assert compiled.ok
    assert [verdict.status for verdict in check_all(compiled.ir)] == ["VERIFIED"]


def test_prompt_d_live_candidate_is_checked_against_same_canonical_intent():
    prompt = (
        "Web tasks take priority over batch tasks. Background jobs need to run within 400 milliseconds, "
        "and their quantum should be longer than the web quantum."
    )
    source = """policy live_prompt_d {
      option max_tasks = 8;
      class web { prio 0; quantum 5 ms; kind interactive; }
      class batch { prio 1; quantum 20 ms; aging 200 ms; kind batch; }
      guarantee no_starvation(batch, 400 ms);
    }"""

    class Provider:
        model = "test/model"

        def complete(self, _prompt):
            return source

    with patch("schedguard.inference.policy_gen.OpenRouterProvider", return_value=Provider()):
        result = propose_policy(prompt, provider_name="openrouter")
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.consistency_status == "MATCH"
    assert result.intent["wait_requirements"] == {"batch": 400}
    assert result.intent["quantum_order"] == ["batch", "web"]


def test_contradictory_priority_is_rejected_before_live_candidate_acceptance():
    prompt = "Give web tasks higher priority than batch tasks, and also give batch tasks higher priority than web tasks."
    intent = extract_intent(prompt)
    assert intent.conflicts

    class Provider:
        calls = 0
        model = "test/model"

        def __init__(self):
            pass

        def complete(self, _prompt):
            self.calls += 1
            return "policy seemingly_valid { class web { prio 0; quantum 5 ms; } class batch { prio 1; quantum 20 ms; } }"

    provider = Provider()
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", return_value=provider):
        result = __import__("schedguard.inference.policy_gen", fromlist=["propose_policy"]).propose_policy(prompt, "openrouter")
    assert result.status in {"UNSUPPORTED_INTENT", "CONFLICTING_REQUIREMENTS"}
    assert result.proposal_status == "CONFLICTING_REQUIREMENTS"
    assert result.source_code == ""
    assert result.intent_status == "CONFLICTING"
    assert provider.calls == 0


def test_qualitative_neglect_requests_wait_bound_clarification():
    prompt = "Keep interactive requests responsive and prevent background jobs from being neglected."
    result = generate_by_rules(prompt)
    assert result.proposal_status == "UNSUPPORTED_INTENT"
    assert result.intent_status == "CLARIFICATION_REQUIRED"
    assert result.extracted_guarantees == ["no_starvation"]
    assert result.source_code == ""
    assert "maximum acceptable waiting time" in result.clarification_question.lower()
    assert any("maximum wait" in item.lower() for item in result.intent["clarifications"] + result.intent["unsupported"])


def test_clarification_answer_resumes_synthesis_and_preserves_original_goal():
    original = "Keep interactive requests responsive and prevent background jobs from being neglected."
    answered = apply_clarification(original, "400 ms")
    result = generate_by_rules(answered)
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.intent["priority_order"][:2] == ["web", "batch"]
    assert result.intent["wait_requirements"] == {"batch": 400}
    assert "guarantee no_starvation(batch, 400 ms);" in result.source_code


def test_invalid_clarification_answer_is_rejected_without_synthesis():
    try:
        apply_clarification("Keep background jobs from being neglected.", "soon")
    except ValueError as exc:
        assert "whole-number bound" in str(exc)
    else:
        raise AssertionError("invalid clarification unexpectedly accepted")


def test_synthesis_api_exposes_question_and_resumes_with_answer():
    client = TestClient(app)
    original = "Keep interactive requests responsive and prevent background jobs from being neglected."
    first = client.post("/api/synthesize", json={"prompt": original, "provider": "rules", "repair": False})
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["source"] == ""
    assert first_data["proposal"]["intent_status"] == "CLARIFICATION_REQUIRED"
    assert "maximum acceptable waiting time" in first_data["proposal"]["clarification_question"].lower()

    resumed = client.post("/api/synthesize", json={
        "prompt": original, "provider": "rules", "repair": False, "clarification_answer": "400 ms"
    })
    assert resumed.status_code == 200
    resumed_data = resumed.json()
    assert resumed_data["proposal"]["proposal_status"] == "PROPOSAL_GENERATED"
    assert resumed_data["proposal"]["intent"]["wait_requirements"] == {"batch": 400}
    assert "guarantee no_starvation(batch, 400 ms);" in resumed_data["source"]

    invalid = client.post("/api/synthesize", json={
        "prompt": original, "provider": "rules", "repair": False, "clarification_answer": "soon"
    })
    assert invalid.status_code == 400
    assert "whole-number bound" in invalid.json()["detail"]


def test_equivalent_duration_units_normalize_to_same_wait_requirement():
    prompts = [
        "Batch tasks must not wait longer than 400 ms.",
        "Background jobs get CPU time within 0.4 seconds.",
        "Worker jobs should receive a CPU turn within four hundred milliseconds.",
    ]
    assert [extract_intent(prompt).wait_requirements for prompt in prompts] == [
        {"batch": 400}, {"batch": 400}, {"batch": 400}
    ]


def test_explicit_aging_prohibition_is_retained():
    prompt = "Keep web above batch, do not use aging, and require batch to get CPU time within 400 ms."
    intent = extract_intent(prompt)
    result = generate_by_rules(prompt)
    assert intent.forbid_aging is True
    assert intent.wait_requirements == {"batch": 400}
    assert "aging " not in result.source_code
    assert "aging" in " ".join(intent.assumptions + intent.unsupported + intent.conflicts).lower()


def test_qualitative_starvation_request_asks_for_missing_bound():
    intent = extract_intent(
        "I want interactive tasks to feel responsive, while background jobs make steady progress and cannot starve."
    )
    assert intent.requested_guarantees == ["no_starvation"]
    assert intent.wait_requirements == {}
    assert not intent.supported
    assert any("explicit maximum wait" in message for message in intent.unsupported)


def test_failed_repair_preserves_original_source_and_reason():
    source = """policy bad {
      option max_tasks = 1;
      class web { prio 0; quantum 1 ms; kind interactive; }
      class batch { prio 1; quantum 1 ms; aging 1 ms; kind batch; }
      guarantee no_starvation(batch, 1 ms);
    }"""
    result = repair_policy(source, feedback="heuristic")
    assert result.success is False
    assert result.source == source
    assert result.status in {"INFEASIBLE", "REPAIR_FAILED"}
    assert result.diagnostic


def test_demo_api_exposes_allowlisted_workflows_and_codegen_smoke():
    client = TestClient(app)
    response = client.get("/api/examples")
    assert response.status_code == 200
    examples = {item["demo_id"]: item for item in response.json()["examples"] if item.get("demo_id")}
    assert {"verified-aging-baseline", "repairable-tight-wait", "repairable-starvation", "no-guarantees", "sched-ext-smoke-supported", "sched-ext-unsupported-policy", "sched-ext-multiclass-aging"} <= set(examples)
    smoke = examples["sched-ext-smoke-supported"]["code"]
    codegen = client.post("/api/codegen", json={"source": smoke})
    assert codegen.status_code == 200
    assert codegen.json()["status"] == "PASSED"
    assert codegen.json()["c_code"]


def test_editor_has_explicit_load_example_action_and_no_auto_run():
    html = Path(__file__).parent / "studio" / "index.html"
    js = Path(__file__).parent / "studio" / "app.js"
    assert "editorLoadExampleBtn" in html.read_text(encoding="utf-8")
    source = js.read_text(encoding="utf-8")
    change_block = source[source.index('const exampleSelect = document.getElementById("editorExampleSelect")'):source.index('const verifExampleSelect = document.getElementById("verifExampleSelect")')]
    assert "loadExample(e.target.value)" not in change_block
