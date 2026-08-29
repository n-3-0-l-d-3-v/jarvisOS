"""
Autonomous curator (`jar curate`) — the knowledge base maintains itself.

Synthesises two patterns:

  * The LLM Wiki's third operation. Ingest and Query were already built; the
    missing one is **Lint** — periodically checking for contradictions, stale
    claims, orphan pages and missing cross-references.
  * Hermes's closed loop: observe -> plan -> act -> journal, where the agent
    gets more useful the longer it runs because each cycle records what it did
    and what it deferred.

Why an external clock rather than agent initiative: a rule that exists is not a
rule that runs. The live repo went 106 notes in four days, then silent for
weeks, with nothing consolidating or repairing in between. Maintenance only
happens if something triggers it on a schedule.

SAFETY MODEL — the part that matters most in an autonomous loop:

  SAFE     additive or repairing, runs unattended (linking, reindexing,
           collapsing duplicate index rows, synthesising wiki pages)
  REVIEW   destructive or judgement-heavy, NEVER auto-runs. It is proposed in
           the report and the journal, and needs an explicit human command.

Deleting notes is permanently in REVIEW. An autonomous loop that can silently
delete your knowledge is not a feature.
"""

import json
from datetime import date, datetime

from jarvis.config import REPO_PATH

CURATOR_LOG = REPO_PATH / "00-meta" / "curator-log.md"
CURATOR_STATE = REPO_PATH / "00-meta" / "curator-state.json"

SAFE = "safe"
REVIEW = "review"

# A topic needs enough material to be worth rewriting its page.
SYNTH_MIN_CLUSTER = 3
# Cap work per cycle so an unattended run cannot spend an unbounded number of
# AI calls or take an unbounded amount of time.
MAX_SYNTH_PER_CYCLE = 2


