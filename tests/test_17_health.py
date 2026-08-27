"""Feature 17: jar doctor (health check) + jar reindex."""

import json

import pytest

from jarvis import health as H


@pytest.fixture(autouse=True)
def _isolate(pristine_repo):
    """Every health test asserts on repo-wide counts, so start from empty."""
    return pristine_repo


def _write(sandbox, folder, name, content):
    p = sandbox / folder
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text(content, encoding="utf-8")
    return p / name


GOOD = ("---\ntitle: Good Note\ndomain: databases\ntype: concept\n---\n"
        "# Good Note\n\nThis note has plenty of genuine content in it, well past "
        "the threshold used to detect empty scaffolding notes.\n"
        "## Related Topics\n- [[other-note|Other]]\n")


def test_detects_missing_file(sandbox, write_index):
    write_index([{"id": "1", "title": "Ghost", "folder_path": "04-dsa",
                  "filename": "ghost.md", "date": "2026-07-01"}])
    findings = H.check_health()
    assert len(findings["missing_files"]) == 1
    assert findings["missing_files"][0]["title"] == "Ghost"


def test_detects_empty_note(sandbox, write_index):
    _write(sandbox, "22-knowledge-base", "empty.md",
           "---\ntitle: Empty\n---\n# Empty\n<!-- nothing -->\n")
    write_index([{"id": "1", "title": "Empty", "folder_path": "22-knowledge-base",
                  "filename": "empty.md", "date": "2026-07-01"}])
    findings = H.check_health()
    assert any(e["file"].endswith("empty.md") for e in findings["empty_notes"])


def test_full_content_note_is_not_flagged_empty(sandbox, write_index):
    _write(sandbox, "08-databases", "good.md", GOOD)
    _write(sandbox, "08-databases", "other-note.md", GOOD)
    write_index([
        {"id": "1", "title": "Good Note", "folder_path": "08-databases",
         "filename": "good.md", "date": "2026-07-01"},
        {"id": "2", "title": "Other", "folder_path": "08-databases",
         "filename": "other-note.md", "date": "2026-07-01"},
    ])
    findings = H.check_health()
    assert not any(e["file"].endswith("good.md") for e in findings["empty_notes"])


def test_detects_duplicate_index_rows(sandbox, write_index):
    _write(sandbox, "08-databases", "dupe.md", GOOD)
    row = {"id": "1", "title": "D", "folder_path": "08-databases",
           "filename": "dupe.md", "date": "2026-07-01"}
    write_index([row, dict(row), dict(row)])
    findings = H.check_health()
    assert findings["duplicate_rows"][0]["count"] == 3


def test_detects_broken_wikilink(sandbox, write_index):
    _write(sandbox, "08-databases", "linky.md",
           "---\ntitle: Linky\n---\n# Linky\n\nlots of real content here to avoid "
           "the empty check firing on this note at all.\n"
           "## Related\n- [[does-not-exist-anywhere|Nope]]\n")
    write_index([{"id": "1", "title": "Linky", "folder_path": "08-databases",
                  "filename": "linky.md", "date": "2026-07-01"}])
    findings = H.check_health()
    assert any(b["target"] == "does-not-exist-anywhere"
               for b in findings["broken_links"])


def test_link_to_existing_but_unindexed_file_is_not_broken(sandbox, write_index):
    """Regression: a link to a real file on disk isn't broken, it's unindexed."""
    _write(sandbox, "08-databases", "target-note.md", GOOD)
    _write(sandbox, "08-databases", "src.md",
           "---\ntitle: Src\n---\n# Src\n\nplenty of genuine content here so the "
           "empty-note detector does not fire for this particular file.\n"
           "## Related\n- [[target-note|T]]\n")
    write_index([{"id": "1", "title": "Src", "folder_path": "08-databases",
                  "filename": "src.md", "date": "2026-07-01"}])
    findings = H.check_health()
    assert not any(b["target"] == "target-note" for b in findings["broken_links"])
    assert any(u["file"].endswith("target-note.md")
               for u in findings["untracked_files"])


