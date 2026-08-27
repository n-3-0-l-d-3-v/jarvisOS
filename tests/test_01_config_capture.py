"""Feature 1: config resolution + inbox capture."""

import json

from jarvis import config
from jarvis.capture import capture_note, list_pending, mark_failed, mark_processed


def test_config_points_at_sandbox(sandbox):
    assert config.REPO_PATH == sandbox
    assert config.INDEX_PATH == sandbox / "00-meta" / "index.json"
    assert config.DAILY_LOGS_PATH == sandbox / "daily-logs"


def test_config_creates_required_dirs(sandbox):
    for path in (config.INBOX_RAW, config.INBOX_PROCESSED,
                 config.INBOX_FAILED, config.META_PATH, config.DAILY_LOGS_PATH):
        assert path.exists(), f"{path} was not created"


def test_capture_note_writes_valid_payload():
    path = capture_note("test capture payload", source="cli", source_url="")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in ("id", "timestamp", "date", "time", "source",
                  "source_url", "text", "status"):
        assert field in data, f"missing field {field}"
    assert data["text"] == "test capture payload"
    assert data["status"] == "pending"
    path.unlink()


def test_list_pending_and_mark_processed():
    path = capture_note("pending item", source="cli")
    assert path in list_pending()
    dest = mark_processed(path)
    assert dest.exists() and not path.exists()
    assert path not in list_pending()
    dest.unlink()


def test_mark_failed_records_reason():
    path = capture_note("failing item", source="cli")
    dest = mark_failed(path, "boom")
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["failure_reason"] == "boom"
    assert not path.exists()
    dest.unlink()


def test_capture_ids_are_unique():
    paths = [capture_note(f"note {i}") for i in range(5)]
    ids = {json.loads(p.read_text(encoding="utf-8"))["id"] for p in paths}
    assert len(ids) == 5
    for p in paths:
        p.unlink()
