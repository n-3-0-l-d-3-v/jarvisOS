"""Feature 9: the FastAPI dashboard, capture API and bookmarklet (Task 3.4)."""

import datetime

import pytest
from fastapi.testclient import TestClient

from jarvis import api_server as S

client = TestClient(S.app)
TODAY = datetime.date.today().isoformat()

SEED = [
    {"id": "1", "title": "Two Sum", "type": "dsa", "domain": "dsa",
     "date": TODAY, "source": "leetcode", "folder_path": "04-dsa",
     "filename": "lc-1-two-sum.md"},
    {"id": "2", "title": "Docker Layers", "type": "video-summary",
     "domain": "devops", "date": "2026-01-01", "source": "youtube",
     "folder_path": "21-creators", "filename": "docker.md"},
    {"id": "3", "title": "Redis Guide", "type": "article", "domain": "databases",
     "date": TODAY, "source": "article", "folder_path": "08-databases",
     "filename": "redis.md"},
    {"id": "4", "title": "CSS Grid", "type": "concept", "domain": "frontend",
     "date": "2026-02-02", "source": "cli", "folder_path": "05-frontend",
     "filename": "css.md"},
]


# --- read endpoints --------------------------------------------------------
def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "online"
    assert body["version"] == S.VERSION
    assert body["repo"]


def test_status(write_index):
    write_index(SEED)
    body = client.get("/status").json()
    assert body["total_notes"] == 4
    assert body["today"] == 2


def test_api_stats_counts_every_type(write_index):
    write_index(SEED)
    s = client.get("/api/stats").json()
    assert s["total_notes"] == 4
    assert s["today"] == 2
    assert s["dsa"] == 1
    assert s["videos"] == 1
    assert s["articles"] == 1
    assert {d["domain"] for d in s["domains"]} == {
        "dsa", "devops", "databases", "frontend"}
    assert len(s["recent"]) == 4


def test_stats_handles_empty_index(clean_index):
    s = client.get("/api/stats").json()
    assert s["total_notes"] == 0 and s["domains"] == [] and s["recent"] == []


def test_recent_is_newest_first(write_index):
    write_index(SEED)
    recent = client.get("/api/stats").json()["recent"]
    assert recent[0]["title"] == "CSS Grid"  # last appended shows first


# --- dashboard -------------------------------------------------------------
def test_dashboard_renders(write_index):
    write_index(SEED)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    assert "Jarvis" in html and "Save to Jarvis" in html
    assert "Two Sum" in html          # recent captures table
    assert "Domain Breakdown" in html


def test_root_serves_dashboard(write_index):
    write_index(SEED)
    assert client.get("/").status_code == 200


def test_dashboard_has_no_unreplaced_tokens(write_index):
    write_index(SEED)
    html = client.get("/dashboard").text
    for token in ("__CARDS__", "__DOMAIN_ROWS__", "__RECENT_ROWS__",
                  "__BOOKMARKLET_HREF__", "__REPO__", "__VERSION__",
                  "__API_BASE__"):
        assert token not in html, f"unreplaced token {token}"


def test_dashboard_escapes_html_in_titles(write_index):
    write_index([{"id": "x", "title": "<script>alert(1)</script>",
                  "type": "concept", "domain": "web", "date": TODAY,
                  "source": "cli", "folder_path": "f", "filename": "n.md"}])
    html = client.get("/dashboard").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# --- bookmarklet -----------------------------------------------------------
def test_bookmarklet_is_valid_javascript_uri():
    href = S._build_bookmarklet("http://localhost:7823")
    assert href.startswith("javascript:")
    from urllib.parse import unquote
    js = unquote(href[len("javascript:"):])
    assert js.count("(") == js.count(")")
    assert js.count("{") == js.count("}")
    assert "fetch(" in js
    assert "http://localhost:7823" in js
    assert "/capture/youtube" in js and "/capture/article" in js


def test_bookmarklet_detects_youtube_and_handles_offline():
    from urllib.parse import unquote
    js = unquote(S._build_bookmarklet("http://x")[len("javascript:"):])
    assert "youtube" in js.lower()
    assert "jar serve" in js  # offline hint shown to the user


