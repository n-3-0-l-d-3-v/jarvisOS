"""Feature 22: learning analytics + categorical palette safety."""

from datetime import date, timedelta

import pytest

from jarvis import analytics as A
from jarvis import graph_view as GV

TODAY = date(2026, 8, 27)


def _row(i, day, domain="databases", ntype="concept", pattern=""):
    row = {"id": f"n{i}", "title": f"Note {i}", "folder_path": "08-databases",
           "filename": f"note-{i}.md", "domain": domain, "subdomain": "redis",
           "tags": ["redis"], "type": ntype, "date": day.isoformat()}
    if pattern:
        row["pattern"] = pattern
    return row


@pytest.fixture
def seeded(pristine_repo, write_index):
    def _write(rows):
        for r in rows:
            p = pristine_repo / r["folder_path"]
            p.mkdir(parents=True, exist_ok=True)
            (p / r["filename"]).write_text("# n\n\nbody", encoding="utf-8")
        write_index(rows)
        return pristine_repo
    return _write


# --- timeline --------------------------------------------------------------
def test_timeline_is_zero_filled_for_the_window(seeded):
    seeded([_row(0, TODAY)])
    a = A.build_analytics(days=30, today=TODAY)
    assert len(a["timeline"]) == 30, "gaps must be visible, not omitted"
    assert a["timeline"][-1]["count"] == 1
    assert a["timeline"][0]["count"] == 0


def test_timeline_buckets_by_day(seeded):
    seeded([_row(0, TODAY), _row(1, TODAY), _row(2, TODAY - timedelta(days=2))])
    a = A.build_analytics(days=7, today=TODAY)
    counts = {r["date"]: r["count"] for r in a["timeline"]}
    assert counts[TODAY.isoformat()] == 2
    assert counts[(TODAY - timedelta(days=2)).isoformat()] == 1


def test_timeline_excludes_notes_outside_window(seeded):
    seeded([_row(0, TODAY - timedelta(days=90))])
    a = A.build_analytics(days=30, today=TODAY)
    assert sum(r["count"] for r in a["timeline"]) == 0
    assert a["totals"]["notes"] == 1, "still counted in the total"


def test_timeline_rows_are_ordered(seeded):
    seeded([_row(0, TODAY)])
    dates = [r["date"] for r in A.build_analytics(days=10, today=TODAY)["timeline"]]
    assert dates == sorted(dates)


# --- domains / types -------------------------------------------------------
def test_domains_ranked_by_count(seeded):
    seeded([_row(0, TODAY, domain="dsa"), _row(1, TODAY, domain="dsa"),
            _row(2, TODAY, domain="devops")])
    domains = A.build_analytics(today=TODAY)["domains"]
    assert domains[0]["name"] == "dsa" and domains[0]["count"] == 2


def test_types_are_counted(seeded):
    seeded([_row(0, TODAY, ntype="dsa"), _row(1, TODAY, ntype="article")])
    names = {t["name"] for t in A.build_analytics(today=TODAY)["types"]}
    assert {"dsa", "article"} <= names


# --- DSA pattern coverage --------------------------------------------------
def test_all_patterns_listed_including_zeros(seeded):
    """Uncovered patterns are the useful signal — they must not be dropped."""
    seeded([_row(0, TODAY, ntype="dsa", pattern="sliding-window")])
    a = A.build_analytics(today=TODAY)
    assert len(a["patterns"]) == len(A.DSA_PATTERNS)
    by_name = {p["name"]: p["count"] for p in a["patterns"]}
    assert by_name["sliding-window"] == 1
    assert by_name["tries"] == 0
    assert a["totals"]["patterns_covered"] == 1


def test_non_dsa_notes_do_not_count_toward_patterns(seeded):
    seeded([_row(0, TODAY, ntype="concept", pattern="sliding-window")])
    assert A.build_analytics(today=TODAY)["totals"]["patterns_covered"] == 0


