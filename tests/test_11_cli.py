"""Feature 11: every `jar` CLI command is registered and runs."""

import pytest
from click.testing import CliRunner

from jarvis import cli as C

runner = CliRunner()

EXPECTED_COMMANDS = {
    "note", "process", "inbox", "status", "sync", "cleanup", "index-clean",
    "log", "logs", "today", "finalize", "weekly", "schedule",
    "dsa", "lc", "link", "graph", "search", "ask",
    "youtube", "article", "discord", "serve", "rss",
    "push", "doctor", "reindex", "review", "quiz", "export", "open",
}


def test_all_commands_are_registered():
    missing = EXPECTED_COMMANDS - set(C.cli.commands)
    assert not missing, f"missing commands: {sorted(missing)}"


def test_help_exits_cleanly():
    result = runner.invoke(C.cli, ["--help"])
    assert result.exit_code == 0
    assert "Jarvis" in result.output


@pytest.mark.parametrize("name", sorted(EXPECTED_COMMANDS))
def test_every_command_has_working_help(name):
    result = runner.invoke(C.cli, [name, "--help"])
    assert result.exit_code == 0, f"`jar {name} --help` failed: {result.output}"


# --- read-only commands run against the sandbox ---------------------------
def test_status_runs(write_index):
    write_index([{"id": "1", "title": "N", "type": "concept", "domain": "d",
                  "date": "2026-07-22", "folder_path": "f", "filename": "n.md"}])
    result = runner.invoke(C.cli, ["status"])
    assert result.exit_code == 0
    assert "Total notes" in result.output


def test_inbox_reports_empty():
    result = runner.invoke(C.cli, ["inbox"])
    assert result.exit_code == 0


def test_today_handles_missing_log(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "get_log_path",
                        lambda d=None: tmp_path / "nope.md", raising=False)
    result = runner.invoke(C.cli, ["today"])
    assert result.exit_code == 0
    assert "No log for today" in result.output


def test_logs_command_runs():
    assert runner.invoke(C.cli, ["logs"]).exit_code == 0


def test_dsa_command_runs(write_index):
    write_index([{"id": "1", "title": "Two Sum", "type": "dsa", "domain": "dsa",
                  "date": "2026-07-22", "pattern": "arrays",
                  "problem_number": "LC-1", "difficulty": "Easy",
                  "folder_path": "04-dsa", "filename": "lc-1-two-sum.md"}])
    result = runner.invoke(C.cli, ["dsa"])
    assert result.exit_code == 0
    assert "Two Sum" in result.output


def test_graph_handles_no_match(write_index):
    write_index([])
    result = runner.invoke(C.cli, ["graph", "nonexistent-term-xyz"])
    assert result.exit_code == 0
    assert "No notes found" in result.output


# --- mutating commands, with the pipeline stubbed -------------------------
def test_note_command_invokes_pipeline(monkeypatch):
    called = {}

    def fake_capture(text, source, source_url, extra=None):
        called["captured"] = text
        return "inbox/raw/fake.json"

    def fake_process(force=False, push=True):
        called["processed"] = True
        called["push"] = push
        return {"processed": 1, "failed": 0, "results": []}

    monkeypatch.setattr(C, "capture_note", fake_capture, raising=False)
    monkeypatch.setattr(C, "process_inbox", fake_process, raising=False)

    result = runner.invoke(C.cli, ["note", "a plain text note"])
    assert result.exit_code == 0
    assert called.get("captured") == "a plain text note"
    assert called.get("processed") is True


def test_note_routes_youtube_urls(monkeypatch):
    seen = {}

    def fake_youtube(url):
        seen["url"] = url
        return {"title": "V", "channel": "C", "folder_path": "p",
                "filename": "f.md"}

    monkeypatch.setattr(C, "process_youtube_url", fake_youtube, raising=False)
    monkeypatch.setattr(C, "sync", lambda msg: {"synced": True}, raising=False)
    monkeypatch.setattr(C, "run_linker_for_new_notes",
                        lambda notes: None, raising=False)

    result = runner.invoke(C.cli, ["note", "https://youtube.com/watch?v=abc"])
    assert result.exit_code == 0, result.output
    assert seen.get("url") == "https://youtube.com/watch?v=abc"


def test_rss_command_reports_summary(monkeypatch):
    import jarvis.rss_processor as R
    monkeypatch.setattr(R, "process_feeds",
                        lambda sync_git=True, verbose=True: {
                            "fetched": 30, "new": 5, "saved": 2,
                            "files": ["22-knowledge-base/rss/a.md"]},
                        raising=False)
    result = runner.invoke(C.cli, ["rss"])
    assert result.exit_code == 0
    assert "Saved" in result.output


