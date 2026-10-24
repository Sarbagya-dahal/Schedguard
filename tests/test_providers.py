"""Tests for LLM providers: OpenRouter, caching, budget guard, and provider selection.
All tests work without network access — HTTP transport is mocked."""
import json, os, hashlib, tempfile, shutil
import pytest
from unittest.mock import patch, MagicMock
from schedguard.inference.prompts import Prompt


# --- Helpers ---
def _make_prompt(system="sys", user="usr"):
    return Prompt(system=system, user=user, context={})


def _openrouter_response_body(content="hello"):
    return json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode()


# --- OpenRouterProvider tests ---

class TestOpenRouterProvider:
    def test_http_failure_exposes_safe_category_status_and_retryability(self):
        from schedguard.inference.providers import OpenRouterProvider, ProviderFailure
        import urllib.error

        err_body = MagicMock()
        err_body.read.return_value = b'{"error": {"message": "upstream unavailable"}}'
        err = urllib.error.HTTPError("url", 500, "Server Error", {}, err_body)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "SCHEDGUARD_MODEL": "test/model"}):
            with patch("urllib.request.urlopen", side_effect=err), patch("time.sleep"):
                with pytest.raises(ProviderFailure) as caught:
                    OpenRouterProvider(max_retries=0).complete(_make_prompt())

        assert caught.value.category == "upstream_http"
        assert caught.value.upstream_status == 500
        assert caught.value.retryable is True

    def test_successful_response(self):
        from schedguard.inference.providers import OpenRouterProvider
        body = _openrouter_response_body('{"guarantees":[], "rationale":"test"}')
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "SCHEDGUARD_MODEL": "test/model"}):
            with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                prov = OpenRouterProvider()
                result = prov.complete(_make_prompt())
                assert result == '{"guarantees":[], "rationale":"test"}'
                # Verify the request was made
                mock_urlopen.assert_called_once()
                sent_payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
                assert sent_payload["stream"] is False
                assert sent_payload["max_tokens"] == 4096

    def test_retry_on_429(self):
        from schedguard.inference.providers import OpenRouterProvider
        import urllib.error
        err_body = b'{"error": "rate limited"}'
        err_resp = MagicMock()
        err_resp.read.return_value = err_body
        err_429 = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, err_resp)

        ok_resp = MagicMock()
        ok_resp.read.return_value = _openrouter_response_body("ok")
        ok_resp.status = 200
        ok_resp.__enter__ = lambda s: s
        ok_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "SCHEDGUARD_MODEL": "test/model"}):
            with patch("urllib.request.urlopen", side_effect=[err_429, ok_resp]):
                with patch("time.sleep"):  # Don't actually sleep in tests
                    prov = OpenRouterProvider()
                    result = prov.complete(_make_prompt())
                    assert result == "ok"

    def test_http_error_with_body(self):
        from schedguard.inference.providers import OpenRouterProvider
        import urllib.error
        err_body = MagicMock()
        err_body.read.return_value = b'{"error": {"message": "bad request detail"}}'
        err = urllib.error.HTTPError("url", 400, "Bad Request", {}, err_body)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "SCHEDGUARD_MODEL": "test/model"}):
            with patch("urllib.request.urlopen", side_effect=err):
                prov = OpenRouterProvider()
                with pytest.raises(RuntimeError, match="bad request detail"):
                    prov.complete(_make_prompt())

    def test_timeout(self):
        from schedguard.inference.providers import OpenRouterProvider
        import urllib.error
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "SCHEDGUARD_MODEL": "test/model"}):
            with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
                with patch("time.sleep"):
                    prov = OpenRouterProvider()
                    with pytest.raises(RuntimeError, match="timed out|timeout|Timeout"):
                        prov.complete(_make_prompt())

    def test_missing_api_key(self):
        from schedguard.inference.providers import OpenRouterProvider
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
                OpenRouterProvider()

    def test_missing_model_uses_default_flint(self):
        """Without SCHEDGUARD_MODEL, OpenRouterProvider defaults to recursive/flint-v1.0:free."""
        from schedguard.inference.providers import OpenRouterProvider
        env = {k: v for k, v in os.environ.items() if k != "SCHEDGUARD_MODEL"}
        env["OPENROUTER_API_KEY"] = "sk-test"
        with patch.dict(os.environ, env, clear=True):
            prov = OpenRouterProvider()
            assert prov.model == "recursive/flint-v1.0:free"

            body = _openrouter_response_body('{"guarantees":[], "rationale":"test"}')
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                prov.complete(_make_prompt())
                req = mock_urlopen.call_args[0][0]
                sent_payload = json.loads(req.data.decode("utf-8"))
                assert sent_payload["model"] == "recursive/flint-v1.0:free"

    def test_malformed_response(self):
        from schedguard.inference.providers import OpenRouterProvider
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"not_choices": []}'
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "SCHEDGUARD_MODEL": "test/model"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                prov = OpenRouterProvider()
                with pytest.raises((RuntimeError, KeyError, IndexError)):
                    prov.complete(_make_prompt())

    def test_retry_exhaustion(self):
        from schedguard.inference.providers import OpenRouterProvider
        import urllib.error
        err_body = MagicMock()
        err_body.read.return_value = b'{"error": "server error"}'
        err = urllib.error.HTTPError("url", 500, "Server Error", {}, err_body)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "SCHEDGUARD_MODEL": "test/model"}):
            with patch("urllib.request.urlopen", side_effect=err):
                with patch("time.sleep"):
                    prov = OpenRouterProvider(max_retries=2)
                    with pytest.raises(RuntimeError):
                        prov.complete(_make_prompt())


