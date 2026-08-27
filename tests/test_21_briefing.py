"""Feature 21: the daily briefing."""

from datetime import date, timedelta

import pytest

from jarvis import briefing as B

TODAY = date(2026, 8, 27)


def _row(i, day, domain="databases", ntype="concept", sub="redis"):
    return {"id": f"n{i}", "title": f"Note {i}", "folder_path": "08-databases",
            "filename": f"note-{i}.md", "domain": domain, "subdomain": sub,
            "tags": ["redis"], "type": ntype, "date": day.isoformat()}


# --- streak ----------------------------------------------------------------
def test_streak_counts_consecutive_days():
    notes = [_row(i, TODAY - timedelta(days=i)) for i in range(4)]
    assert B.capture_streak(notes, TODAY)["current"] == 4


def test_streak_tolerates_not_having_captured_yet_today():
    """Starting from yesterday keeps the streak alive before you capture."""
    notes = [_row(i, TODAY - timedelta(days=i)) for i in range(1, 4)]
    assert B.capture_streak(notes, TODAY)["current"] == 3


def test_streak_breaks_on_a_gap():
    notes = [_row(0, TODAY), _row(1, TODAY - timedelta(days=3))]
    assert B.capture_streak(notes, TODAY)["current"] == 1


def test_longest_streak_is_tracked_separately():
    days = [0, 5, 6, 7, 8]  # a 4-day run in the past
    notes = [_row(i, TODAY - timedelta(days=d)) for i, d in enumerate(days)]
    result = B.capture_streak(notes, TODAY)
    assert result["current"] == 1
    assert result["longest"] == 4


def test_streak_handles_empty_and_bad_dates():
    assert B.capture_streak([])["current"] == 0
    bad = [{"date": "not-a-date"}, {"date": None}]
    assert B.capture_streak(bad, TODAY)["current"] == 0


def test_duplicate_days_count_once():
    notes = [_row(0, TODAY), _row(1, TODAY), _row(2, TODAY)]
    assert B.capture_streak(notes, TODAY)["active_days"] == 1


# --- briefing --------------------------------------------------------------
@pytest.fixture
def seeded(pristine_repo, write_index):
    rows = [
        _row(0, TODAY),
        _row(1, TODAY - timedelta(days=1)),
        _row(2, TODAY - timedelta(days=1), domain="dsa", sub="arrays"),
    ]
    for r in rows:
        p = pristine_repo / r["folder_path"]
        p.mkdir(parents=True, exist_ok=True)
        (p / r["filename"]).write_text(f"# {r['title']}\n\nbody", encoding="utf-8")
    write_index(rows)
    return pristine_repo


def test_briefing_splits_today_and_yesterday(seeded):
    b = B.build_briefing(target_date=TODAY)
    assert b["today_count"] == 1
    assert b["yesterday_count"] == 2
    assert b["date"] == TODAY.isoformat()


def test_briefing_reports_totals_and_streak(seeded):
    b = B.build_briefing(target_date=TODAY)
    assert b["total_notes"] == 3
    assert b["streak"]["current"] >= 1


def test_briefing_surfaces_due_reviews(seeded):
    b = B.build_briefing(target_date=TODAY)
    assert isinstance(b["due"], list)
    for item in b["due"]:
        assert "title" in item and "overdue_days" in item


def test_briefing_suggests_actions(seeded):
    b = B.build_briefing(target_date=TODAY)
    assert isinstance(b["actions"], list)
    assert len(b["actions"]) <= 3
    for action in b["actions"]:
        assert action["kind"] in {"synthesize", "review", "gap"}
        assert action["text"]


def test_briefing_on_empty_repo_does_not_crash(pristine_repo, write_index):
    write_index([])
    b = B.build_briefing(target_date=TODAY)
    assert b["total_notes"] == 0
    assert b["yesterday"] == [] and b["due"] == []
    assert b["streak"]["current"] == 0


def test_briefing_caps_list_lengths(pristine_repo, write_index):
    rows = [_row(i, TODAY - timedelta(days=1)) for i in range(20)]
    for r in rows:
        p = pristine_repo / r["folder_path"]
        p.mkdir(parents=True, exist_ok=True)
        (p / r["filename"]).write_text("# n\n\nbody", encoding="utf-8")
    write_index(rows)
    b = B.build_briefing(target_date=TODAY, max_items=5)
    assert len(b["yesterday"]) == 5
    assert b["yesterday_count"] == 20, "count should reflect the true total"


def test_briefing_deduplicates_index_rows(pristine_repo, write_index):
    row = _row(0, TODAY)
    p = pristine_repo / row["folder_path"]
    p.mkdir(parents=True, exist_ok=True)
    (p / row["filename"]).write_text("# n\n\nbody", encoding="utf-8")
    write_index([row, dict(row), dict(row)])
    assert B.build_briefing(target_date=TODAY)["total_notes"] == 1


# --- CLI + MCP -------------------------------------------------------------
def test_daily_command_runs(seeded):
    from click.testing import CliRunner

    from jarvis import cli as C

    result = CliRunner().invoke(C.cli, ["daily"])
    assert result.exit_code == 0, result.output
    assert "streak" in result.output.lower()


def test_mcp_exposes_daily_briefing():
    import asyncio

    from jarvis.mcp_server import server

    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "daily_briefing" in names
