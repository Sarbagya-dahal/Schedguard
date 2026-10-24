import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from schedguard.cli import main
from schedguard.inference.policy_gen import _extract_policy_source, propose_policy
from schedguard.server import app


PROMPT = "Prioritize interactive web over batch; batch must not wait longer than 350 ms."
SOURCE = """policy llm_policy {
  option max_tasks = 8;
  class web { prio 0; quantum 5 ms; kind interactive; }
  class batch { prio 1; quantum 20 ms; aging 175 ms; kind batch; }
  guarantee no_starvation(batch, 350 ms);
}"""


def _mock_provider(response=None, error=None):
    class Provider:
        name = "openrouter"
        model = "test/model"

        def __init__(self):
            if error:
                raise error

        def complete(self, prompt):
            assert "<extracted_intent>" in prompt.user
            assert "350" in prompt.user
            if error:
                raise error
            return response

    return Provider


def test_openrouter_success_uses_live_provider_and_validates_source():
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(SOURCE)):
        result = propose_policy(PROMPT, provider_name="openrouter")
    assert result.provider == "openrouter"
    assert result.mode_label == "OpenRouter (Live LLM)"
    assert result.is_live_llm is True
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.compilation_status == "COMPILATION_SUCCESS"
    assert result.consistency_status == "MATCH"
    assert result.source_code == SOURCE


@pytest.mark.parametrize("response", ["not PolicyLang", "```json\n{\"policy\": 1}\n```"])
def test_openrouter_malformed_response_is_rejected_without_rule_fallback(response):
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(response)):
        result = propose_policy(PROMPT, provider_name="openrouter")
    assert result.provider == "openrouter"
    assert result.is_live_llm is True
    assert result.proposal_status == "PROPOSAL_REJECTED"
    assert result.consistency_status == "MISMATCH"
    assert result.compilation_status == "COMPILATION_FAILED"
    assert result.source_code != SOURCE


def test_openrouter_api_error_is_structured_and_never_offline_falls_back():
    secret = "test-openrouter-key"
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": secret, "SCHEDGUARD_MODEL": "test/model"}, clear=True):
        with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(error=RuntimeError(f"HTTP 401 Bearer {secret}"))):
            result = propose_policy(PROMPT, provider_name="openrouter")
    assert result.status == "PROVIDER_ERROR"
    assert result.provider == "openrouter"
    assert result.source_code == ""
    assert "offline_rules" not in result.mode_label
    assert secret not in result.provider_error
    assert "401" in result.provider_error


def test_openrouter_missing_credentials_returns_useful_provider_error():
    with patch.dict("os.environ", {}, clear=True):
        result = propose_policy(PROMPT, provider_name="openrouter")
    assert result.status == "PROVIDER_ERROR"
    assert result.provider == "openrouter"
    assert "OPENROUTER_API_KEY" in result.provider_error
    assert result.source_code == ""


def test_openrouter_consistency_rejection_preserves_live_metadata():
    wrong = SOURCE.replace("350 ms", "250 ms")
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(wrong)):
        result = propose_policy(PROMPT, provider_name="openrouter")
    assert result.is_live_llm is True
    assert result.provider == "openrouter"
    assert result.proposal_status == "PROPOSAL_REJECTED"
    assert any("350ms" in e for e in result.consistency_errors)


def test_policy_source_extraction_accepts_fences_and_surrounding_prose():
    assert _extract_policy_source("Here is the policy:\n" + SOURCE + "\nThat is all.") == SOURCE
    assert _extract_policy_source("```schedlang\n" + SOURCE + "\n```") == SOURCE
    assert _extract_policy_source("   ") == ""


def test_empty_live_output_is_rejected_without_success():
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider("")):
        result = propose_policy(PROMPT, provider_name="openrouter")
    assert result.is_live_llm is True
    assert result.proposal_status == "PROPOSAL_REJECTED"
    assert result.compilation_status == "NOT_RUN"
    assert result.consistency_status == "NOT_RUN"
    assert result.consistency_errors == ["Provider returned empty policy output."]


