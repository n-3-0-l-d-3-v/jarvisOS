"""
Learning analytics for the dashboard.

Answers the questions the note list cannot: am I actually capturing
consistently, which domains am I neglecting, and how much DSA pattern coverage
do I have before an interview.

Every series here is SINGLE-series magnitude (counts per day, counts per
domain), which is a sequential encoding job — one hue, no categorical palette.
Identity colouring belongs to the knowledge graph, not to these bars.
"""

from datetime import date, datetime, timedelta

from jarvis.index_store import load_index

TIMELINE_DAYS = 30
TOP_DOMAINS = 10

# The 12 patterns the classifier recognises, so coverage shows real gaps
# (a pattern with zero notes is the useful signal here).
DSA_PATTERNS = [
    "sliding-window", "two-pointers", "binary-search", "dynamic-programming",
    "backtracking", "graphs", "trees", "heaps", "linked-lists", "stacks",
    "greedy", "tries",
]


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


def build_analytics(days=TIMELINE_DAYS, today=None):
    """Return every series the analytics panel needs."""
    today = today or date.today()
    notes = _unique_notes()

    # --- capture timeline: one bar per day, zero-filled so gaps are visible ---
    start = today - timedelta(days=days - 1)
    buckets = {start + timedelta(days=i): 0 for i in range(days)}
    for note in notes:
        day = _parse(note.get("date"))
        if day and start <= day <= today:
            buckets[day] += 1
    timeline = [
        {"date": d.isoformat(), "label": d.strftime("%d %b"), "count": c}
        for d, c in sorted(buckets.items())
    ]

    # --- domain magnitude ---
    domain_counts = {}
    for note in notes:
        key = note.get("domain") or "unclassified"
        domain_counts[key] = domain_counts.get(key, 0) + 1
    domains = [
        {"name": name, "count": count}
        for name, count in sorted(domain_counts.items(),
                                  key=lambda kv: (-kv[1], kv[0]))
    ][:TOP_DOMAINS]

    # --- note types ---
    type_counts = {}
    for note in notes:
        key = note.get("type") or "concept"
        type_counts[key] = type_counts.get(key, 0) + 1
    types = [
        {"name": name, "count": count}
        for name, count in sorted(type_counts.items(), key=lambda kv: -kv[1])
    ]

    # --- DSA pattern coverage (zeros included — the gaps are the point) ---
    pattern_counts = {p: 0 for p in DSA_PATTERNS}
    for note in notes:
        if note.get("type") != "dsa":
            continue
        pattern = (note.get("pattern") or note.get("dsa_pattern") or "").strip().lower()
        if pattern in pattern_counts:
            pattern_counts[pattern] += 1
    patterns = [{"name": p, "count": pattern_counts[p]} for p in DSA_PATTERNS]
    covered = sum(1 for p in patterns if p["count"] > 0)

    try:
        from jarvis.briefing import capture_streak

        streak = capture_streak(notes, today)
    except Exception:
        streak = {"current": 0, "longest": 0, "active_days": 0}

    active_last_n = sum(1 for row in timeline if row["count"] > 0)

    return {
        "timeline": timeline,
        "domains": domains,
        "types": types,
        "patterns": patterns,
        "totals": {
            "notes": len(notes),
            "domains": len(domain_counts),
            "streak": streak["current"],
            "longest_streak": streak["longest"],
            "active_days": streak["active_days"],
            "active_last_n": active_last_n,
            "window_days": days,
            "patterns_covered": covered,
            "patterns_total": len(DSA_PATTERNS),
            "captured_today": buckets.get(today, 0),
        },
    }