# --- Provider selection tests ---

class TestProviderSelection:
    def test_selection_stub(self):
        from schedguard.inference.providers import get_provider
        prov = get_provider("stub")
        assert prov.name == "stub"

    def test_selection_openrouter_env(self):
        from schedguard.inference.providers import get_provider
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "SCHEDGUARD_MODEL": "test/m"}):
            prov = get_provider("openrouter")
            assert prov.name == "openrouter"

    def test_auto_detect_openrouter(self):
        from schedguard.inference.providers import get_provider
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "SCHEDGUARD_PROVIDER")}
        env["OPENROUTER_API_KEY"] = "sk-test"
        env["SCHEDGUARD_MODEL"] = "test/m"
        with patch.dict(os.environ, env, clear=True):
            prov = get_provider(None)
            assert prov.name == "openrouter"

    def test_auto_detect_stub_fallback(self):
        from schedguard.inference.providers import get_provider
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "SCHEDGUARD_PROVIDER")}
        with patch.dict(os.environ, env, clear=True):
            prov = get_provider(None)
            assert prov.name == "stub"


# --- CachedProvider tests ---

class TestCachedProvider:
    def test_cache_hit_and_miss(self):
        from schedguard.inference.providers import CachedProvider, StubProvider
        cache_dir = tempfile.mkdtemp()
        try:
            inner = MagicMock()
            inner.name = "mock"
            inner.model = "m"
            inner.complete.return_value = '{"guarantees":[]}'
            cached = CachedProvider(inner, cache_dir=cache_dir)

            p = _make_prompt("system1", "user1")
            r1 = cached.complete(p)
            assert inner.complete.call_count == 1
            r2 = cached.complete(p)
            assert inner.complete.call_count == 1  # cache hit
            assert r1 == r2
        finally:
            shutil.rmtree(cache_dir, ignore_errors=True)


# --- BudgetProvider tests ---

class TestBudgetProvider:
    def test_budget_exceeded(self):
        from schedguard.inference.providers import BudgetProvider, BudgetExceededError
        inner = MagicMock()
        inner.complete.return_value = "ok"
        budget = BudgetProvider(inner, max_calls=2)
        budget.complete(_make_prompt())
        budget.complete(_make_prompt())
        with pytest.raises(BudgetExceededError):
            budget.complete(_make_prompt())
