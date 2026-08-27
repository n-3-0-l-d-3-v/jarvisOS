"""Feature 16: fast capture — local commit now, push deferred / batched."""

import datetime

import pytest
from click.testing import CliRunner

from jarvis import cli as C
from jarvis import orchestrator as O
from jarvis.capture import capture_note

runner = CliRunner()
TODAY = datetime.date.today()


@pytest.fixture
def stub_classifier(monkeypatch):
    monkeypatch.setattr(O, "classify_note", lambda t, s, u: {
        "title": "Fast Note", "domain": "backend", "subdomain": "x",
        "folder_path": "22-knowledge-base", "type": "concept", "tags": [],
        "confidence": 0.9, "classifier_used": "stub", "dsa_pattern": "",
    }, raising=False)


def test_push_false_commits_locally_but_does_not_push(stub_classifier, monkeypatch, sandbox, clean_index):
    pushed = {"called": False}

    def fake_push():
        pushed["called"] = True
        return {"pushed": True}

    monkeypatch.setattr("jarvis.git_sync.push_to_remote", fake_push, raising=False)

    capture_note("offline capture", source="cli")
    result = O.process_inbox_orchestrated(force=True, push=False)

    assert result["processed"] == 1
    assert result["pushed"] is False
    assert pushed["called"] is False, "push must NOT run when push=False"

    (sandbox / "22-knowledge-base" / "fast-note.md").unlink(missing_ok=True)


def test_push_true_pushes_once_for_the_batch(stub_classifier, monkeypatch, sandbox, clean_index):
    push_calls = {"n": 0}

    def fake_push():
        push_calls["n"] += 1
        return {"pushed": True}

    monkeypatch.setattr("jarvis.git_sync.push_to_remote", fake_push, raising=False)

    # three notes in the inbox -> still only ONE push at the end
    for i in range(3):
        capture_note(f"batch note {i}", source="cli")
    # distinct filenames so all three save
    titles = iter(["A Note", "B Note", "C Note"])
    monkeypatch.setattr(O, "classify_note", lambda t, s, u: {
        "title": next(titles), "domain": "backend", "subdomain": "x",
        "folder_path": "22-knowledge-base", "type": "concept", "tags": [],
        "confidence": 0.9, "classifier_used": "stub", "dsa_pattern": "",
    }, raising=False)

    result = O.process_inbox_orchestrated(force=True, push=True)
    assert result["processed"] == 3
    assert push_calls["n"] == 1, f"expected 1 batched push, got {push_calls['n']}"

    for name in ("a-note.md", "b-note.md", "c-note.md"):
        (sandbox / "22-knowledge-base" / name).unlink(missing_ok=True)


def test_local_commit_still_happens_when_push_deferred(stub_classifier, sandbox, clean_index):
    """The note must be committed to git even without a push."""
    from jarvis.git_sync import get_repo

    capture_note("committed offline", source="cli")
    O.process_inbox_orchestrated(force=True, push=False)

    repo = get_repo()
    # working tree should be clean — everything was committed locally
    assert not repo.is_dirty(untracked_files=True), "changes left uncommitted"
    latest_msg = repo.head.commit.message
    assert "Fast Note" in latest_msg or "wikilink" in latest_msg

    (sandbox / "22-knowledge-base" / "fast-note.md").unlink(missing_ok=True)


def test_note_command_accepts_no_push_flag(monkeypatch):
    seen = {}

    def fake_capture(text, source, source_url, extra=None):
        return "p"

    def fake_process(force=False, push=True):
        seen["push"] = push
        return {"processed": 1, "failed": 0, "results": []}

    monkeypatch.setattr(C, "capture_note", fake_capture, raising=False)
    monkeypatch.setattr(C, "process_inbox", fake_process, raising=False)

    result = runner.invoke(C.cli, ["note", "hello", "--no-push"])
    assert result.exit_code == 0
    assert seen["push"] is False


def test_push_command_registered_and_runs(monkeypatch):
    monkeypatch.setattr("jarvis.git_sync.stage_and_commit",
                        lambda msg: {"committed": False}, raising=False)
    monkeypatch.setattr("jarvis.git_sync.get_status",
                        lambda: {"ahead": 2}, raising=False)
    monkeypatch.setattr("jarvis.git_sync.push_to_remote",
                        lambda: {"pushed": True}, raising=False)
    result = runner.invoke(C.cli, ["push"])
    assert result.exit_code == 0
    assert "Synced" in result.output or "Pushed" in result.output
