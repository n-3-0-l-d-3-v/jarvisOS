"""Feature 4: the daily engineering journal (the original ISSUE 1 area)."""

import datetime

from jarvis import daily_log as D

DAY = datetime.date(2026, 7, 22)


def test_get_log_path_builds_year_month_structure(sandbox):
    path = D.get_log_path(DAY)
    assert path == sandbox / "daily-logs" / "2026" / "07" / "2026-07-22.md"


def test_get_log_path_creates_parent_dirs(sandbox):
    """ISSUE 1 regression: the YYYY/MM folders must be created."""
    path = D.get_log_path(datetime.date(2027, 3, 9))
    assert path.parent.exists(), "daily-logs/YYYY/MM was not created"


def test_ensure_log_exists_creates_file_with_all_sections():
    path = D.ensure_log_exists(DAY)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    for section in ("## Summary", "## Captured Notes", "## Technologies Used",
                    "## Domains Covered", "## LeetCode / DSA", "## Bugs Fixed",
                    "## Key Learnings", "## Tomorrow"):
        assert section in content, f"missing {section}"


def test_append_to_log_writes_into_captured_notes():
    D.ensure_log_exists(DAY)
    path = D.append_to_log("redis persistence deep dive", "cli", "",
                           "concept", {"domain": "databases"}, target_date=DAY)
    content = path.read_text(encoding="utf-8")
    captured = content.split("## Captured Notes")[1].split("##")[0]
    assert "redis persistence deep dive" in captured


def test_dsa_note_also_lands_in_dsa_section():
    path = D.append_to_log("LC-76 minimum window", "leetcode", "",
                           "dsa", {"domain": "dsa"}, target_date=DAY)
    content = path.read_text(encoding="utf-8")
    dsa_section = content.split("## LeetCode / DSA")[1].split("##")[0]
    assert "LC-76" in dsa_section


def test_bug_note_also_lands_in_bugs_section():
    path = D.append_to_log("fixed CORS preflight failure", "cli", "",
                           "bug", {"domain": "backend"}, target_date=DAY)
    content = path.read_text(encoding="utf-8")
    bugs = content.split("## Bugs Fixed")[1].split("##")[0]
    assert "CORS" in bugs


def test_source_url_is_linked_in_entry():
    path = D.append_to_log("great article", "article", "https://ex.com/x",
                           "article", {"domain": "backend"}, target_date=DAY)
    assert "https://ex.com/x" in path.read_text(encoding="utf-8")


def test_update_technologies_records_and_dedupes():
    cls = {"domain": "devops", "subdomain": "docker", "tags": ["docker", "compose"]}
    D.update_technologies(cls, target_date=DAY)
    D.update_technologies(cls, target_date=DAY)  # repeat must not duplicate
    content = D.get_log_path(DAY).read_text(encoding="utf-8")
    tech = content.split("## Technologies Used")[1].split("##")[0]
    assert tech.count("- docker") == 1, "technology was duplicated"
    domains = content.split("## Domains Covered")[1].split("##")[0]
    assert "devops" in domains


def test_appending_twice_creates_two_distinct_entries():
    day = datetime.date(2026, 7, 23)
    D.ensure_log_exists(day)
    D.append_to_log("first note", "cli", "", "concept", {}, target_date=day)
    D.append_to_log("second note", "cli", "", "concept", {}, target_date=day)
    captured = D.get_log_path(day).read_text(encoding="utf-8") \
        .split("## Captured Notes")[1].split("##")[0]
    assert "first note" in captured and "second note" in captured


def test_get_week_logs_returns_seven_days():
    week = D.get_week_logs(DAY)
    assert len(week) == 7
    assert week[-1]["date"] == DAY.isoformat()


def test_fallback_summary_works_without_ai():
    """finalize must degrade gracefully when no AI key is available."""
    content = D.get_log_path(DAY).read_text(encoding="utf-8")
    summary = D._fallback_daily_summary(content)
    assert isinstance(summary, str) and len(summary) > 0
