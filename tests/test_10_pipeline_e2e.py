"""
Feature 10: the FULL capture pipeline, end to end, in the sandbox repo.

capture -> classify -> format -> save -> index -> daily log -> git commit

The classifier is stubbed so the test is deterministic and offline; every other
stage is the real code path.
"""

import datetime
import json

import pytest

from jarvis import orchestrator as O
from jarvis.capture import capture_note

TODAY = datetime.date.today()


@pytest.fixture
def stub_classifier(monkeypatch):
    def _fake(text, source, source_url):
        return {
            "title": "Redis Persistence", "domain": "databases",
            "subdomain": "redis", "folder_path": "08-databases/redis",
            "type": "concept", "tags": ["redis", "persistence"],
            "summary": "How redis persists.", "confidence": 0.9,
            "classifier_used": "stub", "dsa_pattern": "",
        }
    monkeypatch.setattr(O, "classify_note", _fake, raising=False)


def _daily_log_text():
    from jarvis.daily_log import get_log_path
    path = get_log_path(TODAY)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_full_pipeline_writes_note_index_and_log(stub_classifier, sandbox, clean_index):
    inbox_file = capture_note("redis rdb vs aof persistence", source="cli")

    result = O.process_single_note(inbox_file, force=True)
    assert result["success"] is True, result.get("error")

    # 1. markdown file written to the classified folder
    note_path = sandbox / "08-databases" / "redis" / "redis-persistence.md"
    assert note_path.exists(), "note markdown was not written"
    content = note_path.read_text(encoding="utf-8")
    # Lean template is the default now: frontmatter + the actual captured text,
    # plus the placeholder the linker needs.
    assert content.startswith("---")
    assert "redis rdb vs aof persistence" in content
    assert "<!-- [[wikilinks]] added automatically -->" in content

    # 2. index.json updated
    index = json.loads(clean_index.read_text(encoding="utf-8"))
    assert index["total_notes"] == 1
    entry = index["notes"][0]
    assert entry["title"] == "Redis Persistence"
    assert entry["folder_path"] == "08-databases/redis"
    assert entry["filename"] == "redis-persistence.md"

    # 3. daily log written (ISSUE 1 regression guard)
    log = _daily_log_text()
    assert "redis rdb vs aof persistence" in log

    inbox_file.unlink(missing_ok=True)
    note_path.unlink()


def test_daily_log_entry_is_not_duplicated(stub_classifier, sandbox, clean_index):
    """Regression: orchestrator is the ONLY place that appends to the log."""
    from jarvis.daily_log import ensure_log_exists
    ensure_log_exists(TODAY)
    before = _daily_log_text().count("unique-log-marker")

    f = capture_note("unique-log-marker persistence note", source="cli")
    O.process_single_note(f, force=True)

    after = _daily_log_text().count("unique-log-marker")
    assert after == before + 1, "daily log entry was written more than once"

    f.unlink(missing_ok=True)
    (sandbox / "08-databases" / "redis" / "redis-persistence.md").unlink(missing_ok=True)


def test_duplicate_note_is_skipped_without_force(stub_classifier, sandbox, clean_index):
    f1 = capture_note("first version", source="cli")
    assert O.process_single_note(f1, force=True)["success"] is True

    f2 = capture_note("second version", source="cli")
    result = O.process_single_note(f2, force=False)
    assert result["success"] is False
    assert result["error"] == "already_exists"

    (sandbox / "08-databases" / "redis" / "redis-persistence.md").unlink(missing_ok=True)


def test_force_overwrites_existing_note(stub_classifier, sandbox, clean_index):
    f1 = capture_note("original body", source="cli")
    O.process_single_note(f1, force=True)
    f2 = capture_note("replacement body", source="cli")
    assert O.process_single_note(f2, force=True)["success"] is True

    content = (sandbox / "08-databases" / "redis" / "redis-persistence.md") \
        .read_text(encoding="utf-8")
    assert "replacement body" in content
    (sandbox / "08-databases" / "redis" / "redis-persistence.md").unlink(missing_ok=True)


def test_dsa_note_gets_deterministic_filename(monkeypatch, sandbox, clean_index):
    """DSA notes must be named lc-<n>-<slug>.md so duplicates collide."""
    monkeypatch.setattr(O, "classify_note", lambda t, s, u: {
        "title": "Two Sum", "domain": "dsa", "subdomain": "arrays",
        "folder_path": "04-dsa/arrays", "type": "dsa", "tags": ["arrays"],
        "confidence": 0.9, "classifier_used": "stub", "dsa_pattern": "arrays",
    }, raising=False)
    monkeypatch.setattr(O, "run_parallel_dsa_enrichment", lambda text, cls: (
        {"problem_summary": "Given an array", "url": "https://lc.com/two-sum",
         "difficulty": "Easy", "tags": ["Array"], "companies": ["Google"]},
        {"problem_number": "LC-1", "problem_name": "Two Sum", "pattern": "arrays",
         "approach": "hashmap", "time_complexity": "O(n)",
         "space_complexity": "O(n)", "key_insight": "complement",
         "edge_cases": ["dupes"], "similar_problems": ["3Sum"],
         "difficulty": "Easy", "companies": ["Google"],
         "mistakes_to_avoid": "off by one"},
    ), raising=False)

    f = capture_note("LC-1 two sum hashmap", source="leetcode")
    result = O.process_single_note(f, force=True)
    assert result["success"] is True

    expected = sandbox / "04-dsa" / "arrays" / "lc-1-two-sum.md"
    assert expected.exists(), f"expected {expected.name}, got {result['filepath']}"
    content = expected.read_text(encoding="utf-8")
    assert "## Problem Statement" in content and "O(n)" in content

    log = _daily_log_text()
    assert "LC-1" in log.split("## LeetCode / DSA")[1].split("##")[0]

    expected.unlink()


def test_process_inbox_moves_file_to_processed(stub_classifier, sandbox, clean_index):
    from jarvis.config import INBOX_PROCESSED, INBOX_RAW
    f = capture_note("inbox move test", source="cli")
    name = f.name
    O.process_inbox_orchestrated(force=True)
    assert not (INBOX_RAW / name).exists(), "file left in inbox/raw"
    assert (INBOX_PROCESSED / name).exists(), "file not moved to processed"
    (INBOX_PROCESSED / name).unlink(missing_ok=True)
    (sandbox / "08-databases" / "redis" / "redis-persistence.md").unlink(missing_ok=True)


def test_pipeline_failure_is_captured_not_raised(monkeypatch, clean_index):
    def _boom(*a, **k):
        raise RuntimeError("classifier exploded")
    monkeypatch.setattr(O, "classify_note", _boom, raising=False)

    f = capture_note("this will fail", source="cli")
    result = O.process_single_note(f, force=False)
    assert result["success"] is False
    assert "classifier exploded" in result["error"]
    f.unlink(missing_ok=True)
