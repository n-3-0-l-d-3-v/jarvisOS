"""Feature 7: YouTube / article / LeetCode / DSA agents (deterministic parts)."""

import pytest

from jarvis import article_fetcher as A
from jarvis import dsa_agent as DA
from jarvis import youtube_agent as Y
from jarvis.leetcode_fetcher import extract_lc_number

TS = "2026-07-22T12:00:00"


# --- YouTube ---------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&t=30s",
])
def test_extract_video_id_handles_every_url_format(url):
    assert Y.extract_video_id(url) == "dQw4w9WgXcQ"


def test_extract_video_id_returns_none_for_non_youtube():
    assert Y.extract_video_id("https://example.com/page") is None


@pytest.mark.parametrize("channel,expected", [
    ("Fireship", "fireship"),
    ("ThePrimeagen", "primeagen"),
    ("ByteByteGo", "bytebytego"),
    ("NeetCode", "neetcode"),
])
def test_detect_creator_maps_known_channels(channel, expected):
    assert Y.detect_creator(channel) == expected


def test_detect_creator_slugifies_unknown_channel():
    assert Y.detect_creator("Some Random Dev.Channel") == "some-random-devchannel"


def test_build_video_note_has_required_sections():
    meta = {"video_id": "x", "title": "Test Video", "channel": "Fireship",
            "description": "d", "published_at": "2026-01-01", "tags": [],
            "duration": "PT5M", "view_count": "100",
            "url": "https://youtu.be/x", "thumbnail": ""}
    summary = {"tldr": "short", "domain": "devops", "topics": ["docker"],
               "technologies": ["docker"], "difficulty": "intermediate",
               "tags": ["docker"], "action_items": ["try it"],
               "key_concepts": [{"concept": "Layers", "explanation": "e"}]}
    note = Y.build_video_note(meta, "transcript text", summary, TS)
    for section in ("## Channel", "## Video Link", "## TLDR", "## Key Concepts",
                    "## Technologies Mentioned", "## Action Items"):
        assert section in note, f"missing {section}"
    assert note.startswith("---") and "type: video-summary" in note


def test_build_video_note_survives_missing_summary():
    meta = {"video_id": "x", "title": "T", "channel": "C", "description": "",
            "published_at": "", "tags": [], "duration": "", "view_count": "",
            "url": "u", "thumbnail": ""}
    assert "# T" in Y.build_video_note(meta, None, None, TS)


# --- Article ---------------------------------------------------------------
def test_article_metadata_from_h1_and_url():
    meta = A.extract_article_metadata(
        "https://blog.example.com/deep-dive", "# Real Title\n\nsome body words")
    assert meta["title"] == "Real Title"
    assert meta["site"] == "blog.example.com"
    assert "min read" in meta["estimated_read_time"]


def test_article_metadata_falls_back_to_url_slug():
    meta = A.extract_article_metadata(
        "https://ex.com/my-cool-post", "no heading here")
    assert "Cool" in meta["title"]


def test_article_extract_json_handles_fences():
    assert A.extract_json('```json\n{"domain":"backend"}\n```')["domain"] == "backend"


def test_build_article_note_sections():
    meta = {"url": "u", "title": "T", "site": "ex.com",
            "estimated_read_time": "3 min read"}
    cls = {"title": "T", "domain": "backend", "subdomain": "redis",
           "tags": ["redis"], "complexity": "intermediate", "tldr": "sum",
           "key_points": ["a", "b"], "technologies": ["redis"],
           "practical_value": "use it", "confidence": 0.9}
    note = A.build_article_note("https://ex.com/x", "content", meta, cls, TS)
    for section in ("## Source", "## TLDR", "## Key Points",
                    "## Technologies Mentioned", "## How I Can Apply This"):
        assert section in note
    assert "type: article" in note


# --- LeetCode --------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("LC-76 minimum window", 76),
    ("LC1 two sum", 1),
    ("leetcode 239 sliding window max", 239),
    ("42. Trapping Rain Water", 42),
    ("no number here", None),
])
def test_extract_lc_number(text, expected):
    assert extract_lc_number(text) == expected


# --- DSA agent -------------------------------------------------------------
def test_build_dsa_note_with_enrichment_has_all_sections():
    cls = {"title": "Two Sum", "tags": ["arrays"], "dsa_pattern": "arrays"}
    enriched = {"problem_number": "LC-1", "problem_name": "Two Sum",
                "pattern": "arrays", "approach": "hashmap",
                "time_complexity": "O(n)", "space_complexity": "O(n)",
                "key_insight": "complement lookup", "edge_cases": ["dupes"],
                "similar_problems": ["3Sum"], "difficulty": "Easy",
                "companies": ["Google"], "mistakes_to_avoid": "off by one"}
    lc = {"problem_summary": "Given an array...", "url": "https://lc.com/two-sum"}
    note = DA.build_dsa_note("my notes", cls, enriched, TS, lc)
    for section in ("## Pattern", "## Problem Statement", "## LeetCode Link",
                    "## Difficulty", "## Approach", "## Key Insight",
                    "## Complexity", "## Edge Cases", "## Similar Problems",
                    "## Companies"):
        assert section in note, f"missing {section}"
    assert "O(n)" in note and "Google" in note
    assert 'problem_number: "LC-1"' in note


def test_build_dsa_note_falls_back_to_plain_template():
    cls = {"title": "T", "tags": [], "dsa_pattern": "arrays", "type": "dsa"}
    note = DA.build_dsa_note("body", cls, None, TS, None)
    assert "## Problem Summary" in note  # plain format_dsa template


def test_dsa_agent_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(DA, "GROQ_API_KEY", "", raising=False)
    assert DA.analyze_dsa_note("LC-1 two sum", {"dsa_pattern": "arrays"}) is None
