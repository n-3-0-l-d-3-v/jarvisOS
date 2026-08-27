"""Feature 15: retrieval layer — jar search + jar ask."""

import pytest

from jarvis import retrieval as R


@pytest.fixture
def seeded_repo(sandbox, write_index):
    """Write real note files + index rows into the sandbox."""
    notes = [
        ("08-databases/redis", "redis-persistence.md", "Redis Persistence",
         "Redis persists data using RDB snapshots and AOF append-only logs.",
         ["redis", "persistence"], "databases"),
        ("04-dsa/sliding-window", "lc-76.md", "Minimum Window Substring",
         "Use a sliding window: expand right, shrink left until valid.",
         ["sliding-window", "strings"], "dsa"),
        ("05-frontend/react", "useeffect.md", "React useEffect",
         "The cleanup function runs before the next effect and on unmount.",
         ["react", "hooks"], "frontend"),
    ]
    for folder, fn, title, body, tags, domain in notes:
        p = sandbox / folder
        p.mkdir(parents=True, exist_ok=True)
        (p / fn).write_text(
            f"---\ntitle: {title}\n---\n# {title}\n\n{body}\n"
            "## Related Topics\n<!-- placeholder -->\n", encoding="utf-8")
    write_index([
        {"id": str(i), "title": t, "folder_path": f, "filename": fn,
         "tags": tags, "domain": d, "subdomain": f.split("/")[-1], "type": "concept"}
        for i, (f, fn, t, b, tags, d) in enumerate(notes)
    ])
    return sandbox


# --- search ----------------------------------------------------------------
def test_search_finds_by_body_content(seeded_repo):
    results = R.search_notes("append only logs")
    assert results
    assert results[0]["filename"] == "redis-persistence.md"


def test_search_matches_title_and_tags(seeded_repo):
    results = R.search_notes("sliding window")
    assert results[0]["title"] == "Minimum Window Substring"


def test_search_ranks_by_relevance(seeded_repo):
    results = R.search_notes("redis persistence rdb")
    assert results[0]["filename"] == "redis-persistence.md"
    assert results[0]["score"] >= results[-1]["score"]


def test_search_returns_snippet(seeded_repo):
    results = R.search_notes("cleanup function unmount")
    assert "cleanup" in results[0]["snippet"].lower()


def test_search_ignores_stopwords_only_query(seeded_repo):
    assert R.search_notes("the and of to") == []


def test_search_empty_query_returns_nothing(seeded_repo):
    assert R.search_notes("") == []


def test_search_no_match_returns_empty(seeded_repo):
    assert R.search_notes("kubernetes helm charts xyz") == []


def test_search_dedupes_a_corrupted_index(sandbox, write_index):
    """Even if the index has duplicate rows for one file, search returns it once."""
    folder = sandbox / "08-databases/redis"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "redis.md").write_text("# Redis\nredis persistence data", encoding="utf-8")
    row = {"id": "1", "title": "Redis", "folder_path": "08-databases/redis",
           "filename": "redis.md", "tags": ["redis"], "domain": "databases"}
    write_index([row, dict(row), dict(row)])  # 3 identical rows
    results = R.search_notes("redis persistence")
    assert len([r for r in results if r["filename"] == "redis.md"]) == 1


def test_search_limit_is_respected(seeded_repo):
    assert len(R.search_notes("redis sliding react data window persist", limit=2)) <= 2


# --- ask -------------------------------------------------------------------
def test_ask_uses_ai_and_cites_sources(seeded_repo, monkeypatch):
    monkeypatch.setattr(R, "_ai_complete",
                        lambda prompt: "RDB snapshots and AOF logs.\nSources: Redis Persistence",
                        raising=False)
    result = R.ask("how does redis persist data")
    assert result["used_ai"] is True
    assert "AOF" in result["answer"]
    assert result["sources"]
    assert result["sources"][0]["filename"] == "redis-persistence.md"


def test_ask_degrades_to_search_without_ai(seeded_repo, monkeypatch):
    monkeypatch.setattr(R, "_ai_complete", lambda prompt: None, raising=False)
    result = R.ask("redis persistence")
    assert result["used_ai"] is False
    assert "Redis Persistence" in result["answer"]
    assert result["sources"]


def test_ask_handles_no_relevant_notes(seeded_repo, monkeypatch):
    monkeypatch.setattr(R, "_ai_complete", lambda prompt: "x", raising=False)
    result = R.ask("quantum blockchain kubernetes xyz")
    assert result["sources"] == []
    assert result["used_ai"] is False


def test_ask_prompt_only_includes_found_notes(seeded_repo, monkeypatch):
    captured = {}

    def fake(prompt):
        captured["prompt"] = prompt
        return "answer"

    monkeypatch.setattr(R, "_ai_complete", fake, raising=False)
    R.ask("react useEffect cleanup")
    assert "useEffect" in captured["prompt"]
    assert "sliding window" not in captured["prompt"].lower()


def test_ai_complete_delegates_to_central_client(monkeypatch):
    """Retrieval must go through jarvis.ai so model fallback applies."""
    import jarvis.ai as AI
    monkeypatch.setattr(AI, "complete",
                        lambda prompt, max_tokens=1200, temperature=0.2, prefer=None:
                        "central answer",
                        raising=False)
    assert R._ai_complete("q") == "central answer"


def test_ai_client_falls_back_between_providers(monkeypatch):
    """The provider ladder itself: a dead primary must fall through."""
    import jarvis.ai as AI
    monkeypatch.setattr(AI, "_try_groq", lambda p, m, t: None, raising=False)
    monkeypatch.setattr(AI, "_try_gemini", lambda p, m, t: "gemini answer", raising=False)
    assert AI.complete("q", prefer="groq") == "gemini answer"


def test_ai_client_returns_none_when_all_models_fail(monkeypatch):
    import jarvis.ai as AI
    monkeypatch.setattr(AI, "_try_groq", lambda p, m, t: None, raising=False)
    monkeypatch.setattr(AI, "_try_gemini", lambda p, m, t: None, raising=False)
    assert AI.complete("q") is None
