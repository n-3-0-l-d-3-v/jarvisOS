"""
Feature 24: the autonomous curator.

The safety tier is the most important thing under test here. An unattended loop
that can delete notes is a liability, so several tests exist purely to pin the
rule that destructive work is proposed and never performed.
"""

import json

import pytest

from jarvis import curator as C


@pytest.fixture
def repo(pristine_repo, write_index, monkeypatch):
    monkeypatch.setattr(C, "CURATOR_LOG",
                        pristine_repo / "00-meta" / "curator-log.md", raising=False)
    monkeypatch.setattr(C, "CURATOR_STATE",
                        pristine_repo / "00-meta" / "curator-state.json", raising=False)
    (pristine_repo / "00-meta" / "curator-log.md").unlink(missing_ok=True)
    (pristine_repo / "00-meta" / "curator-state.json").unlink(missing_ok=True)

    def _make(specs):
        rows = []
        for folder, fn, title, body in specs:
            p = pristine_repo / folder
            p.mkdir(parents=True, exist_ok=True)
            (p / fn).write_text(
                f"---\ntitle: {title}\ndomain: databases\n---\n# {title}\n\n{body}\n",
                encoding="utf-8")
            rows.append({"id": fn[:6], "title": title, "folder_path": folder,
                         "filename": fn, "domain": "databases",
                         "subdomain": "redis", "tags": ["redis"],
                         "type": "concept", "date": "2026-01-01"})
        write_index(rows)
        return pristine_repo
    return _make


HEALTHY = ("Redis persists data with RDB snapshots and AOF logs, which is "
           "plenty of genuine content to avoid the empty-note detector.")


# --- safety tiers (the critical contract) ---------------------------------
def test_destructive_actions_are_review_tier():
    """merge_duplicates and fill_empty must never be auto-runnable."""
    observation = {
        "health": {"duplicate_rows": [], "untracked_files": [],
                   "missing_files": [], "broken_links": [], "orphan_notes": [],
                   "empty_notes": [{"file": "x"}]},
        "clusters": [],
        "duplicates": [{"keep": {}, "duplicates": [{}], "scores": [0.9]}],
    }
    tiers = {a["action"]: a["tier"] for a in C.plan(observation)}
    assert tiers["merge_duplicates"] == C.REVIEW
    assert tiers["fill_empty"] == C.REVIEW


def test_act_refuses_review_tier_actions():
    result = C.act({"action": "merge_duplicates", "tier": C.REVIEW}, {})
    assert result["done"] is False
    assert "human" in result["result"]


def test_review_actions_never_execute_in_a_cycle(repo, monkeypatch):
    """Even in --apply mode, a REVIEW action must not run."""
    repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    called = {"merged": False}

    def _boom(*a, **k):
        called["merged"] = True
        raise AssertionError("destructive action was executed autonomously")

    monkeypatch.setattr("jarvis.dedupe.dedupe", _boom, raising=False)
    monkeypatch.setattr(C, "plan", lambda obs: [
        {"action": "merge_duplicates", "tier": C.REVIEW, "detail": "d"}
    ], raising=False)

    result = C.run_cycle(dry_run=False)
    assert called["merged"] is False
    assert result["entries"][0]["done"] is False


def test_repairs_are_planned_before_enrichment():
    """A wiki page built on a broken index bakes in the breakage."""
    observation = {
        "health": {"duplicate_rows": [{"file": "x", "count": 2}],
                   "untracked_files": [], "missing_files": [],
                   "broken_links": [], "orphan_notes": [], "empty_notes": []},
        "clusters": [{"topic": "redis", "count": 5}],
        "duplicates": [],
    }
    order = [a["action"] for a in C.plan(observation)]
    assert order.index("dedupe_index") < order.index("synthesize")


def test_synthesis_is_capped_per_cycle():
    observation = {
        "health": {"duplicate_rows": [], "untracked_files": [],
                   "missing_files": [], "broken_links": [], "orphan_notes": [],
                   "empty_notes": []},
        "clusters": [{"topic": f"t{i}", "count": 5} for i in range(10)],
        "duplicates": [],
    }
    synth = [a for a in C.plan(observation) if a["action"] == "synthesize"]
    assert len(synth) == C.MAX_SYNTH_PER_CYCLE


