"""Feature 18: spaced repetition, quiz, and the documentation exporter."""

import json
from datetime import date, timedelta

import pytest

from jarvis import exporter as E
from jarvis import review as R

NOTE = ("---\ntitle: Redis Persistence\ndomain: databases\ntype: concept\n---\n"
        "# Redis Persistence\n\nRedis uses RDB snapshots and AOF logs.\n\n"
        "## Empty Section\n\n## Related Topics\n- [[other|Other]]\n")


@pytest.fixture
def seeded(sandbox, write_index):
    def _mk(folder, name, title, domain="databases", tags=None, ntype="concept"):
        p = sandbox / folder
        p.mkdir(parents=True, exist_ok=True)
        (p / name).write_text(NOTE.replace("Redis Persistence", title),
                              encoding="utf-8")
        return {"id": name[:4], "title": title, "folder_path": folder,
                "filename": name, "domain": domain, "tags": tags or [],
                "type": ntype, "subdomain": "", "date": "2026-01-01"}

    rows = [
        _mk("08-databases", "redis.md", "Redis Persistence", tags=["redis"]),
        _mk("08-databases", "postgres.md", "Postgres MVCC", tags=["postgres"]),
        _mk("04-dsa", "two-sum.md", "Two Sum", domain="dsa",
            tags=["arrays"], ntype="dsa"),
    ]
    write_index(rows)
    (sandbox / "00-meta" / "review.json").unlink(missing_ok=True)
    return sandbox


# --- spaced repetition ----------------------------------------------------
def test_never_reviewed_notes_become_due(seeded):
    due = R.due_notes()
    assert len(due) == 3
    assert {d["title"] for d in due} == {"Redis Persistence", "Postgres MVCC", "Two Sum"}


def test_domain_filter(seeded):
    due = R.due_notes(domain="dsa")
    assert [d["title"] for d in due] == ["Two Sum"]


def test_recording_success_pushes_review_further_out(seeded):
    due = R.due_notes()
    key = due[0]["key"]
    entry = R.record_review(key, remembered=True)
    assert entry["level"] == 1
    assert entry["next_review"] == (date.today() + timedelta(days=R.INTERVALS[1])).isoformat()
    # no longer due today
    assert key not in {d["key"] for d in R.due_notes()}


def test_intervals_grow_each_success(seeded):
    key = R.due_notes()[0]["key"]
    levels = []
    for _ in range(4):
        levels.append(R.record_review(key, remembered=True)["level"])
    assert levels == [1, 2, 3, 4]


def test_forgetting_resets_to_level_zero(seeded):
    key = R.due_notes()[0]["key"]
    R.record_review(key, remembered=True)
    R.record_review(key, remembered=True)
    entry = R.record_review(key, remembered=False)
    assert entry["level"] == 0
    assert entry["next_review"] == (date.today() + timedelta(days=R.INTERVALS[0])).isoformat()


def test_level_is_capped(seeded):
    key = R.due_notes()[0]["key"]
    for _ in range(20):
        entry = R.record_review(key, remembered=True)
    assert entry["level"] == len(R.INTERVALS) - 1


def test_review_state_persists_to_disk(seeded):
    key = R.due_notes()[0]["key"]
    R.record_review(key, remembered=True)
    saved = json.loads((seeded / "00-meta" / "review.json").read_text(encoding="utf-8"))
    assert key in saved and saved[key]["reviews"] == 1


def test_review_stats(seeded):
    key = R.due_notes()[0]["key"]
    R.record_review(key, remembered=True)
    stats = R.review_stats()
    assert stats["tracked"] == 1
    assert stats["due"] == 2


def test_due_notes_skips_missing_files(sandbox, write_index):
    write_index([{"id": "1", "title": "Ghost", "folder_path": "x",
                  "filename": "ghost.md", "domain": "d", "date": "2026-01-01"}])
    assert R.due_notes() == []


# --- quiz ------------------------------------------------------------------
def test_quiz_uses_ai_when_available(seeded, monkeypatch):
    monkeypatch.setattr(R, "_ai", lambda p: json.dumps([
        {"question": "What does AOF do?", "answer": "Logs every write",
         "source": "Redis Persistence"}]), raising=False)
    quiz = R.generate_quiz(count=1)
    assert quiz[0]["question"] == "What does AOF do?"


def test_quiz_falls_back_without_ai(seeded, monkeypatch):
    monkeypatch.setattr(R, "_ai", lambda p: None, raising=False)
    quiz = R.generate_quiz(count=2)
    assert len(quiz) == 2
    assert all(q["question"].startswith("Explain:") for q in quiz)


def test_quiz_respects_domain_filter(seeded, monkeypatch):
    monkeypatch.setattr(R, "_ai", lambda p: None, raising=False)
    quiz = R.generate_quiz(count=5, domain="dsa")
    assert len(quiz) == 1 and "Two Sum" in quiz[0]["question"]


def test_quiz_empty_when_no_notes(sandbox, write_index, monkeypatch):
    write_index([])
    assert R.generate_quiz() == []


# --- exporter --------------------------------------------------------------
def test_select_by_domain(seeded):
    assert len(E.select_notes(domain="databases")) == 2


def test_select_by_tag(seeded):
    assert [n["title"] for n in E.select_notes(tag="redis")] == ["Redis Persistence"]


def test_select_by_type(seeded):
    assert [n["title"] for n in E.select_notes(note_type="dsa")] == ["Two Sum"]


def test_build_document_has_title_toc_and_content(seeded):
    notes = E.select_notes(domain="databases")
    doc = E.build_document(notes, "DB Handbook")
    assert doc.startswith("# DB Handbook")
    assert "## Contents" in doc
    assert "### Redis Persistence" in doc
    assert "RDB snapshots" in doc


def test_export_strips_frontmatter_and_empty_sections(seeded):
    doc = E.build_document(E.select_notes(domain="databases"), "T")
    assert "---\ntitle:" not in doc
    assert "Empty Section" not in doc, "empty sections should be dropped"


def test_export_demotes_headings_so_they_nest(seeded):
    doc = E.build_document(E.select_notes(tag="redis"), "T")
    # note's "## Related Topics" becomes "#### Related Topics" under "### Title"
    assert "#### Related Topics" in doc


def test_export_writes_file(seeded, tmp_path):
    out = tmp_path / "handbook.md"
    result = E.export(domain="databases", output=str(out), title="DB Book")
    assert out.exists()
    assert result["count"] == 2
    assert "DB Book" in out.read_text(encoding="utf-8")


def test_export_handles_no_matches(seeded, tmp_path):
    out = tmp_path / "none.md"
    result = E.export(domain="nonexistent-domain", output=str(out))
    assert result["count"] == 0
    assert "No notes matched" in out.read_text(encoding="utf-8")


def test_export_no_toc_option(seeded, tmp_path):
    out = tmp_path / "notoc.md"
    E.export(domain="databases", output=str(out), include_toc=False)
    assert "## Contents" not in out.read_text(encoding="utf-8")
