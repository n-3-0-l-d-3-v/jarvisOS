"""
Feature 19: the central AI client.

Regression suite for the outage that motivated it — Google retired
`gemini-2.0-flash` and Groq retired `llama-3.3-70b-versatile`, and because every
call site swallowed the 404, Jarvis silently ran on the keyword classifier for
weeks. These tests pin the behaviour that prevents a repeat.
"""

import pytest

from jarvis import ai as AI


@pytest.fixture(autouse=True)
def _clean_cache():
    AI.reset_cache()
    yield
    AI.reset_cache()


# --- provider ladder -------------------------------------------------------
def test_complete_prefers_groq_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(AI, "_try_groq",
                        lambda p, m, t: calls.append("groq") or "groq answer")
    monkeypatch.setattr(AI, "_try_gemini",
                        lambda p, m, t: calls.append("gemini") or "gemini answer")
    assert AI.complete("q", prefer="groq") == "groq answer"
    assert calls == ["groq"], "gemini should not be called when groq succeeds"


def test_complete_falls_through_to_second_provider(monkeypatch):
    monkeypatch.setattr(AI, "_try_groq", lambda p, m, t: None)
    monkeypatch.setattr(AI, "_try_gemini", lambda p, m, t: "gemini answer")
    assert AI.complete("q", prefer="groq") == "gemini answer"


def test_complete_returns_none_when_everything_fails(monkeypatch):
    monkeypatch.setattr(AI, "_try_groq", lambda p, m, t: None)
    monkeypatch.setattr(AI, "_try_gemini", lambda p, m, t: None)
    assert AI.complete("q") is None


def test_prefer_gemini_reverses_order(monkeypatch):
    calls = []
    monkeypatch.setattr(AI, "_try_groq", lambda p, m, t: calls.append("groq") or "g")
    monkeypatch.setattr(AI, "_try_gemini", lambda p, m, t: calls.append("gemini") or "x")
    AI.complete("q", prefer="gemini")
    assert calls[0] == "gemini"


# --- model fallback within a provider (the actual outage) ------------------
def test_dead_model_is_skipped_for_the_next_one(monkeypatch):
    """A 404 on model #1 must transparently try model #2."""
    monkeypatch.setattr(AI, "GROQ_API_KEY", "key", raising=False)
    monkeypatch.setattr(AI, "GROQ_MODELS", ["dead-model", "live-model"], raising=False)

    class _Resp:
        def __init__(self, status, payload=None, text=""):
            self.status_code = status
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    def fake_post(url, headers=None, json=None, timeout=None):
        if json["model"] == "dead-model":
            return _Resp(404, text="model_not_found")
        return _Resp(200, {"choices": [{"message": {"content": "recovered"}}]})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    assert AI._try_groq("q", 100, 0.1) == "recovered"
    assert AI._working["groq"] == "live-model", "working model should be cached"


def test_working_model_is_cached_and_reused(monkeypatch):
    monkeypatch.setattr(AI, "GROQ_API_KEY", "key", raising=False)
    monkeypatch.setattr(AI, "GROQ_MODELS", ["m1", "m2"], raising=False)
    seen = []

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "ok"}}]}

    import httpx
    monkeypatch.setattr(httpx, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        seen.append(json["model"]) or _Resp())

    AI._try_groq("q", 100, 0.1)
    AI._try_groq("q", 100, 0.1)
    assert seen == ["m1", "m1"], "second call should reuse the cached model"


def test_all_models_dead_returns_none_and_records_error(monkeypatch):
    monkeypatch.setattr(AI, "GROQ_API_KEY", "key", raising=False)
    monkeypatch.setattr(AI, "GROQ_MODELS", ["d1", "d2"], raising=False)

    class _Resp:
        status_code = 404
        text = "model_not_found"

        @staticmethod
        def json():
            return {}

    import httpx
    monkeypatch.setattr(httpx, "post",
                        lambda url, headers=None, json=None, timeout=None: _Resp())

    assert AI._try_groq("q", 100, 0.1) is None
    assert "404" in AI.last_error()["groq"] or "d2" in AI.last_error()["groq"]


def test_no_api_key_returns_none_without_network(monkeypatch):
    monkeypatch.setattr(AI, "GROQ_API_KEY", "", raising=False)
    monkeypatch.setattr(AI, "GEMINI_API_KEY", "", raising=False)
    assert AI._try_groq("q", 10, 0.1) is None
    assert AI._try_gemini("q", 10, 0.1) is None


# --- fatal vs transient ----------------------------------------------------
@pytest.mark.parametrize("message,fatal", [
    ("404 model not found", True),
    ("This model is no longer available", True),
    ("model does not exist", True),
    ("401 unauthorized", True),
    ("429 rate limit exceeded", False),
    ("connection timed out", False),
])
def test_fatal_error_detection(message, fatal):
    assert AI._is_fatal(message) is fatal


# --- JSON extraction -------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Sure!\n{"a": 1}\nhope that helps', {"a": 1}),
    ('[{"i": 0}]', [{"i": 0}]),
    ('```\n[{"i": 0}]\n```', [{"i": 0}]),
])
def test_extract_json_shapes(raw, expected):
    assert AI.extract_json(raw) == expected


def test_extract_json_returns_none_on_garbage():
    assert AI.extract_json("no json here at all") is None
    assert AI.extract_json("") is None


def test_complete_json_parses(monkeypatch):
    monkeypatch.setattr(AI, "complete",
                        lambda p, m=1200, t=0.1, prefer=None: '```json\n{"ok":true}\n```')
    assert AI.complete_json("q") == {"ok": True}


# --- health ----------------------------------------------------------------
def test_health_reports_both_providers(monkeypatch):
    monkeypatch.setattr(AI, "GEMINI_API_KEY", "k", raising=False)
    monkeypatch.setattr(AI, "GROQ_API_KEY", "k", raising=False)
    monkeypatch.setattr(AI, "_try_gemini", lambda p, m, t: None)
    monkeypatch.setattr(AI, "_try_groq", lambda p, m, t: "OK")
    report = AI.health()
    assert report["groq"]["ok"] is True
    assert report["gemini"]["ok"] is False
    assert report["any"] is True


def test_health_flags_total_outage(monkeypatch):
    """The exact condition that hid for weeks must now be reported."""
    monkeypatch.setattr(AI, "GEMINI_API_KEY", "k", raising=False)
    monkeypatch.setattr(AI, "GROQ_API_KEY", "k", raising=False)
    monkeypatch.setattr(AI, "_try_gemini", lambda p, m, t: None)
    monkeypatch.setattr(AI, "_try_groq", lambda p, m, t: None)
    assert AI.health()["any"] is False


def test_health_reports_missing_keys(monkeypatch):
    monkeypatch.setattr(AI, "GEMINI_API_KEY", "", raising=False)
    monkeypatch.setattr(AI, "GROQ_API_KEY", "", raising=False)
    report = AI.health()
    assert report["any"] is False
    assert "no API key" in report["groq"]["error"]


# --- config ----------------------------------------------------------------
def test_model_lists_are_non_empty_lists():
    """Guards against someone regressing these back to bare strings."""
    from jarvis.config import GEMINI_MODELS, GROQ_MODELS
    for models in (GEMINI_MODELS, GROQ_MODELS):
        assert isinstance(models, list) and len(models) >= 2


def test_retired_models_are_not_in_defaults():
    from jarvis.config import GEMINI_MODELS, GROQ_MODELS
    retired = {"gemini-2.0-flash", "llama-3.3-70b-versatile"}
    assert not (set(GEMINI_MODELS) | set(GROQ_MODELS)) & retired
