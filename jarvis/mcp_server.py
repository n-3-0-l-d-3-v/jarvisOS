"""
Jarvis MCP server — makes your knowledge base a native tool for any AI agent.

This is the "second interface" to Jarvis. Instead of typing CLI commands, you
talk to Claude (Desktop, Code, or the mobile app) and it can search, read,
write, and reason over your entire knowledge base directly.

Why this beats a bolt-on voice agent:
  - Conversational AND agentic — it can chain operations ("find my Redis notes,
    then write a summary page and file it").
  - Read *and* write. Capture by talking.
  - Voice comes free: the Claude mobile app already does speech-to-text, so
    dictating a note on your phone routes through these same tools.
  - Zero extra API cost — the client's model does the reasoning.

Register it once:
    claude mcp add --transport stdio -s user jarvis -- python -m jarvis.mcp_server

CRITICAL: stdio transport uses stdout for the protocol itself. The Jarvis
pipeline prints progress to stdout, which would corrupt the stream — so every
tool body runs inside `_quiet()`, which redirects stdout to stderr.
"""

import contextlib
import datetime
import io
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="jarvis",
    instructions=(
        "Jarvis is the user's personal engineering knowledge base: markdown notes "
        "in a git repo covering things they've learned (concepts, DSA/LeetCode "
        "problems, bugs, code snippets, articles, videos).\n\n"
        "Use `search_notes` to find things and `read_note` to get full content. "
        "Prefer grounding answers in their own notes over general knowledge, and "
        "cite the note titles you used.\n\n"
        "Use `capture_note` when the user says they learned something or wants it "
        "saved. Use `capture_url` for links. Both write to their real repo, so "
        "confirm intent before capturing something ambiguous.\n\n"
        "`knowledge_health` and `notes_due_for_review` help them maintain the base."
    ),
)


@contextlib.contextmanager
def _quiet():
    """Keep library prints off stdout — stdout belongs to the MCP protocol."""
    original = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = original