def test_dsa_pattern_falls_back_to_dsa_pattern_field(seeded, write_index, pristine_repo):
    row = _row(0, TODAY, ntype="dsa")
    row["dsa_pattern"] = "greedy"
    p = pristine_repo / row["folder_path"]
    p.mkdir(parents=True, exist_ok=True)
    (p / row["filename"]).write_text("# n", encoding="utf-8")
    write_index([row])
    by_name = {x["name"]: x["count"] for x in A.build_analytics(today=TODAY)["patterns"]}
    assert by_name["greedy"] == 1


# --- totals ----------------------------------------------------------------
def test_totals_dedupe_index_rows(seeded, write_index, pristine_repo):
    row = _row(0, TODAY)
    p = pristine_repo / row["folder_path"]
    p.mkdir(parents=True, exist_ok=True)
    (p / row["filename"]).write_text("# n", encoding="utf-8")
    write_index([row, dict(row), dict(row)])
    assert A.build_analytics(today=TODAY)["totals"]["notes"] == 1


def test_empty_repo_produces_valid_shape(pristine_repo, write_index):
    write_index([])
    a = A.build_analytics(today=TODAY)
    assert a["totals"]["notes"] == 0
    assert len(a["timeline"]) == 30
    assert a["domains"] == []
    assert len(a["patterns"]) == len(A.DSA_PATTERNS)


def test_active_days_in_window(seeded):
    seeded([_row(0, TODAY), _row(1, TODAY - timedelta(days=1)),
            _row(2, TODAY - timedelta(days=1))])
    assert A.build_analytics(days=30, today=TODAY)["totals"]["active_last_n"] == 2


# --- categorical palette safety -------------------------------------------
def test_palette_is_capped_at_eight():
    """A generated 9th hue is indistinguishable under CVD — the tail folds."""
    assert len(GV._PALETTE) == GV.MAX_DOMAIN_COLOURS == 8


def test_palette_has_no_duplicate_hues():
    assert len(set(GV._PALETTE)) == len(GV._PALETTE)


def test_domains_beyond_ceiling_fold_into_other(seeded):
    rows = []
    for i in range(11):
        r = _row(i, TODAY, domain=f"domain{i:02d}")
        r["folder_path"] = f"d{i:02d}"
        r["filename"] = f"n{i}.md"
        rows.append(r)
    seeded(rows)
    graph = GV.build_graph()
    legend = [d["domain"] for d in graph["domains"]]
    assert len(legend) <= GV.MAX_DOMAIN_COLOURS + 1
    assert GV._OTHER_LABEL in legend
    colours = [d["colour"] for d in graph["domains"] if d["domain"] != GV._OTHER_LABEL]
    assert len(set(colours)) == len(colours), "no two domains may share a hue"


def test_largest_domains_get_the_colours(seeded):
    rows = [_row(i, TODAY, domain="dsa") for i in range(5)]
    for i, r in enumerate(rows):
        r["filename"] = f"dsa-{i}.md"
    rare = _row(99, TODAY, domain="rare-domain")
    rare["filename"] = "rare.md"
    seeded(rows + [rare])
    graph = GV.build_graph()
    assert graph["domains"][0]["domain"] == "dsa"


def test_every_node_has_a_colour(seeded):
    rows = []
    for i in range(12):
        r = _row(i, TODAY, domain=f"d{i}")
        r["folder_path"] = f"f{i}"
        r["filename"] = f"n{i}.md"
        rows.append(r)
    seeded(rows)
    for node in GV.build_graph()["nodes"]:
        assert node["colour"].startswith("#")
        assert node["legend"]


# --- API -------------------------------------------------------------------
def test_analytics_endpoint(seeded):
    from fastapi.testclient import TestClient

    from jarvis.api_server import app

    seeded([_row(0, TODAY)])
    body = TestClient(app).get("/api/analytics").json()
    assert "timeline" in body and "totals" in body and "patterns" in body
