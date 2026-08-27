"""Feature 2: the 3-tier classifier and its helper functions (offline paths)."""

import pytest

from jarvis import classifier as C


# --- JSON extraction -------------------------------------------------------
def test_clean_json_response_strips_fences():
    assert C.clean_json_response('```json\n{"a": 1}\n```').strip().startswith("{")


@pytest.mark.parametrize("raw", [
    '{"domain": "dsa"}',
    '```json\n{"domain": "dsa"}\n```',
    '```\n{"domain": "dsa"}\n```',
    'Here you go:\n{"domain": "dsa"}\nhope that helps',
])
def test_extract_json_handles_all_ai_response_shapes(raw):
    parsed = C.extract_json(raw)
    assert parsed is not None, f"failed to parse: {raw!r}"
    assert parsed["domain"] == "dsa"


def test_extract_json_returns_none_on_garbage():
    assert C.extract_json("not json at all") is None


# --- folder path validation ------------------------------------------------
def test_validate_folder_path_corrects_wrong_prefix():
    # A wrong numeric prefix on a known domain should be corrected.
    corrected = C.validate_folder_path("99-dsa/arrays")
    assert corrected.startswith("04-dsa"), corrected


def test_validate_folder_path_keeps_correct_prefix():
    assert C.validate_folder_path("04-dsa/arrays") == "04-dsa/arrays"


# --- DSA pattern detection -------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("used a sliding window to find the longest substring", "sliding-window"),
    ("two pointers from both ends of the sorted array", "two-pointers"),
    ("binary search on the rotated sorted array", "binary-search"),
    ("solved with dynamic programming and memoization", "dynamic-programming"),
    ("backtracking to generate all permutations", "backtracking"),
])
def test_detect_dsa_pattern(text, expected):
    assert C.detect_dsa_pattern(text) == expected


def test_detect_dsa_pattern_returns_empty_for_non_dsa():
    assert C.detect_dsa_pattern("react useEffect cleanup function") in ("", None)


# --- note type pre-detection ----------------------------------------------
@pytest.mark.parametrize("text,source,expected", [
    ("LC-76 minimum window substring sliding window", "cli", "dsa"),
    ("fixed a TypeError: cannot read property of undefined", "cli", "bug"),
    ("https://youtube.com/watch?v=abc", "youtube", "video-summary"),
])
def test_detect_note_type(text, source, expected):
    assert C.detect_note_type(text, source) == expected


# --- offline keyword classifier (last-resort tier, must never fail) --------
def test_keyword_classifier_returns_complete_classification():
    result = C.classify_with_keywords(
        "docker compose networking between containers", "cli", "", "", ""
    )
    for field in ("domain", "subdomain", "folder_path", "title", "tags", "type"):
        assert field in result, f"missing {field}"
    assert result["folder_path"]


def test_keyword_classifier_routes_dsa():
    result = C.classify_with_keywords(
        "LC-1 two sum using a hashmap", "leetcode", "", "dsa", "arrays"
    )
    assert result["type"] == "dsa"
    assert "04-dsa" in result["folder_path"]


def test_keyword_classifier_never_raises_on_empty():
    # The last-resort tier must never crash, whatever it is handed.
    result = C.classify_with_keywords("", "cli", "", "", "")
    assert isinstance(result, dict) and result.get("folder_path")


def test_classify_note_falls_back_without_api_keys(monkeypatch):
    """With both AI tiers disabled, classify_note must still return a note."""
    monkeypatch.setattr(C, "GEMINI_API_KEY", "", raising=False)
    monkeypatch.setattr(C, "GROQ_API_KEY", "", raising=False)
    monkeypatch.setattr(C, "genai", None, raising=False)
    monkeypatch.setattr(C, "classify_with_groq",
                        lambda *a, **k: None, raising=False)

    result = C.classify_note("redis persistence rdb vs aof", "cli", "")
    assert isinstance(result, dict)
    assert result.get("folder_path")
    assert result.get("title")
