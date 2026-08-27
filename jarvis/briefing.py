"""
Daily briefing (`jar daily`).

The habit problem: capture has a natural trigger (you just learned something)
but *reading* your knowledge base has none, so a second brain quietly becomes
write-only. The live repo showed exactly that shape — 106 notes in one 4-day
burst, then weeks of silence.

This gives the system one reason to be opened every morning: what you did
yesterday, what you're about to forget, and one concrete next action. It is
deliberately short — a briefing you scroll past is the same as no briefing.

Everything is computed from index.json and review.json; nothing new to maintain.
"""

from datetime import date, datetime, timedelta

from jarvis.index_store import load_index

# How far back to look for the "recently quiet" gap hint.
GAP_WINDOW_DAYS = 21


def _unique_notes():
    seen = {}
    for note in load_index().get("notes", []):
        key = (note.get("folder_path", ""), note.get("filename", ""))
        seen.setdefault(key, note)
    return list(seen.values())


def _parse(iso):
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def capture_streak(notes, today=None):
    """Consecutive days (ending today or yesterday) with at least one capture.

    Yesterday still counts so the streak isn't reported as broken simply
    because you haven't captured yet this morning.
    """
    today = today or date.today()
    days = {d for d in (_parse(n.get("date")) for n in notes) if d}
    if not days:
        return {"current": 0, "longest": 0, "active_days": 0}

    current = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    longest, run, previous = 0, 0, None
    for day in sorted(days):
        run = run + 1 if previous and (day - previous).days == 1 else 1
        longest = max(longest, run)
        previous = day

    return {"current": current, "longest": longest, "active_days": len(days)}


def _recent_captures(notes, since, until):
    out = []
    for note in notes:
        day = _parse(note.get("date"))
        if day and since <= day <= until:
            out.append(note)
    return out


def build_briefing(target_date=None, max_items=5):
    """Assemble the briefing. Returns a plain dict; rendering lives in the CLI."""
    today = target_date or date.today()
    yesterday = today - timedelta(days=1)
    notes = _unique_notes()

    captured_today = _recent_captures(notes, today, today)
    captured_yesterday = _recent_captures(notes, yesterday, yesterday)

    # Spaced repetition — the main "read" prompt.
    try:
        from jarvis.review import due_notes, review_stats

        due = due_notes(limit=max_items)
        review_summary = review_stats()
    except Exception:
        due, review_summary = [], {"tracked": 0, "mastered": 0, "due": 0}

    # One concrete next action, in priority order.
    actions = []
    try:
        from jarvis.wiki import suggest_topics

        clusters = suggest_topics(min_size=3)
        # Skip topics that already have a synthesized page.
        existing = {
            n.get("subdomain") for n in notes if n.get("type") == "wiki"
        }
        clusters = [c for c in clusters if c["topic"] not in existing]
        if clusters:
            top = clusters[0]
            actions.append({
                "kind": "synthesize",
                "text": (f"{top['count']} scattered notes on '{top['topic']}' — "
                         f"run: jar wiki \"{top['topic']}\""),
            })
    except Exception:
        pass

    if due:
        actions.append({
            "kind": "review",
            "text": f"{review_summary.get('due', len(due))} note(s) due — run: jar review",
        })

    # A domain you were active in but have gone quiet on.
    window_start = today - timedelta(days=GAP_WINDOW_DAYS)
    recent_domains = {
        n.get("domain") for n in _recent_captures(notes, window_start, today)
    }
    all_domains = {n.get("domain") for n in notes if n.get("domain")}
    quiet = sorted(d for d in all_domains - recent_domains if d)
    if quiet:
        actions.append({
            "kind": "gap",
            "text": f"No captures in {GAP_WINDOW_DAYS}d for: {', '.join(quiet[:4])}",
        })

    streak = capture_streak(notes, today)

    return {
        "date": today.isoformat(),
        "today_count": len(captured_today),
        "yesterday": [
            {"title": n.get("title", "Untitled"), "domain": n.get("domain", ""),
             "type": n.get("type", "")}
            for n in captured_yesterday[:max_items]
        ],
        "yesterday_count": len(captured_yesterday),
        "due": [
            {"title": d["title"], "domain": d["domain"],
             "overdue_days": d["overdue_days"]}
            for d in due
        ],
        "review": review_summary,
        "streak": streak,
        "total_notes": len(notes),
        "actions": actions[:3],
    }