# --------------------------------------------------------------------------- #
# State + journal
# --------------------------------------------------------------------------- #
def load_state():
    try:
        if CURATOR_STATE.exists():
            data = json.loads(CURATOR_STATE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("cycles", 0)
                data.setdefault("synthesized", [])
                data.setdefault("next", "")
                return data
    except Exception:
        pass
    return {"cycles": 0, "last_run": "", "synthesized": [], "next": ""}


def save_state(state):
    CURATOR_STATE.parent.mkdir(parents=True, exist_ok=True)
    CURATOR_STATE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def journal(entries, state):
    """Append one dated block to the curator log (append-only, like wiki/log.md)."""
    CURATOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["", f"## [{stamp}] cycle {state.get('cycles', 0)}"]
    if not entries:
        lines.append("- nothing to do")
    for item in entries:
        mark = "x" if item.get("done") else " "
        lines.append(f"- [{mark}] {item['action']}: {item['detail']}"
                     f" -> {item.get('result', '')}")
    if state.get("next"):
        lines.append(f"- next: {state['next']}")
    existing = (CURATOR_LOG.read_text(encoding="utf-8")
                if CURATOR_LOG.exists() else "# Curator Log\n")
    CURATOR_LOG.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Observe
# --------------------------------------------------------------------------- #
def observe():
    """Gather everything the planner needs. Read-only."""
    from jarvis.health import check_health, health_score

    findings = check_health()
    observation = {
        "health": findings,
        "score": health_score(findings),
        "clusters": [],
        "duplicates": [],
    }

    try:
        from jarvis.wiki import suggest_topics

        state = load_state()
        done = set(state.get("synthesized", []))
        clusters = suggest_topics(min_size=SYNTH_MIN_CLUSTER)
        # A topic already synthesised is revisited only once it has grown,
        # so the key carries the size it was synthesised at.
        observation["clusters"] = [
            c for c in clusters
            if f"{c['topic']}:{c['count']}" not in done
        ]
    except Exception:
        pass

    try:
        from jarvis.dedupe import find_duplicate_clusters

        observation["duplicates"] = find_duplicate_clusters()
    except Exception:
        pass

    return observation


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
def plan(observation):
    """Turn observations into a prioritised action list.

    Repairs come before enrichment: synthesising a page from a broken index
    just bakes the breakage into a wiki page.
    """
    actions = []
    health = observation["health"]

    if health["duplicate_rows"]:
        actions.append({
            "action": "dedupe_index", "tier": SAFE,
            "detail": f"collapse {len(health['duplicate_rows'])} duplicate index row(s)",
        })

    if health["untracked_files"]:
        actions.append({
            "action": "reindex", "tier": SAFE,
            "detail": f"index {len(health['untracked_files'])} unindexed note(s)",
        })

    if health["missing_files"]:
        actions.append({
            "action": "clean_index", "tier": SAFE,
            "detail": f"drop {len(health['missing_files'])} row(s) whose file is gone",
        })

    if health["broken_links"] or health["orphan_notes"]:
        actions.append({
            "action": "relink", "tier": SAFE,
            "detail": (f"{len(health['broken_links'])} broken link(s), "
                       f"{len(health['orphan_notes'])} orphan note(s)"),
        })

    for cluster in observation["clusters"][:MAX_SYNTH_PER_CYCLE]:
        actions.append({
            "action": "synthesize", "tier": SAFE,
            "topic": cluster["topic"], "count": cluster["count"],
            "detail": f"merge {cluster['count']} notes on '{cluster['topic']}'",
        })

    # Destructive work is proposed, never performed.
    if observation["duplicates"]:
        total = sum(len(c["duplicates"]) for c in observation["duplicates"])
        actions.append({
            "action": "merge_duplicates", "tier": REVIEW,
            "detail": (f"{total} near-duplicate note(s) in "
                       f"{len(observation['duplicates'])} cluster(s)"
                       f" — run: jar dedupe --apply"),
        })

    if health["empty_notes"]:
        actions.append({
            "action": "fill_empty", "tier": REVIEW,
            "detail": (f"{len(health['empty_notes'])} note(s) are scaffolding only"
                       f" — fill or delete them"),
        })

    return actions


# --------------------------------------------------------------------------- #
# Act
# --------------------------------------------------------------------------- #
def act(action, state):
    """Execute one SAFE action. REVIEW actions are never executed here."""
    if action["tier"] != SAFE:
        return {"done": False, "result": "deferred to human"}

    name = action["action"]
    try:
        if name == "dedupe_index":
            from jarvis.index_store import dedupe_index

            out = dedupe_index()
            return {"done": True, "result": f"removed {out['removed']} row(s)"}

        if name == "reindex":
            from jarvis.health import reindex

            out = reindex()
            return {"done": True, "result": f"indexed {len(out['added'])} note(s)"}

        if name == "clean_index":
            from jarvis.index_cleaner import clean_index

            out = clean_index()
            return {"done": True, "result": f"removed {out['removed']} stale row(s)"}

        if name == "relink":
            from jarvis.linker import run_linker

            out = run_linker(verbose=False)
            return {"done": True, "result": f"linked {out['linked']} note(s)"}

        if name == "synthesize":
            from jarvis.wiki import build_index, synthesize_topic

            out = synthesize_topic(action["topic"])
            if out["count"]:
                build_index()
                state.setdefault("synthesized", []).append(
                    f"{action['topic']}:{action['count']}"
                )
                how = "ai" if out["used_ai"] else "fallback"
                return {"done": True,
                        "result": f"merged {out['count']} notes ({how})"}
            return {"done": False, "result": "no notes matched"}

    except Exception as exc:
        return {"done": False, "result": f"failed: {str(exc)[:120]}"}

    return {"done": False, "result": "unknown action"}


# --------------------------------------------------------------------------- #
# The cycle
# --------------------------------------------------------------------------- #
def run_cycle(dry_run=False, max_actions=8):
    """One observe -> plan -> act -> journal tick."""
    state = load_state()
    observation = observe()
    actions = plan(observation)[:max_actions]

    entries = []
    for action in actions:
        if dry_run or action["tier"] != SAFE:
            entries.append({
                "action": action["action"], "tier": action["tier"],
                "detail": action["detail"], "done": False,
                "result": "proposed" if dry_run else "needs approval",
            })
            continue
        outcome = act(action, state)
        entries.append({
            "action": action["action"], "tier": action["tier"],
            "detail": action["detail"], "done": outcome["done"],
            "result": outcome["result"],
        })

    did_work = any(e["done"] for e in entries)
    after = observe() if (not dry_run and did_work) else observation

    # The next directive: what the following tick should look at first.
    pending = [e for e in entries if not e["done"]]
    state["next"] = (pending[0]["detail"] if pending
                     else "no outstanding maintenance")

    if not dry_run:
        state["cycles"] = state.get("cycles", 0) + 1
        state["last_run"] = date.today().isoformat()
        save_state(state)
        journal(entries, state)

    return {
        "entries": entries,
        "score_before": observation["score"],
        "score_after": after["score"],
        "cycles": state.get("cycles", 0),
        "next": state["next"],
        "dry_run": dry_run,
    }
