"""API contract regressions for safe, distinguishable provider failures."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from schedguard.server import app


SOURCE = "policy p { class web { quantum 5 ms; } }"


def test_infer_missing_openrouter_credentials_returns_safe_configuration_envelope():
    client = TestClient(app, raise_server_exceptions=False)
    with patch.dict("os.environ", {}, clear=True):
        response = client.post("/api/infer", json={"source": SOURCE, "provider": "openrouter"})

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["operation"] == "infer_guarantees"
    assert payload["error"]["provider"] == "openrouter"
    assert payload["error"]["category"] == "configuration"
    assert payload["error"]["retryable"] is False
    assert payload["error"]["correlation_id"]


def test_api_provider_envelope_never_reflects_bearer_secret():
    from schedguard.inference.providers import ProviderFailure
    from schedguard.server import provider_error_response

    response = provider_error_response(
        "policy_synthesis",
        "openrouter",
        ProviderFailure("upstream_http", "upstream request failed: Bearer secret-token", upstream_status=500, retryable=True),
    )

    assert response.status_code == 503
    assert b"secret-token" not in response.body
    assert b"openrouter" in response.body


def test_generate_and_synthesize_use_the_same_provider_error_envelope():
    client = TestClient(app, raise_server_exceptions=False)
    with patch.dict("os.environ", {}, clear=True):
        for route, operation in (("/api/generate", "generate_policy"), ("/api/synthesize", "synthesize_policy")):
            response = client.post(route, json={"prompt": "Prioritize web over batch", "provider": "openrouter"})
            payload = response.json()
            assert response.status_code == 400
            assert payload["ok"] is False
            assert payload["error"]["operation"] == operation
            assert payload["error"]["category"] == "configuration"
