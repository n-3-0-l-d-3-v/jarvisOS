"""Feature 6: index cleaning + GitHub sync."""

import json

from jarvis import git_sync as G
from jarvis.index_cleaner import clean_index


# --- index_cleaner ---------------------------------------------------------
def test_clean_index_removes_only_stale_entries(sandbox, write_index):
    real = sandbox / "22-knowledge-base" / "real-note.md"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("# real", encoding="utf-8")

    write_index([
        {"id": "1", "folder_path": "22-knowledge-base", "filename": "real-note.md"},
        {"id": "2", "folder_path": "22-knowledge-base", "filename": "ghost.md"},
    ])

    result = clean_index()
    assert result["removed"] == 1
    assert result["remaining"] == 1

    data = json.loads((sandbox / "00-meta" / "index.json").read_text(encoding="utf-8"))
    assert [n["id"] for n in data["notes"]] == ["1"]
    assert data["total_notes"] == 1
    real.unlink()


def test_clean_index_noop_when_all_valid(sandbox, write_index):
    f = sandbox / "22-knowledge-base" / "keep.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# keep", encoding="utf-8")
    write_index([{"id": "1", "folder_path": "22-knowledge-base", "filename": "keep.md"}])
    assert clean_index()["removed"] == 0
    f.unlink()


# --- git_sync --------------------------------------------------------------
def test_build_commit_message_follows_convention():
    msg = G.build_commit_message(
        {"type": "dsa", "domain": "dsa"}, "LC-1 two sum with hashmap")
    assert msg.startswith("feat: add dsa note — ")
    assert msg.endswith("[dsa]")


def test_build_commit_message_truncates_long_titles():
    long_text = "word " * 60
    msg = G.build_commit_message({"type": "concept", "domain": "backend"}, long_text)
    assert len(msg) < 120
    assert msg.endswith("[backend]")


def test_get_status_reads_sandbox_repo():
    status = G.get_status()
    for key in ("branch", "is_dirty", "untracked", "modified", "ahead"):
        assert key in status


def test_stage_and_commit_then_nothing_to_commit(sandbox):
    (sandbox / "22-knowledge-base" / "commit-me.md").write_text(
        "# commit me", encoding="utf-8")
    result = G.stage_and_commit("test: add a note")
    assert result["committed"] is True
    assert len(result["sha"]) == 7
    # second call with a clean tree must report nothing to commit
    assert G.stage_and_commit("test: nothing")["committed"] is False


def test_sync_handles_missing_remote_gracefully(sandbox):
    """Sandbox has no 'origin' — sync must not raise, just report the failure."""
    (sandbox / "22-knowledge-base" / "sync-me.md").write_text("# s", encoding="utf-8")
    result = G.sync("test: sync attempt")
    assert result["committed"] is True
    assert result["synced"] is False
    assert "push_error" in result
