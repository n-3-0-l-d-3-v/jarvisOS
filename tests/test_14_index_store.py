"""Feature 14: centralized index store — the duplicate-entry bug fix."""

import json

from jarvis import index_store as IS


def _entry(fp, fn, **over):
    return dict({"id": "x", "title": "T", "folder_path": fp, "filename": fn,
                 "domain": "d", "type": "concept"}, **over)


def test_upsert_adds_new_note(clean_index):
    assert IS.upsert_note(_entry("04-dsa", "two-sum.md")) == "added"
    data = json.loads(clean_index.read_text(encoding="utf-8"))
    assert data["total_notes"] == 1


def test_upsert_updates_same_file_instead_of_duplicating(clean_index):
    """The core bug: re-saving the same file must NOT add a second row."""
    IS.upsert_note(_entry("04-dsa", "two-sum.md", title="First"))
    result = IS.upsert_note(_entry("04-dsa", "two-sum.md", title="Second"))
    assert result == "updated"

    data = json.loads(clean_index.read_text(encoding="utf-8"))
    assert data["total_notes"] == 1, "re-capture created a duplicate index row"
    assert data["notes"][0]["title"] == "Second"


def test_different_files_are_distinct_rows(clean_index):
    IS.upsert_note(_entry("04-dsa", "two-sum.md"))
    IS.upsert_note(_entry("04-dsa", "three-sum.md"))
    IS.upsert_note(_entry("08-databases", "two-sum.md"))  # same name, diff folder
    data = json.loads(clean_index.read_text(encoding="utf-8"))
    assert data["total_notes"] == 3


def test_upsert_preserves_original_id_and_date(clean_index):
    IS.upsert_note(_entry("f", "n.md", id="orig-id", date="2026-01-01"))
    # A re-capture that omits id/date must keep the originals.
    entry = _entry("f", "n.md", title="Updated")
    entry.pop("id")
    IS.upsert_note(entry)
    note = json.loads(clean_index.read_text(encoding="utf-8"))["notes"][0]
    assert note["id"] == "orig-id"
    assert note["date"] == "2026-01-01"
    assert note["title"] == "Updated"


def test_total_notes_always_matches_real_length(clean_index):
    for i in range(5):
        IS.upsert_note(_entry("f", f"n{i}.md"))
    for i in range(5):  # re-upsert everything
        IS.upsert_note(_entry("f", f"n{i}.md", title="again"))
    data = json.loads(clean_index.read_text(encoding="utf-8"))
    assert data["total_notes"] == 5 == len(data["notes"])


def test_remove_note(clean_index):
    IS.upsert_note(_entry("f", "keep.md"))
    IS.upsert_note(_entry("f", "drop.md"))
    assert IS.remove_note("f", "drop.md") is True
    assert IS.remove_note("f", "missing.md") is False
    data = json.loads(clean_index.read_text(encoding="utf-8"))
    assert [n["filename"] for n in data["notes"]] == ["keep.md"]


def test_dedupe_index_collapses_legacy_duplicates(write_index):
    """Repair path for indexes corrupted before upsert existed."""
    index_path = write_index([
        _entry("04-dsa", "two-sum.md", title="v1"),
        _entry("04-dsa", "two-sum.md", title="v2"),
        _entry("04-dsa", "two-sum.md", title="v3"),
        _entry("08-databases", "redis.md", title="r"),
    ])
    result = IS.dedupe_index()
    assert result["removed"] == 2
    assert result["remaining"] == 2

    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert data["total_notes"] == 2
    # last write wins
    two_sum = [n for n in data["notes"] if n["filename"] == "two-sum.md"][0]
    assert two_sum["title"] == "v3"


def test_load_index_survives_missing_or_corrupt(clean_index):
    clean_index.write_text("{ this is not json", encoding="utf-8")
    data = IS.load_index()
    assert data == {"total_notes": 0, "notes": []}
