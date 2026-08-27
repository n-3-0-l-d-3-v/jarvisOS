"""
Single AI client for all of Jarvis — with model fallback and loud failures.

WHY THIS EXISTS
---------------
Model names were hardcoded in eight places (classifier, dsa_agent, youtube_agent,
article_fetcher, rss_processor, retrieval, review, wiki). When Google retired
`gemini-2.0-flash` and Groq retired `llama-3.3-70b-versatile`, every one of those
call sites started returning 404 — and because each had a `except: return None`
fallback, Jarvis silently degraded to the offline keyword classifier with no
error anywhere. Notes kept getting saved, just badly: truncated titles, near
duplicate pages, no summaries.

This module fixes the class of bug, not just the instance:

  * Model names live in ONE place and are lists, not strings.
  * A dead model is skipped and the next is tried; the first that works is
    cached for the process.
  * `gemini-flash-latest` is preferred precisely because it is a moving alias
    that survives deprecations.
  * `health()` reports what actually works, so `jar doctor` can surface a dead
    AI layer instead of hiding it.
  * `last_error()` keeps the real reason available for diagnostics.
"""

import json
import re
import threading
import warnings

from jarvis.config import (
    AI_PRIMARY,
    GEMINI_API_KEY,
    GEMINI_MODELS,
    GROQ_API_KEY,
    GROQ_MODELS,
    WHISPER_MODEL,
)

_lock = threading.Lock()
_working = {"gemini": None, "groq": None}  # cache first model that responds
_last_error = {"gemini": "", "groq": ""}

GEMINI_TIMEOUT = 45
GROQ_TIMEOUT = 60

# Errors that mean "this model will never work" — skip to the next candidate
# immediately instead of burning the timeout budget on it.
_FATAL_MODEL_ERRORS = ("not found", "404", "no longer available",
                       "does not exist", "not supported", "invalid model",
                       "permission", "unauthorized", "401", "403")


def _is_fatal(message):
    lowered = str(message).lower()
    return any(token in lowered for token in _FATAL_MODEL_ERRORS)


def last_error():
    return dict(_last_error)


def reset_cache():
    with _lock:
        _working["gemini"] = None
        _working["groq"] = None


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
def _gemini_client():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    return genai


def _try_gemini(prompt, max_tokens, temperature):
    if not GEMINI_API_KEY:
        return None
    try:
        genai = _gemini_client()
    except Exception as exc:
        _last_error["gemini"] = f"sdk: {exc}"
        return None

    candidates = ([_working["gemini"]] if _working["gemini"]
                  else list(GEMINI_MODELS))
    for model_name in candidates:
        try:
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(
                prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
                # Hard bound: without this the SDK retries a dead model with
                # exponential backoff and a 404 costs minutes instead of ms.
                request_options={"timeout": GEMINI_TIMEOUT},
            )
            text = (getattr(resp, "text", "") or "").strip()
            if text:
                with _lock:
                    _working["gemini"] = model_name
                return text
            _last_error["gemini"] = f"{model_name}: empty response"
        except Exception as exc:
            _last_error["gemini"] = f"{model_name}: {str(exc)[:160]}"
            # A cached model that just died — clear it and retry the full list.
            if _working["gemini"] == model_name:
                with _lock:
                    _working["gemini"] = None
                return _try_gemini(prompt, max_tokens, temperature)
            # Non-fatal (rate limit, transient): stop here rather than hammering
            # every remaining model with the same doomed request.
            if not _is_fatal(exc):
                break
    return None


def _try_groq(prompt, max_tokens, temperature):
    if not GROQ_API_KEY:
        return None
    import httpx

    candidates = ([_working["groq"]] if _working["groq"] else list(GROQ_MODELS))
    for model_name in candidates:
        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=GROQ_TIMEOUT,
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"].strip()
                if text:
                    with _lock:
                        _working["groq"] = model_name
                    return text
                _last_error["groq"] = f"{model_name}: empty response"
            else:
                _last_error["groq"] = f"{model_name}: HTTP {resp.status_code} {resp.text[:120]}"
                if _working["groq"] == model_name:
                    with _lock:
                        _working["groq"] = None
                    return _try_groq(prompt, max_tokens, temperature)
                # Rate limit / server error: trying other models won't help.
                if resp.status_code in (429, 500, 502, 503):
                    break
        except Exception as exc:
            _last_error["groq"] = f"{model_name}: {str(exc)[:160]}"
            break  # network-level failure — do not retry every model
    return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def complete(prompt, max_tokens=1200, temperature=0.2, prefer=None):
    """Return model text, or None if every provider/model failed.

    prefer: "groq" to try Groq first (it is faster for short structured jobs).
    """
    primary = (prefer or AI_PRIMARY or "groq").lower()
    order = ["groq", "gemini"] if primary == "groq" else ["gemini", "groq"]
    for provider in order:
        fn = _try_gemini if provider == "gemini" else _try_groq
        result = fn(prompt, max_tokens, temperature)
        if result:
            return result
    return None


def extract_json(text):
    """Parse JSON out of a model response tolerantly (fences, prose, arrays)."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except Exception:
                continue
    return None


def complete_json(prompt, max_tokens=1200, temperature=0.1, prefer=None):
    """complete() + tolerant JSON parsing. Returns parsed object or None."""
    return extract_json(complete(prompt, max_tokens, temperature, prefer=prefer))


def transcribe(audio_path):
    """Transcribe audio via Groq Whisper (free tier). Returns text or None."""
    if not GROQ_API_KEY:
        return None
    import httpx

    try:
        with open(audio_path, "rb") as handle:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (str(audio_path), handle, "application/octet-stream")},
                data={"model": WHISPER_MODEL, "response_format": "json"},
                timeout=120.0,
            )
        if resp.status_code == 200:
            return (resp.json().get("text") or "").strip()
        _last_error["groq"] = f"whisper: HTTP {resp.status_code} {resp.text[:120]}"
    except Exception as exc:
        _last_error["groq"] = f"whisper: {str(exc)[:160]}"
    return None


def health():
    """Probe each provider with a trivial prompt. Used by `jar doctor`."""
    report = {}
    probe = "Reply with the single word: OK"

    if not GEMINI_API_KEY:
        report["gemini"] = {"ok": False, "model": None, "error": "no API key"}
    else:
        text = _try_gemini(probe, 16, 0.0)
        report["gemini"] = {
            "ok": bool(text),
            "model": _working["gemini"],
            "error": "" if text else _last_error["gemini"],
        }

    if not GROQ_API_KEY:
        report["groq"] = {"ok": False, "model": None, "error": "no API key"}
    else:
        text = _try_groq(probe, 16, 0.0)
        report["groq"] = {
            "ok": bool(text),
            "model": _working["groq"],
            "error": "" if text else _last_error["groq"],
        }

    report["any"] = report["gemini"]["ok"] or report["groq"]["ok"]
    return report