def _fmt_results(results):
    if not results:
        return "No matching notes found."
    lines = []
    for r in results:
        lines.append(
            f"- **{r['title']}** [{r['folder_path']}/{r['filename']}] "
            f"(score {r['score']}, domain: {r['domain']})\n  {r['snippet']}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
@server.tool(
    description=(
        "Full-text search across the user's knowledge base. Returns ranked notes "
        "with a snippet, file path, and domain. Fast and offline. Use this first "
        "to find what the user has written about a topic."
    )
)
def search_notes(query: str, limit: int = 10) -> str:
    with _quiet():
        from jarvis.retrieval import search_notes as _search

        results = _search(query, limit=limit)
    return _fmt_results(results)


@server.tool(
    description=(
        "Read the full markdown content of one note. Accepts either a "
        "'folder/filename.md' path (as returned by search_notes) or a note title "
        "to look up. Use after search_notes when you need the complete text."
    )
)
def read_note(path_or_title: str) -> str:
    with _quiet():
        from jarvis.config import REPO_PATH
        from jarvis.retrieval import search_notes as _search

        candidate = REPO_PATH / path_or_title
        if candidate.exists() and candidate.is_file():
            return candidate.read_text(encoding="utf-8")

        results = _search(path_or_title, limit=1)
        if not results:
            return f"No note found for '{path_or_title}'."
        from pathlib import Path

        target = Path(results[0]["path"])
        if not target.exists():
            return f"Indexed note file is missing: {results[0]['path']}"
        header = f"# (matched: {results[0]['title']})\n\n"
        return header + target.read_text(encoding="utf-8")


@server.tool(
    description=(
        "Answer a question using ONLY the user's own notes, with cited sources. "
        "Use when they ask 'what do I know about X' or 'what did I learn about Y'. "
        "For raw material you want to synthesize yourself, prefer search_notes."
    )
)
def ask_knowledge_base(question: str) -> str:
    with _quiet():
        from jarvis.retrieval import ask as _ask

        result = _ask(question)
    sources = ", ".join(s["title"] for s in result.get("sources", [])[:6])
    answer = result.get("answer", "")
    return f"{answer}\n\nSources: {sources}" if sources else answer


@server.tool(
    description=(
        "Find notes related to a given note title, using the knowledge graph "
        "(shared domain, subdomain, tags, and DSA pattern). Use to explore "
        "connections or find what a topic links to."
    )
)
def find_related(title: str, limit: int = 8) -> str:
    with _quiet():
        from jarvis.linker import find_related_notes, load_index

        all_notes = load_index()
        match = None
        lowered = title.lower()
        for note in all_notes:
            if lowered in (note.get("title", "") or "").lower():
                match = note
                break
        if not match:
            return f"No note found matching '{title}'."
        related = find_related_notes(match, all_notes, max_results=limit)

    if not related:
        return f"'{match['title']}' has no strongly related notes yet."
    lines = [f"Related to **{match['title']}**:"]
    lines += [
        f"- {r['title']} [{r['domain']}] (relevance {r['score']})" for r in related
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Capture (writes to the real repo)
# --------------------------------------------------------------------------- #
@server.tool(
    description=(
        "Capture a new note into the knowledge base. The text is auto-classified, "
        "formatted, filed into the right domain folder, cross-linked, and "
        "committed to git. Use when the user says they learned something or asks "
        "you to save/remember it. This WRITES to their repo."
    )
)
def capture_note(text: str, source: str = "mcp", tags: str = "") -> str:
    if not text.strip():
        return "Cannot capture an empty note."
    with _quiet():
        from jarvis.capture import capture_note as _capture
        from jarvis.processor import process_inbox

        _capture(text, source=source or "mcp", source_url="")
        # push=False keeps the tool call fast; the user syncs with `jar push`.
        result = process_inbox(force=False, push=False)

    processed = result.get("processed", 0)
    if not processed:
        return "Captured to inbox, but processing produced no new note (it may already exist)."
    for r in reversed(result.get("results", [])):
        if r.get("success") and r.get("classification"):
            cls = r["classification"]
            return (
                f"Saved '{cls.get('title')}' to {cls.get('folder_path')} "
                f"(type: {cls.get('type')}). Committed locally — run `jar push` to sync."
            )
    return f"Captured and processed {processed} note(s)."


@server.tool(
    description=(
        "Capture a URL into the knowledge base. YouTube links are fetched with "
        "transcript and summarized; other URLs are fetched as articles. Writes a "
        "structured note to the repo."
    )
)
def capture_url(url: str, note: str = "") -> str:
    url = url.strip()
    if not url:
        return "No URL provided."
    is_youtube = any(x in url for x in ("youtube.com", "youtu.be"))
    with _quiet():
        timestamp = datetime.datetime.now().isoformat()
        if is_youtube:
            from jarvis.youtube_agent import process_youtube_url

            result = process_youtube_url(url, timestamp)
        else:
            from jarvis.article_fetcher import process_article_url

            result = process_article_url(url, note, timestamp)

    if not result:
        return f"Could not fetch or process {url}."
    kind = "video" if is_youtube else "article"
    return (
        f"Saved {kind} '{result['title']}' to "
        f"{result['folder_path']}/{result['filename']}."
    )


# --------------------------------------------------------------------------- #
# Overview / maintenance
# --------------------------------------------------------------------------- #
@server.tool(
    description=(
        "Overview of the knowledge base: total notes, today's captures, counts by "
        "type, and the domain breakdown. Use to answer 'how much have I written' "
        "or to orient yourself before other calls."
    )
)
def knowledge_stats() -> str:
    with _quiet():
        from jarvis.api_server import compute_stats

        stats = compute_stats()
    domains = "\n".join(
        f"  - {d['domain']}: {d['count']}" for d in stats["domains"][:15]
    )
    return (
        f"Total notes: {stats['total_notes']}\n"
        f"Captured today: {stats['today']}\n"
        f"DSA: {stats['dsa']} | Videos: {stats['videos']} | Articles: {stats['articles']}\n\n"
        f"Domains:\n{domains}"
    )


@server.tool(
    description=(
        "List the most recently captured notes, newest first. Use for 'what have I "
        "been working on' or to catch up on recent activity."
    )
)
def list_recent(limit: int = 10) -> str:
    with _quiet():
        from jarvis.api_server import compute_stats

        recent = compute_stats()["recent"][:limit]
    if not recent:
        return "No notes captured yet."
    return "\n".join(
        f"- [{n['date']}] {n['title']} ({n['type']}, {n['domain']})" for n in recent
    )


@server.tool(
    description=(
        "Read the user's engineering journal for a day (default today). Shows what "
        "they captured, technologies touched, DSA problems and bugs. Date format "
        "YYYY-MM-DD."
    )
)
def get_daily_log(date: str = "") -> str:
    with _quiet():
        from jarvis.daily_log import get_log_path

        if date.strip():
            try:
                target = datetime.date.fromisoformat(date.strip())
            except ValueError:
                return "Date must be in YYYY-MM-DD format."
        else:
            target = datetime.date.today()
        path = get_log_path(target)
        if not path.exists():
            return f"No log for {target.isoformat()}."
        return path.read_text(encoding="utf-8")


@server.tool(
    description=(
        "Notes that are due for spaced-repetition review. Use when the user asks "
        "what they should revise, or to proactively suggest a review session."
    )
)
def notes_due_for_review(limit: int = 10, domain: str = "") -> str:
    with _quiet():
        from jarvis.review import due_notes, review_stats

        due = due_notes(limit=limit, domain=domain or None)
        stats = review_stats()
    if not due:
        return f"Nothing due. Tracked: {stats['tracked']}, mastered: {stats['mastered']}."
    lines = [f"{len(due)} note(s) due for review:"]
    lines += [
        f"- {d['title']} ({d['domain']})"
        + (f" — {d['overdue_days']}d overdue" if d["overdue_days"] else "")
        for d in due
    ]
    return "\n".join(lines)


@server.tool(
    description=(
        "The user's daily briefing: what they captured yesterday, what is due for "
        "review, their capture streak, and suggested next actions. Use when they "
        "ask 'what should I do today', 'catch me up', or for a morning summary."
    )
)
def daily_briefing() -> str:
    with _quiet():
        from jarvis.briefing import build_briefing

        b = build_briefing()

    lines = [
        f"Briefing for {b['date']}",
        f"Streak: {b['streak']['current']} day(s) (best {b['streak']['longest']}) "
        f"| {b['total_notes']} notes total | {b['today_count']} captured today",
    ]
    if b["yesterday"]:
        lines.append(f"\nYesterday ({b['yesterday_count']}):")
        lines += [f"  - {n['title']} [{n['domain']}]" for n in b["yesterday"]]
    else:
        lines.append("\nNothing captured yesterday.")
    if b["due"]:
        lines.append(f"\nDue for review ({b['review'].get('due', 0)} total):")
        lines += [
            f"  - {d['title']}"
            + (f" ({d['overdue_days']}d overdue)" if d["overdue_days"] else "")
            for d in b["due"]
        ]
    if b["actions"]:
        lines.append("\nSuggested next:")
        lines += [f"  - {a['text']}" for a in b["actions"]]
    return "\n".join(lines)


@server.tool(
    description=(
        "Health check on the knowledge base: empty notes, broken links, duplicate "
        "index rows, unindexed files, stale notes. Returns a 0-100 score and what "
        "to fix."
    )
)
def knowledge_health() -> str:
    with _quiet():
        from jarvis.health import check_health, health_score, summarize

        findings = check_health()
        score = health_score(findings)
        rows = summarize(findings)
    lines = [f"Health score: {score}/100 ({findings['total_indexed']} notes indexed)"]
    for _severity, label, count, hint in rows:
        lines.append(f"- {label}: {count}" + (f"  (fix: {hint})" if count else ""))
    return "\n".join(lines)


@server.tool(
    description=(
        "Compile a set of notes into one document with a table of contents. Filter "
        "by domain, tag, type, or a search query. Use when the user wants a "
        "handbook, cheatsheet, or study guide built from their notes."
    )
)
def export_document(
    domain: str = "", tag: str = "", note_type: str = "", query: str = "",
    title: str = "",
) -> str:
    if not any([domain, tag, note_type, query]):
        return "Provide at least one filter: domain, tag, note_type, or query."
    with _quiet():
        from jarvis.exporter import export

        result = export(
            domain=domain or None, tag=tag or None,
            note_type=note_type or None, query=query or None,
            title=title or None,
        )
    return (
        f"Built '{result['title']}' from {result['count']} note(s).\n"
        f"Saved to: {result['path']}"
    )


@server.tool(
    description=(
        "List topics with enough scattered notes to be worth merging into one "
        "wiki page. Use to answer 'what should I consolidate', or before "
        "calling synthesize_topic."
    )
)
def suggest_wiki_topics(min_size: int = 3) -> str:
    with _quiet():
        from jarvis.wiki import suggest_topics

        clusters = suggest_topics(min_size=min_size)
    if not clusters:
        return "No clusters large enough to synthesize yet."
    return "\n".join(
        f"- {c['topic']}: {c['count']} notes (by {c['basis']})"
        for c in clusters[:20]
    )


@server.tool(
    description=(
        "Merge every scattered note about a topic into ONE authoritative wiki "
        "page that cites its sources. Original notes are never modified. This "
        "WRITES a new page to the repo — confirm the topic with the user first "
        "if it is ambiguous."
    )
)
def synthesize_topic(topic: str) -> str:
    topic = (topic or "").strip()
    if not topic:
        return "No topic given."
    with _quiet():
        from jarvis.wiki import build_index
        from jarvis.wiki import synthesize_topic as _synth

        result = _synth(topic)
        if result["count"]:
            build_index()
    if not result["count"]:
        return f"No notes found for '{topic}'."
    how = "AI synthesis" if result["used_ai"] else "structured fallback (AI unavailable)"
    return (
        f"Merged {result['count']} note(s) on '{topic}' into {result['path']} "
        f"via {how}.\nSources: {', '.join(result['sources'][:8])}"
    )


@server.tool(
    description=(
        "Find near-identical notes that say the same thing twice. Read-only by "
        "default — it reports what WOULD be merged. Pass apply=true only after "
        "the user explicitly confirms, since that deletes notes (they are "
        "archived to 00-meta/merged)."
    )
)
def find_duplicates(threshold: float = 0.72, apply: bool = False) -> str:
    with _quiet():
        from jarvis.dedupe import dedupe

        result = dedupe(threshold=threshold, apply=apply)
    if not result["cluster_count"]:
        return "No near-duplicate notes found."

    lines = [
        f"{result['duplicate_count']} duplicate(s) in "
        f"{result['cluster_count']} cluster(s)"
        + ("  [MERGED]" if apply else "  [dry run — nothing changed]")
    ]
    for cluster in result["clusters"]:
        keep = cluster["keep"]
        lines.append(
            f"\nKeep: {keep.get('title')} "
            f"({keep.get('folder_path')}/{keep.get('filename')})"
        )
        for dupe, score in zip(cluster["duplicates"], cluster["scores"]):
            lines.append(f"  - {dupe.get('title')} ({score:.0%} similar)")
    if not apply:
        lines.append("\nAsk the user before merging, then call with apply=true.")
    return "\n".join(lines)


@server.tool(
    description=(
        "Learning analytics: capture timeline, notes per domain, DSA pattern "
        "coverage and streaks. Use for 'how am I doing', interview-readiness "
        "questions, or to spot neglected areas."
    )
)
def learning_analytics(days: int = 30) -> str:
    with _quiet():
        from jarvis.analytics import build_analytics

        a = build_analytics(days=days)
    t = a["totals"]
    gaps = [p["name"] for p in a["patterns"] if not p["count"]]
    lines = [
        f"{t['notes']} notes across {t['domains']} domains",
        f"Streak: {t['streak']} day(s) (best {t['longest_streak']}); active "
        f"{t['active_last_n']} of the last {t['window_days']} days",
        f"DSA patterns covered: {t['patterns_covered']}/{t['patterns_total']}",
    ]
    if gaps:
        lines.append(f"Uncovered patterns: {', '.join(gaps)}")
    lines.append("\nTop domains:")
    lines += [f"  - {d['name']}: {d['count']}" for d in a["domains"][:8]]
    return "\n".join(lines)


@server.tool(
    description=(
        "Run one autonomous maintenance cycle over the knowledge base: repair "
        "the index, relink notes, and synthesize topic pages. Read-only unless "
        "apply=true. Destructive work (deleting duplicate notes) is NEVER "
        "performed here — it is reported for the user to approve separately. "
        "Use for 'tidy up my notes' or 'run maintenance'."
    )
)
def curate_knowledge_base(apply: bool = False) -> str:
    with _quiet():
        from jarvis.curator import REVIEW, run_cycle

        result = run_cycle(dry_run=not apply)

    if not result["entries"]:
        return "Nothing to maintain — the knowledge base is in good shape."

    lines = []
    for entry in result["entries"]:
        if entry["tier"] == REVIEW:
            state = "NEEDS YOUR APPROVAL"
        elif entry["done"]:
            state = "done"
        else:
            state = "proposed"
        lines.append(f"- [{state}] {entry['action']}: {entry['detail']}"
                     f" -> {entry.get('result', '')}")

    header = (
        f"Cycle {result['cycles']} — health "
        f"{result['score_before']} -> {result['score_after']}/100"
        if apply else
        f"Dry run — health {result['score_before']}/100, nothing changed"
    )
    return f"{header}\n" + "\n".join(lines) + f"\n\nNext: {result['next']}"


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
