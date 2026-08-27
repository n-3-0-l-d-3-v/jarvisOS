"""Feature 20: wiki synthesis, MCP server, and knowledge-graph data."""

import json

import pytest

from jarvis import graph_view as GV
from jarvis import wiki as W

NOTE_TMPL = ("---\ntitle: {title}\ndomain: {domain}\ntype: concept\n---\n"
             "# {title}\n\n{body}\n\n## Related Topics\n<!-- ph -->\n")


@pytest.fixture
def seeded(pristine_repo, write_index, monkeypatch):
    """Real note files + index rows, with wiki output redirected to sandbox.

    Uses pristine_repo so repo-wide assertions (page counts, node counts) are
    not skewed by notes other tests wrote into the shared sandbox.
    """
    import shutil

    sandbox = pristine_repo
    shutil.rmtree(sandbox / "wiki", ignore_errors=True)
    monkeypatch.setattr(W, "WIKI_DIR", sandbox / "wiki", raising=False)
    monkeypatch.setattr(W, "TOPICS_DIR", sandbox / "wiki" / "topics", raising=False)
    monkeypatch.setattr(W, "WIKI_LOG", sandbox / "wiki" / "log.md", raising=False)
    monkeypatch.setattr(W, "WIKI_INDEX", sandbox / "wiki" / "index.md", raising=False)

    specs = [
        ("08-databases/redis", "redis-a.md", "Redis RDB", "databases", "redis",
         ["redis"], "Redis RDB snapshots the dataset periodically."),
        ("08-databases/redis", "redis-b.md", "Redis AOF", "databases", "redis",
         ["redis"], "Redis AOF logs every write operation to disk."),
        ("08-databases/redis", "redis-c.md", "Redis TTL", "databases", "redis",
         ["redis"], "EXPIRE sets a time to live on a key."),
        ("04-dsa/arrays", "two-sum.md", "Two Sum", "dsa", "arrays",
         ["arrays"], "Use a hashmap to find the complement in one pass."),
    ]
    rows = []
    for i, (folder, fn, title, domain, sub, tags, body) in enumerate(specs):
        p = sandbox / folder
        p.mkdir(parents=True, exist_ok=True)
        (p / fn).write_text(
            NOTE_TMPL.format(title=title, domain=domain, body=body), encoding="utf-8")
        rows.append({"id": f"note{i}", "title": title, "folder_path": folder,
                     "filename": fn, "domain": domain, "subdomain": sub,
                     "tags": tags, "type": "concept", "date": "2026-01-01"})
    write_index(rows)
    return sandbox


# --- cluster discovery -----------------------------------------------------
def test_suggest_topics_finds_subdomain_clusters(seeded):
    topics = {c["topic"]: c for c in W.suggest_topics(min_size=2)}
    assert "redis" in topics
    assert topics["redis"]["count"] == 3
    assert topics["redis"]["basis"] == "subdomain"


def test_singleton_is_not_suggested(seeded):
    assert "arrays" not in {c["topic"] for c in W.suggest_topics(min_size=2)}


def test_find_cluster_by_subdomain(seeded):
    assert len(W.find_cluster("redis")) == 3


def test_find_cluster_falls_back_to_search(seeded):
    """An arbitrary phrase should still gather relevant notes."""
    assert W.find_cluster("hashmap complement")


def test_find_cluster_unknown_topic_is_empty(seeded):
    assert W.find_cluster("kubernetes helm xyz") == []


# --- synthesis -------------------------------------------------------------
def test_synthesis_writes_page_with_ai(seeded, monkeypatch):
    monkeypatch.setattr(W, "_ai",
                        lambda p: "# Redis\n\nMerged summary.\n\n## Persistence\nRDB and AOF.",
                        raising=False)
    result = W.synthesize_topic("redis")
    assert result["used_ai"] is True
    assert result["count"] == 3

    content = (seeded / "wiki" / "topics" / "redis.md").read_text(encoding="utf-8")
    assert content.startswith("---")
    assert "type: wiki" in content
    assert "source_count: 3" in content
    assert "## Persistence" in content
    assert "## Sources" in content
    assert "[[redis-a|Redis RDB]]" in content


def test_synthesis_falls_back_without_ai(seeded, monkeypatch):
    monkeypatch.setattr(W, "_ai", lambda p: None, raising=False)
    result = W.synthesize_topic("redis")
    assert result["used_ai"] is False
    assert result["count"] == 3
    # Fallback still preserves every source's content.
    assert "RDB snapshots" in result["content"]
    assert "AOF logs every write" in result["content"]