def test_search_command_runs(monkeypatch):
    import jarvis.retrieval as RT
    monkeypatch.setattr(RT, "search_notes",
                        lambda q, limit=10: [{"title": "Redis Note", "score": 6,
                                              "folder_path": "08-databases",
                                              "filename": "redis.md", "domain": "db",
                                              "path": "p", "snippet": "redis persists"}],
                        raising=False)
    result = runner.invoke(C.cli, ["search", "redis"])
    assert result.exit_code == 0
    assert "Redis Note" in result.output


def test_ask_command_runs(monkeypatch):
    import jarvis.retrieval as RT
    monkeypatch.setattr(RT, "ask",
                        lambda question: {"answer": "Redis uses RDB and AOF.",
                                          "sources": [{"title": "Redis Note"}],
                                          "used_ai": True},
                        raising=False)
    result = runner.invoke(C.cli, ["ask", "how does redis persist?"])
    assert result.exit_code == 0
    assert "RDB and AOF" in result.output


def test_doctor_command_runs(monkeypatch):
    import jarvis.health as HL
    monkeypatch.setattr(HL, "check_health", lambda stale_days=90: {
        "total_indexed": 3, "missing_files": [], "empty_notes": [],
        "orphan_notes": [], "stale_notes": [], "broken_links": [],
        "no_frontmatter": [], "duplicate_rows": [], "untracked_files": [],
    }, raising=False)
    result = runner.invoke(C.cli, ["doctor"])
    assert result.exit_code == 0
    assert "Health score" in result.output


def test_reindex_dry_run_command(monkeypatch):
    import jarvis.health as HL
    monkeypatch.setattr(HL, "reindex",
                        lambda dry_run=False: {"added": [{"file": "a.md", "title": "A"}],
                                               "scanned": 5},
                        raising=False)
    result = runner.invoke(C.cli, ["reindex", "--dry-run"])
    assert result.exit_code == 0
    assert "Would add" in result.output


def test_review_list_command(monkeypatch):
    import jarvis.review as RV
    monkeypatch.setattr(RV, "due_notes",
                        lambda limit=10, domain=None: [
                            {"title": "Redis", "domain": "db", "key": "k",
                             "path": "p", "level": 0, "overdue_days": 3}],
                        raising=False)
    monkeypatch.setattr(RV, "review_stats",
                        lambda: {"tracked": 1, "mastered": 0, "due": 1},
                        raising=False)
    result = runner.invoke(C.cli, ["review", "--list"])
    assert result.exit_code == 0
    assert "Redis" in result.output


def test_review_handles_nothing_due(monkeypatch):
    import jarvis.review as RV
    monkeypatch.setattr(RV, "due_notes", lambda limit=10, domain=None: [], raising=False)
    monkeypatch.setattr(RV, "review_stats",
                        lambda: {"tracked": 0, "mastered": 0, "due": 0}, raising=False)
    result = runner.invoke(C.cli, ["review"])
    assert result.exit_code == 0
    assert "Nothing due" in result.output


def test_quiz_command_runs(monkeypatch):
    import jarvis.review as RV
    monkeypatch.setattr(RV, "generate_quiz",
                        lambda count=5, domain=None, note_type=None: [
                            {"question": "What is AOF?", "answer": "a log",
                             "source": "Redis"}],
                        raising=False)
    result = runner.invoke(C.cli, ["quiz", "-n", "1"], input="\ny\n")
    assert result.exit_code == 0
    assert "What is AOF?" in result.output


def test_export_requires_a_filter():
    result = runner.invoke(C.cli, ["export"])
    assert result.exit_code == 0
    assert "at least one filter" in result.output


def test_export_command_runs(monkeypatch):
    import jarvis.exporter as EX
    monkeypatch.setattr(EX, "export",
                        lambda **kw: {"path": "/tmp/out.md", "count": 4,
                                      "title": "DB Handbook"},
                        raising=False)
    result = runner.invoke(C.cli, ["export", "--domain", "databases"])
    assert result.exit_code == 0
    assert "DB Handbook" in result.output


def test_open_command_handles_no_match(monkeypatch):
    import jarvis.retrieval as RT
    monkeypatch.setattr(RT, "search_notes", lambda q, limit=1: [], raising=False)
    result = runner.invoke(C.cli, ["open", "nothing"])
    assert result.exit_code == 0
    assert "No note matches" in result.output


def test_serve_command_starts_server(monkeypatch):
    started = {}
    import jarvis.api_server as S
    monkeypatch.setattr(S, "run_server",
                        lambda host, port: started.update(host=host, port=port),
                        raising=False)
    result = runner.invoke(C.cli, ["serve", "--port", "9999"])
    assert result.exit_code == 0
    assert started["port"] == 9999
    assert "Dashboard" in result.output