def test_detects_stale_notes(sandbox, write_index):
    _write(sandbox, "08-databases", "old.md", GOOD)
    write_index([{"id": "1", "title": "Old", "folder_path": "08-databases",
                  "filename": "old.md", "date": "2020-01-01"}])
    findings = H.check_health(stale_days=30)
    assert findings["stale_notes"] and findings["stale_notes"][0]["days"] > 30


def test_health_score_is_100_for_clean_repo(sandbox, write_index):
    _write(sandbox, "08-databases", "clean.md", GOOD)
    _write(sandbox, "08-databases", "other-note.md", GOOD)
    write_index([
        {"id": "1", "title": "Clean", "folder_path": "08-databases",
         "filename": "clean.md", "date": "2026-07-01"},
        {"id": "2", "title": "Other", "folder_path": "08-databases",
         "filename": "other-note.md", "date": "2026-07-01"},
    ])
    findings = H.check_health()
    assert H.health_score(findings) >= 90


def test_health_score_drops_with_problems(sandbox, write_index):
    write_index([{"id": str(i), "title": "Ghost", "folder_path": "x",
                  "filename": f"ghost{i}.md", "date": "2026-07-01"}
                 for i in range(5)])
    findings = H.check_health()
    assert H.health_score(findings) < 60


def test_summarize_returns_rows(sandbox, write_index):
    write_index([])
    rows = H.summarize(H.check_health())
    assert all(len(r) == 4 for r in rows)


# --- frontmatter parsing + reindex ----------------------------------------
def test_parse_frontmatter_flat_and_list():
    raw = ('---\ntitle: "My Note"\ndomain: databases\ntags:\n  - "redis"\n'
           '  - "cache"\ntype: concept\n---\n# body\n')
    fm = H._parse_frontmatter(raw)
    assert fm["title"] == "My Note"
    assert fm["domain"] == "databases"
    assert fm["tags"] == ["redis", "cache"]


def test_parse_frontmatter_inline_list():
    fm = H._parse_frontmatter('---\ntitle: T\ntags: ["a", "b"]\n---\n')
    assert fm["tags"] == ["a", "b"]


def test_parse_frontmatter_missing_returns_empty():
    assert H._parse_frontmatter("# no frontmatter") == {}


def test_reindex_adds_unindexed_notes(sandbox, clean_index):
    _write(sandbox, "08-databases", "found.md",
           '---\ntitle: "Found Note"\ndomain: databases\ntype: concept\n'
           'tags:\n  - "redis"\n---\n# Found Note\n\ncontent\n')
    result = H.reindex()
    assert any(a["title"] == "Found Note" for a in result["added"])

    notes = json.loads(clean_index.read_text(encoding="utf-8"))["notes"]
    entry = [n for n in notes if n["filename"] == "found.md"][0]
    assert entry["domain"] == "databases"
    assert entry["tags"] == ["redis"]


def test_reindex_dry_run_writes_nothing(sandbox, clean_index):
    _write(sandbox, "08-databases", "dry.md", GOOD)
    result = H.reindex(dry_run=True)
    assert result["added"]
    notes = json.loads(clean_index.read_text(encoding="utf-8"))["notes"]
    assert notes == []


def test_reindex_skips_already_indexed(sandbox, write_index):
    _write(sandbox, "08-databases", "known.md", GOOD)
    write_index([{"id": "1", "title": "Known", "folder_path": "08-databases",
                  "filename": "known.md", "date": "2026-07-01"}])
    result = H.reindex()
    assert not any(a["file"].endswith("known.md") for a in result["added"])


def test_reindex_ignores_daily_logs_and_inbox(sandbox, clean_index):
    (sandbox / "daily-logs" / "2026" / "07").mkdir(parents=True, exist_ok=True)
    (sandbox / "daily-logs" / "2026" / "07" / "2026-07-01.md").write_text(
        "# log", encoding="utf-8")
    result = H.reindex()
    assert not any("daily-logs" in a["file"] for a in result["added"])
