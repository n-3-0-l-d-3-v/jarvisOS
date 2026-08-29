"""Feature 12: Windows Task Scheduler wiring for the midnight + RSS jobs."""

import subprocess

from jarvis import scheduler as S
from jarvis import tasks as T


class _Result:
    returncode = 0
    stdout = "SUCCESS"
    stderr = ""


def _capture_cmd(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return captured


def test_daily_log_task_uses_correct_name_and_time(monkeypatch):
    captured = _capture_cmd(monkeypatch)
    S.setup_scheduler()
    cmd = captured["cmd"]
    assert "JarvisDailyLog" in cmd
    assert "23:59" in cmd
    assert "daily" in cmd
    assert any("jarvis.tasks finalize" in str(part) for part in cmd)


def test_rss_task_uses_correct_name_and_default_time(monkeypatch):
    captured = _capture_cmd(monkeypatch)
    S.setup_rss_scheduler()
    cmd = captured["cmd"]
    assert "JarvisRSS" in cmd
    assert "08:00" in cmd
    assert any("jarvis.tasks rss" in str(part) for part in cmd)


def test_rss_task_accepts_custom_time(monkeypatch):
    captured = _capture_cmd(monkeypatch)
    S.setup_rss_scheduler("06:30")
    assert "06:30" in captured["cmd"]


def test_scheduler_reports_failure_without_raising(monkeypatch):
    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "Access denied"

    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: _Fail())
    message = S.setup_scheduler()
    assert "Failed" in message and "Access denied" in message


def test_scheduler_survives_exception(monkeypatch):
    def _boom(*a, **k):
        raise OSError("schtasks missing")
    monkeypatch.setattr(subprocess, "run", _boom)
    assert "Failed" in S.setup_scheduler()


# --- tasks.py routing ------------------------------------------------------
def test_tasks_routes_finalize(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["tasks", "finalize"])
    monkeypatch.setattr(T, "finalize_log", lambda: "finalized ok", raising=False)
    monkeypatch.setattr(T, "generate_weekly_summary", lambda: "w", raising=False)
    T.main()
    assert "finalized ok" in capsys.readouterr().out


def test_tasks_routes_rss(monkeypatch, capsys):
    import jarvis.rss_processor as R
    monkeypatch.setattr("sys.argv", ["tasks", "rss"])
    monkeypatch.setattr(R, "process_feeds",
                        lambda: {"fetched": 10, "new": 3, "saved": 1},
                        raising=False)
    T.main()
    out = capsys.readouterr().out
    assert "saved 1" in out


def test_tasks_shows_usage_for_unknown_command(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["tasks", "bogus"])
    T.main()
    assert "Usage" in capsys.readouterr().out


def test_curator_task_scheduled_at_night(monkeypatch):
    """A cycle makes AI calls and rewrites pages; keep it off peak hours."""
    captured = _capture_cmd(monkeypatch)
    S.setup_curator_scheduler()
    cmd = captured["cmd"]
    assert "JarvisCurator" in cmd
    assert "03:00" in cmd
    assert any("jarvis.tasks curate" in str(part) for part in cmd)


def test_tasks_routes_curate(monkeypatch, capsys):
    import jarvis.curator as CUR
    monkeypatch.setattr("sys.argv", ["tasks", "curate"])
    monkeypatch.setattr(
        CUR, "run_cycle",
        lambda dry_run=False: {"entries": [{"done": True}, {"done": False}],
                               "cycles": 3, "score_before": 80,
                               "score_after": 90, "next": "x"},
        raising=False)
    T.main()
    out = capsys.readouterr().out
    assert "cycle 3" in out and "1 action(s) applied" in out