# --- dry run ---------------------------------------------------------------
def test_dry_run_changes_nothing(repo):
    sandbox = repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    result = C.run_cycle(dry_run=True)
    assert result["dry_run"] is True
    assert all(not e["done"] for e in result["entries"])
    assert not (sandbox / "00-meta" / "curator-state.json").exists()
    assert not (sandbox / "00-meta" / "curator-log.md").exists()


# --- journal + state -------------------------------------------------------
def test_cycle_writes_journal_and_state(repo):
    sandbox = repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    C.run_cycle(dry_run=False)

    state = json.loads(
        (sandbox / "00-meta" / "curator-state.json").read_text(encoding="utf-8"))
    assert state["cycles"] == 1
    assert state["last_run"]

    log = (sandbox / "00-meta" / "curator-log.md").read_text(encoding="utf-8")
    assert "cycle 1" in log


def test_journal_is_append_only(repo):
    sandbox = repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    C.run_cycle(dry_run=False)
    C.run_cycle(dry_run=False)
    log = (sandbox / "00-meta" / "curator-log.md").read_text(encoding="utf-8")
    assert "cycle 1" in log and "cycle 2" in log


def test_cycle_counter_increments(repo):
    repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    assert C.run_cycle(dry_run=False)["cycles"] == 1
    assert C.run_cycle(dry_run=False)["cycles"] == 2


def test_next_directive_points_at_pending_work(repo, monkeypatch):
    repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    monkeypatch.setattr(C, "plan", lambda obs: [
        {"action": "fill_empty", "tier": C.REVIEW, "detail": "2 empty notes"}
    ], raising=False)
    assert "empty" in C.run_cycle(dry_run=False)["next"]


def test_next_is_clear_when_nothing_pending(repo, monkeypatch):
    repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    monkeypatch.setattr(C, "plan", lambda obs: [], raising=False)
    assert "no outstanding" in C.run_cycle(dry_run=False)["next"]


def test_state_survives_corruption(repo):
    sandbox = repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    (sandbox / "00-meta" / "curator-state.json").write_text("{ broken",
                                                            encoding="utf-8")
    state = C.load_state()
    assert state["cycles"] == 0


def test_synthesized_topics_are_remembered(repo, monkeypatch):
    repo([("08-databases", f"n{i}.md", f"Redis {i}", HEALTHY) for i in range(4)])
    monkeypatch.setattr("jarvis.wiki.synthesize_topic",
                        lambda topic, **k: {"count": 3, "used_ai": True,
                                            "path": "p", "sources": [],
                                            "topic": topic, "content": ""},
                        raising=False)
    monkeypatch.setattr("jarvis.wiki.build_index",
                        lambda: {"pages": 1, "path": "p"}, raising=False)
    state = {"synthesized": []}
    C.act({"action": "synthesize", "tier": C.SAFE, "topic": "redis",
           "count": 3, "detail": "d"}, state)
    assert "redis:3" in state["synthesized"]


# --- observe ---------------------------------------------------------------
def test_observe_is_read_only(repo):
    sandbox = repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    before = (sandbox / "08-databases" / "a.md").read_text(encoding="utf-8")
    C.observe()
    assert (sandbox / "08-databases" / "a.md").read_text(encoding="utf-8") == before


def test_observe_reports_a_score(repo):
    repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    observation = C.observe()
    assert 0 <= observation["score"] <= 100
    assert "health" in observation


def test_act_reports_failure_without_raising(monkeypatch):
    def _boom():
        raise RuntimeError("index exploded")
    monkeypatch.setattr("jarvis.index_store.dedupe_index", _boom, raising=False)
    result = C.act({"action": "dedupe_index", "tier": C.SAFE, "detail": "d"}, {})
    assert result["done"] is False
    assert "failed" in result["result"]


def test_unknown_action_is_handled():
    result = C.act({"action": "not_a_real_action", "tier": C.SAFE}, {})
    assert result["done"] is False


# --- CLI -------------------------------------------------------------------
def test_curate_cli_defaults_to_dry_run(repo):
    from click.testing import CliRunner

    from jarvis import cli as CLI

    sandbox = repo([("08-databases", "a.md", "Redis A", HEALTHY)])
    result = CliRunner().invoke(CLI.cli, ["curate"])
    assert result.exit_code == 0, result.output
    assert "Nothing was changed" in result.output or "good shape" in result.output
    assert not (sandbox / "00-meta" / "curator-state.json").exists()
