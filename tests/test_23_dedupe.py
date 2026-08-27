"""Feature 23: near-duplicate detection and merging."""

import pytest

from jarvis import dedupe as D
from jarvis.index_store import load_index

# Modelled on the real duplicates found in the live repo: the same fact written
# twice on different days, differing only in phrasing (those scored 74-93%).
BODY_A = ("Redis sorted sets use a skiplist internally, which gives O(log n) "
          "complexity for range queries over ordered members.")
BODY_B = ("Redis sorted sets internally use a skiplist, which gives O(log n) "
          "complexity for range queries over ordered members.")
BODY_DIFFERENT = ("Docker multi stage builds keep the final image small by "
                  "discarding build tooling from the runtime layer entirely.")


@pytest.fixture
def repo(pristine_repo, write_index):
    def _make(specs):
        rows = []
        for folder, fn, title, body, domain in specs:
            p = pristine_repo / folder
            p.mkdir(parents=True, exist_ok=True)
            (p / fn).write_text(
                f"---\ntitle: {title}\ndomain: {domain}\n---\n"
                f"# {title}\n\n{body}\n", encoding="utf-8")
            rows.append({"id": fn[:6], "title": title, "folder_path": folder,
                         "filename": fn, "domain": domain, "subdomain": "",
                         "tags": [], "type": "concept", "date": "2026-01-01"})
        write_index(rows)
        return pristine_repo
    return _make


# --- detection -------------------------------------------------------------
def test_finds_near_duplicates(repo):
    repo([
        ("08-databases", "a.md", "Redis Sorted Sets Use Skiplist", BODY_A, "databases"),
        ("08-databases", "b.md", "Redis Sorted Sets Internally Use A", BODY_B, "databases"),
    ])
    clusters = D.find_duplicate_clusters()
    assert len(clusters) == 1
    assert len(clusters[0]["duplicates"]) == 1


def test_distinct_notes_are_not_clustered(repo):
    repo([
        ("08-databases", "a.md", "Redis Skiplist", BODY_A, "databases"),
        ("10-devops", "b.md", "Docker Multi Stage", BODY_DIFFERENT, "devops"),
    ])
    assert D.find_duplicate_clusters() == []


def test_threshold_controls_sensitivity(repo):
    repo([
        ("08-databases", "a.md", "Redis Sorted Sets Use Skiplist", BODY_A, "databases"),
        ("08-databases", "b.md", "Redis Sorted Sets Internally Use A", BODY_B, "databases"),
    ])
    assert D.find_duplicate_clusters(threshold=0.99) == []
    assert D.find_duplicate_clusters(threshold=0.5)


def test_three_way_cluster_groups_together(repo):
    repo([
        ("08-databases", "a.md", "Redis Sorted Sets Use Skiplist", BODY_A, "databases"),
        ("08-databases", "b.md", "Redis Sorted Sets Internally Use A", BODY_B, "databases"),
        ("08-databases", "c.md", "Redis Sorted Sets Use Skiplist For", BODY_A, "databases"),
    ])
    clusters = D.find_duplicate_clusters()
    assert len(clusters) == 1
    assert len(clusters[0]["duplicates"]) == 2


def test_wiki_pages_are_excluded(pristine_repo, write_index):
    """Synthesized pages are supposed to overlap their sources."""
    for folder, fn, ntype in [("08-databases", "a.md", "concept"),
                              ("wiki/topics", "redis.md", "wiki")]:
        p = pristine_repo / folder
        p.mkdir(parents=True, exist_ok=True)
        (p / fn).write_text(f"# t\n\n{BODY_A}", encoding="utf-8")
    write_index([
        {"id": "1", "title": "Redis Skiplist", "folder_path": "08-databases",
         "filename": "a.md", "domain": "databases", "type": "concept",
         "tags": [], "date": "2026-01-01"},
        {"id": "2", "title": "Redis (wiki)", "folder_path": "wiki/topics",
         "filename": "redis.md", "domain": "wiki", "type": "wiki",
         "tags": [], "date": "2026-01-01"},
    ])
    assert D.find_duplicate_clusters() == []


# --- survivor selection ----------------------------------------------------
def test_truncated_title_is_not_kept(repo):
    """A fragment title loses even when its file holds the most text."""
    repo([
        ("08-databases", "good.md", "Redis Sorted Sets Use Skiplist",
         BODY_A, "databases"),
        ("08-databases", "frag.md", "Redis Sorted Sets Internally Use A",
         BODY_B + " " + BODY_B, "databases"),
    ])
    cluster = D.find_duplicate_clusters()[0]
    assert cluster["keep"]["title"] == "Redis Sorted Sets Use Skiplist"


