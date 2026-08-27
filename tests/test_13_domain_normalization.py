"""
Feature 13: defensive domain normalisation.

Regression for real corruption found in the live index.json, where the AI
echoed prompt scaffolding into the value ("primary domain: open-source").
"""

import json

import pytest

from jarvis.classifier import normalize_domain
from jarvis.index_cleaner import fix_domains


@pytest.mark.parametrize("raw,expected", [
    ("primary domain: open-source", "open-source"),
    ("primary domain: career", "career"),
    ("Primary Domain: Backend", "backend"),
    ("domain: devops", "devops"),
    ("dsa|frontend|backend", "dsa"),
    ("  backend  ", "backend"),
    ('"databases"', "databases"),
    ("ai-ml", "ai-ml"),
])
def test_normalize_domain_cleans_llm_artifacts(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("empty", ["", None, "   "])
def test_normalize_domain_falls_back_on_empty(empty):
    assert normalize_domain(empty) == "knowledge-base"


def test_normalize_domain_honours_custom_default():
    assert normalize_domain("", "creator-content") == "creator-content"


def test_normalize_domain_leaves_clean_values_untouched():
    for good in ("dsa", "frontend", "system-design", "open-source"):
        assert normalize_domain(good) == good


def test_fix_domains_repairs_index(write_index):
    index_path = write_index([
        {"id": "1", "title": "A", "domain": "primary domain: open-source"},
        {"id": "2", "title": "B", "domain": "backend"},
        {"id": "3", "title": "C", "domain": "primary domain: career"},
    ])
    result = fix_domains()
    assert result["fixed"] == 2

    notes = json.loads(index_path.read_text(encoding="utf-8"))["notes"]
    domains = [n["domain"] for n in notes]
    assert domains == ["open-source", "backend", "career"]


def test_fix_domains_is_noop_when_clean(write_index):
    write_index([{"id": "1", "title": "A", "domain": "backend"}])
    assert fix_domains()["fixed"] == 0


def test_agents_normalize_domain_on_parse(monkeypatch):
    """The article agent must scrub domain AND subdomain before indexing."""
    import jarvis.ai as AI
    import jarvis.article_fetcher as A

    monkeypatch.setattr(A, "GROQ_API_KEY", "fake-key", raising=False)
    monkeypatch.setattr(
        AI, "complete_json",
        lambda prompt, max_tokens=1200, temperature=0.1, prefer=None: {
            "domain": "primary domain: open-source",
            "subdomain": "specific technology: git",
            "type": "article", "title": "T", "tags": [],
            "folder_path": "20-open-source", "complexity": "beginner",
            "tldr": "", "key_points": [], "technologies": [],
            "practical_value": "", "confidence": 0.9},
        raising=False)

    result = A.classify_article_with_ai(
        "https://ex.com", "content", {"site": "ex.com", "title": "T"})
    assert result["domain"] == "open-source"
    assert result["subdomain"] == "git"


def test_subdomain_normalization_repairs_index(write_index):
    """jar index-clean --fix-domains must also repair leaked subdomains."""
    index_path = write_index([
        {"id": "1", "title": "A", "domain": "databases",
         "subdomain": "specific technology: redis"},
        {"id": "2", "title": "B", "domain": "dsa", "subdomain": "arrays"},
    ])
    result = fix_domains()
    assert result["fixed"] == 1
    notes = json.loads(index_path.read_text(encoding="utf-8"))["notes"]
    assert [n["subdomain"] for n in notes] == ["redis", "arrays"]