def test_invalid_first_candidate_gets_one_same_provider_correction_attempt():
    class SequenceProvider:
        name = "openrouter"
        model = "test/model"
        calls = 0

        def __init__(self):
            self.calls = 0

        def complete(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return "policy broken { > }"
            assert "compiler_diagnostics" in prompt.user
            return SOURCE

    provider = SequenceProvider()
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", return_value=provider):
        result = propose_policy(PROMPT, provider_name="openrouter")
    assert provider.calls == 2
    assert result.proposal_status == "PROPOSAL_GENERATED"
    assert result.compilation_status == "COMPILATION_SUCCESS"
    assert result.consistency_status == "MATCH"
    assert [a["attempt"] for a in result.attempts] == [1, 2]


def test_valid_candidate_missing_requested_guarantee_is_rejected():
    missing = SOURCE.replace("  guarantee no_starvation(batch, 350 ms);\n", "")
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(missing)):
        result = propose_policy(PROMPT, provider_name="openrouter")
    assert result.proposal_status == "PROPOSAL_REJECTED"
    assert result.compilation_status == "COMPILATION_SUCCESS"
    assert result.consistency_status == "MISMATCH"
    assert any("Missing no_starvation" in e for e in result.consistency_errors)


def test_valid_candidate_reversing_priority_is_rejected():
    reversed_source = SOURCE.replace("class web { prio 0;", "class web { prio 1;").replace(
        "class batch { prio 1;", "class batch { prio 0;")
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(reversed_source)):
        result = propose_policy(PROMPT, provider_name="openrouter")
    assert result.proposal_status == "PROPOSAL_REJECTED"
    assert result.consistency_status == "MISMATCH"
    assert any("higher priority" in e for e in result.consistency_errors)


def test_offline_rules_remains_honestly_labelled():
    result = propose_policy(PROMPT, provider_name="rules")
    assert result.provider == "offline_rules"
    assert result.mode_label == "Deterministic Rule Engine (Offline)"
    assert result.is_live_llm is False


def test_cli_synth_openrouter_workflow_is_real_provider_path(capsys):
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(SOURCE)):
        with pytest.raises(SystemExit) as exc:
            main(["synth", PROMPT, "--provider", "openrouter", "--no-repair", "--json"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["proposal"]["provider"] == "openrouter"
    assert payload["proposal"]["is_live_llm"] is True


def test_api_synthesize_openrouter_workflow_uses_same_provider_path():
    client = TestClient(app)
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(SOURCE)):
        response = client.post("/api/synthesize", json={"prompt": PROMPT, "provider": "openrouter", "repair": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["proposal"]["provider"] == "openrouter"
    assert payload["proposal"]["mode_label"] == "OpenRouter (Live LLM)"
    assert payload["proposal"]["is_live_llm"] is True


def test_api_synthesize_openrouter_default_repair_keeps_verifier_authority():
    client = TestClient(app)
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(SOURCE)):
        response = client.post("/api/synthesize", json={"prompt": PROMPT, "provider": "openrouter"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["proposal"]["provider"] == "openrouter"
    assert payload["proposal"]["guarantee_status"] == "VERIFIED"
    assert payload["repair"]["iterations"][-1]["status"] == "VERIFIED"


def test_api_synthesize_rejects_invalid_live_candidate_without_500():
    invalid_source = "policy broken { > }"
    client = TestClient(app)
    with patch("schedguard.inference.policy_gen.OpenRouterProvider", _mock_provider(invalid_source)):
        response = client.post("/api/synthesize", json={"prompt": PROMPT, "provider": "openrouter"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["proposal"]["proposal_status"] == "PROPOSAL_REJECTED"
    assert payload["proposal"]["compilation_status"] == "COMPILATION_FAILED"
    assert payload["proposal"]["consistency_status"] == "MISMATCH"
    assert payload["repair"]["iterations"][0]["status"] == "REJECTED"
