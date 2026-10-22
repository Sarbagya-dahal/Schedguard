import json
import os
import time
import hashlib
import urllib.request
import urllib.error
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


class OpenRouterProvider:
    """OpenRouter API provider using standard library urllib."""
    name = "openrouter"

    def __init__(self, model: str | None = None, timeout: int = 30, max_retries: int = 3):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")
        self.api_key = api_key
        m = model or os.environ.get("SCHEDGUARD_MODEL")
        if not m:
            raise ValueError("SCHEDGUARD_MODEL environment variable or model argument is required")
        self.model = m
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def complete(self, p: Prompt) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/SchedGuard",
            "X-Title": "SchedGuard",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": p.system},
                {"role": "user", "content": p.user},
            ],
            "temperature": 0,
        }
        data = json.dumps(payload).encode("utf-8")

        last_err = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(self.base_url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_data = resp.read()
                    parsed = json.loads(resp_data.decode("utf-8"))
                    if "choices" not in parsed or not parsed["choices"]:
                        raise RuntimeError(f"Malformed response from OpenRouter: {parsed}")
                    choice = parsed["choices"][0]
                    content = choice.get("message", {}).get("content")
                    if content is None:
                        raise RuntimeError(f"Malformed response message: {choice}")
                    return content
            except urllib.error.HTTPError as exc:
                last_err = exc
                body_bytes = b""
                try:
                    body_bytes = exc.read()
                except Exception:
                    pass
                body_str = body_bytes.decode("utf-8", errors="replace")
                err_msg = body_str
                try:
                    err_json = json.loads(body_str)
                    if isinstance(err_json, dict):
                        err_obj = err_json.get("error")
                        if isinstance(err_obj, dict):
                            err_msg = err_obj.get("message", body_str)
                        elif isinstance(err_obj, str):
                            err_msg = err_obj
                except Exception:
                    pass

                if exc.code == 429 or 500 <= exc.code < 600:
                    if attempt < self.max_retries:
                        time.sleep(1.0 * (2 ** attempt))
                        continue
                    raise RuntimeError(f"OpenRouter HTTP {exc.code} after {self.max_retries} retries: {err_msg}") from exc
                else:
                    raise RuntimeError(f"OpenRouter HTTP {exc.code}: {err_msg}") from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                last_err = exc
                if attempt < self.max_retries:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                raise RuntimeError(f"OpenRouter connection timed out/failed: {exc}") from exc
            except Exception as exc:
                if isinstance(exc, (RuntimeError, KeyError, IndexError)):
                    raise
                raise RuntimeError(f"OpenRouter request error: {exc}") from exc

        raise RuntimeError(f"OpenRouter failed after retries: {last_err}")


class CachedProvider:
    """Caches LLM completions to disk by hash of provider, model, system, and user prompts."""

    def __init__(self, inner, cache_dir: str = ".cache/llm"):
        self.inner = inner
        self.cache_dir = cache_dir
        self.name = getattr(inner, "name", "cached")
        self.model = getattr(inner, "model", None)

    def complete(self, p: Prompt) -> str:
        key = hashlib.sha256(
            f"{self.inner.name}:{self.model}:{p.system}:{p.user}".encode("utf-8")
        ).hexdigest()
        os.makedirs(self.cache_dir, exist_ok=True)
        path = os.path.join(self.cache_dir, f"{key}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)["content"]
        res = self.inner.complete(p)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"content": res}, f)
        return res

    def __getattr__(self, item):
        return getattr(self.inner, item)


class BudgetExceededError(RuntimeError):
    """Raised when call count exceeds the allowed budget."""
    pass


class BudgetProvider:
    """Enforces a maximum number of API calls across a session."""

    def __init__(self, inner, max_calls: int | None = None):
        self.inner = inner
        self.name = getattr(inner, "name", "budgeted")
        self.model = getattr(inner, "model", None)
        if max_calls is None:
            max_calls = int(os.environ.get("SCHEDGUARD_MAX_CALLS", 200))
        self.max_calls = max_calls
        self.calls = 0

    def complete(self, p: Prompt) -> str:
        if self.calls >= self.max_calls:
            raise BudgetExceededError(f"Budget exceeded: max {self.max_calls} calls reached")
        self.calls += 1
        return self.inner.complete(p)

    def __getattr__(self, item):
        return getattr(self.inner, item)


def get_provider(name: str | None = None):
    if name is None:
        name = os.environ.get("SCHEDGUARD_PROVIDER")
    if name is None:
        if os.environ.get("OPENROUTER_API_KEY"):
            name = "openrouter"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            name = "anthropic"
        else:
            name = "stub"

    if name == "stub":
        return StubProvider()
    elif name == "anthropic":
        inner = AnthropicProvider()
    elif name == "openrouter":
        inner = OpenRouterProvider()
    else:
        raise ValueError(f"unknown provider {name!r}")

    cached = CachedProvider(inner)
    budgeted = BudgetProvider(cached)
    return budgeted