def test_synthesis_never_modifies_raw_notes(seeded, monkeypatch):
    original = (seeded / "08-databases/redis/redis-a.md").read_text(encoding="utf-8")
    monkeypatch.setattr(W, "_ai", lambda p: "# Redis\n\nrewritten", raising=False)
    W.synthesize_topic("redis")
    assert (seeded / "08-databases/redis/redis-a.md").read_text(encoding="utf-8") == original


def test_synthesis_indexes_the_wiki_page(seeded, monkeypatch):
    """The wiki page must itself be indexed so search/ask can surface it."""
    monkeypatch.setattr(W, "_ai", lambda p: "# Redis\n\nsummary", raising=False)
    W.synthesize_topic("redis")
    from jarvis.index_store import load_index

    wiki_rows = [n for n in load_index()["notes"] if n.get("type") == "wiki"]
    assert wiki_rows and wiki_rows[0]["folder_path"] == "wiki/topics"


def test_synthesis_of_unknown_topic_is_safe(seeded):
    result = W.synthesize_topic("nonexistent-topic-xyz")
    assert result["count"] == 0 and result["path"] == ""


def test_dry_run_writes_nothing(seeded):
    W.synthesize_topic("redis", dry_run=True)
    assert not (seeded / "wiki" / "topics" / "redis.md").exists()


def test_build_index_lists_pages(seeded, monkeypatch):
    monkeypatch.setattr(W, "_ai", lambda p: "# Redis\n\nsummary", raising=False)
    W.synthesize_topic("redis")
    result = W.build_index()
    assert result["pages"] == 1
    assert "Redis" in (seeded / "wiki" / "index.md").read_text(encoding="utf-8")


# --- knowledge graph -------------------------------------------------------
def test_graph_has_nodes_and_edges(seeded):
    graph = GV.build_graph()
    assert graph["stats"]["node_count"] == 4
    assert graph["stats"]["edge_count"] >= 1


def test_graph_nodes_carry_display_fields(seeded):
    node = GV.build_graph()["nodes"][0]
    for field in ("id", "title", "domain", "colour", "degree", "path"):
        assert field in node


def test_graph_edges_reference_valid_nodes(seeded):
    graph = GV.build_graph()
    count = len(graph["nodes"])
    for edge in graph["edges"]:
        assert 0 <= edge["source"] < count
        assert 0 <= edge["target"] < count
        assert edge["source"] != edge["target"]


def test_graph_has_no_duplicate_edges(seeded):
    edges = GV.build_graph()["edges"]
    pairs = {(e["source"], e["target"]) for e in edges}
    assert len(pairs) == len(edges)


def test_graph_domain_filter(seeded):
    graph = GV.build_graph(domain="dsa")
    assert {n["domain"] for n in graph["nodes"]} == {"dsa"}


def test_graph_respects_max_nodes(seeded):
    assert len(GV.build_graph(max_nodes=2)["nodes"]) == 2


def test_graph_colours_are_stable_per_domain(seeded):
    first = {d["domain"]: d["colour"] for d in GV.build_graph()["domains"]}
    second = {d["domain"]: d["colour"] for d in GV.build_graph()["domains"]}
    assert first == second


def test_graph_handles_empty_index(sandbox, write_index):
    write_index([])
    graph = GV.build_graph()
    assert graph["nodes"] == [] and graph["edges"] == []


# --- MCP server ------------------------------------------------------------
def test_mcp_registers_expected_tools():
    import asyncio

    from jarvis.mcp_server import server

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    for expected in ("search_notes", "read_note", "ask_knowledge_base",
                     "capture_note", "capture_url", "knowledge_stats",
                     "find_related", "knowledge_health", "export_document",
                     "daily_briefing", "suggest_wiki_topics", "synthesize_topic",
                     "find_duplicates", "learning_analytics"):
        assert expected in names, f"MCP tool missing: {expected}"


def test_mcp_duplicate_tool_defaults_to_read_only(seeded):
    """find_duplicates must never delete unless explicitly asked."""
    from jarvis.mcp_server import find_duplicates

    out = find_duplicates()
    assert "dry run" in out.lower() or "no near-duplicate" in out.lower()


def test_mcp_tools_all_have_descriptions():
    """Descriptions are how the client model decides when to call a tool."""
    import asyncio

    from jarvis.mcp_server import server

    for tool in asyncio.run(server.list_tools()):
        assert tool.description and len(tool.description) > 30, tool.name


def test_mcp_quiet_redirects_stdout():
    """stdout belongs to the MCP protocol — library prints must not reach it."""
    import sys

    from jarvis.mcp_server import _quiet

    original = sys.stdout
    with _quiet():
        assert sys.stdout is sys.stderr
    assert sys.stdout is original


def test_mcp_capture_rejects_empty(seeded):
    from jarvis.mcp_server import capture_note

    assert "empty" in capture_note("   ").lower()