def test_correct_folder_preferred_over_misfiled(repo):
    repo([
        ("03-programming/typescript", "wrong.md", "Redis Skiplist Notes",
         BODY_A + " extra text here to be longer", "databases"),
        ("08-databases", "right.md", "Redis Skiplist Guide", BODY_B, "databases"),
    ])
    cluster = D.find_duplicate_clusters()[0]
    assert cluster["keep"]["folder_path"] == "08-databases"


@pytest.mark.parametrize("title,expect_low", [
    ("Redis Sorted Sets Internally Use A", True),
    ("Docker Multi Stage Builds Reduce Final For", True),
    ("Redis Persistence RDB AOF", False),
])
def test_title_quality_detects_fragments(title, expect_low):
    score = D._title_quality(title)
    assert (score < 0.6) is expect_low


# --- merging ---------------------------------------------------------------
def test_dry_run_changes_nothing(repo):
    sandbox = repo([
        ("08-databases", "a.md", "Redis Sorted Sets Use Skiplist", BODY_A, "databases"),
        ("08-databases", "b.md", "Redis Sorted Sets Internally Use A", BODY_B, "databases"),
    ])
    result = D.dedupe(apply=False)
    assert result["applied"] is False
    assert (sandbox / "08-databases" / "a.md").exists()
    assert (sandbox / "08-databases" / "b.md").exists()
    assert len(load_index()["notes"]) == 2


def test_apply_removes_duplicates_and_updates_index(repo):
    sandbox = repo([
        ("08-databases", "a.md", "Redis Sorted Sets Use Skiplist", BODY_A, "databases"),
        ("08-databases", "b.md", "Redis Sorted Sets Internally Use A", BODY_B, "databases"),
    ])
    result = D.dedupe(apply=True)
    assert result["duplicate_count"] == 1

    remaining = [n["filename"] for n in load_index()["notes"]]
    assert remaining == ["a.md"], "index row for the merged note must be removed"
    assert (sandbox / "08-databases" / "a.md").exists()
    assert not (sandbox / "08-databases" / "b.md").exists()


def test_merged_notes_are_archived_with_provenance(repo):
    sandbox = repo([
        ("08-databases", "a.md", "Redis Sorted Sets Use Skiplist", BODY_A, "databases"),
        ("08-databases", "b.md", "Redis Sorted Sets Internally Use A", BODY_B, "databases"),
    ])
    D.dedupe(apply=True, archive=True)
    archived = list((sandbox / "00-meta" / "merged").glob("*.md"))
    assert archived, "merged note should be recoverable"
    content = archived[0].read_text(encoding="utf-8")
    assert "Merged into" in content
    assert "Original path" in content


def test_no_archive_deletes_outright(repo):
    sandbox = repo([
        ("08-databases", "a.md", "Redis Sorted Sets Use Skiplist", BODY_A, "databases"),
        ("08-databases", "b.md", "Redis Sorted Sets Internally Use A", BODY_B, "databases"),
    ])
    D.dedupe(apply=True, archive=False)
    # An empty archive dir may linger from an earlier test; what matters is
    # that nothing was written into it.
    archived = list((sandbox / "00-meta" / "merged").glob("*.md"))
    assert archived == []
    assert not (sandbox / "08-databases" / "b.md").exists()


def test_empty_repo_is_safe(pristine_repo, write_index):
    write_index([])
    result = D.dedupe(apply=True)
    assert result["cluster_count"] == 0


def test_missing_files_are_skipped(pristine_repo, write_index):
    write_index([{"id": "1", "title": "Ghost", "folder_path": "x",
                  "filename": "ghost.md", "domain": "d", "type": "concept",
                  "tags": [], "date": "2026-01-01"}])
    assert D.find_duplicate_clusters() == []


# --- CLI safety ------------------------------------------------------------
def test_cli_defaults_to_dry_run(repo):
    from click.testing import CliRunner

    from jarvis import cli as C

    sandbox = repo([
        ("08-databases", "a.md", "Redis Sorted Sets Use Skiplist", BODY_A, "databases"),
        ("08-databases", "b.md", "Redis Sorted Sets Internally Use A", BODY_B, "databases"),
    ])
    result = CliRunner().invoke(C.cli, ["dedupe"])
    assert result.exit_code == 0
    assert "Nothing was changed" in result.output
    assert (sandbox / "08-databases" / "b.md").exists(), "dry run must not delete"