# --- capture endpoint validation ------------------------------------------
@pytest.mark.parametrize("path,payload", [
    ("/capture/note", {"text": "   "}),
    ("/capture/article", {"url": ""}),
    ("/capture/youtube", {"url": ""}),
])
def test_capture_rejects_empty_input(path, payload):
    r = client.post(path, json=payload)
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_capture_note_success_path(monkeypatch):
    import jarvis.capture as cap
    import jarvis.orchestrator as orch
    monkeypatch.setattr(cap, "capture_note", lambda *a, **k: "p", raising=False)
    monkeypatch.setattr(orch, "process_inbox_orchestrated",
                        lambda force=False: {
                            "processed": 1, "failed": 0,
                            "results": [{"success": True,
                                         "classification": {"title": "Saved Note"}}]},
                        raising=False)
    body = client.post("/capture/note", json={"text": "hello"}).json()
    assert body["ok"] is True and body["title"] == "Saved Note"


def test_capture_article_success_path(monkeypatch):
    import jarvis.article_fetcher as AF
    import jarvis.git_sync as GS
    monkeypatch.setattr(AF, "process_article_url",
                        lambda url, note, ts: {"title": "An Article",
                                               "site": "ex.com",
                                               "folder_path": "22-knowledge-base",
                                               "filename": "a.md"},
                        raising=False)
    monkeypatch.setattr(GS, "sync", lambda msg: {"synced": False}, raising=False)
    body = client.post("/capture/article",
                       json={"url": "https://ex.com/a"}).json()
    assert body["ok"] is True and body["title"] == "An Article"


def test_capture_article_reports_fetch_failure(monkeypatch):
    import jarvis.article_fetcher as AF
    monkeypatch.setattr(AF, "process_article_url",
                        lambda *a, **k: None, raising=False)
    r = client.post("/capture/article", json={"url": "https://bad.example"})
    assert r.status_code == 502 and r.json()["ok"] is False


def test_capture_youtube_success_path(monkeypatch):
    import jarvis.git_sync as GS
    import jarvis.youtube_agent as YA
    monkeypatch.setattr(YA, "process_youtube_url",
                        lambda url, ts: {"title": "A Video", "channel": "Fireship",
                                         "folder_path": "21-creators",
                                         "filename": "v.md"},
                        raising=False)
    monkeypatch.setattr(GS, "sync", lambda msg: {"synced": False}, raising=False)
    body = client.post("/capture/youtube",
                       json={"url": "https://youtu.be/x"}).json()
    assert body["ok"] is True and body["channel"] == "Fireship"


# --- retrieval endpoints ---------------------------------------------------
def test_api_search_endpoint(monkeypatch):
    import jarvis.retrieval as RT
    monkeypatch.setattr(RT, "search_notes",
                        lambda q, limit=10: [{"title": "Hit", "score": 5,
                                              "folder_path": "f", "filename": "n.md",
                                              "domain": "d", "path": "p",
                                              "snippet": "..."}],
                        raising=False)
    body = client.get("/api/search", params={"q": "redis"}).json()
    assert body["query"] == "redis"
    assert body["results"][0]["title"] == "Hit"


def test_api_ask_endpoint(monkeypatch):
    import jarvis.retrieval as RT
    monkeypatch.setattr(RT, "ask",
                        lambda question, k=8: {"answer": "because X",
                                               "sources": [], "used_ai": True},
                        raising=False)
    body = client.post("/api/ask", json={"question": "why X?"}).json()
    assert body["ok"] is True and body["answer"] == "because X"


def test_api_ask_rejects_empty():
    r = client.post("/api/ask", json={"question": "  "})
    assert r.status_code == 400


# --- CORS (bookmarklet runs cross-origin) ---------------------------------
def test_cors_allows_cross_origin_capture():
    r = client.options("/capture/note", headers={
        "Origin": "https://www.youtube.com",
        "Access-Control-Request-Method": "POST"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"
