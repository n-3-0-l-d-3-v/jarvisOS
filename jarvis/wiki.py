"""
Wiki synthesis layer — the compounding half of the knowledge base.

Implements the "LLM Wiki" pattern (Karpathy): raw captures are immutable
sources; the AI maintains a separate layer of synthesized topic pages that get
richer every time a related source arrives.

Why this matters for Jarvis specifically: capture produces one file per thought,
so a topic you revisit five times becomes five overlapping fragments (the live
repo has eight separate Redis-persistence notes). Search finds all five; none of
them is the page you actually want to reread. Synthesis collapses a cluster into
one coherent page that supersedes the fragments, while the originals stay
untouched in their domain folders as provenance.

    devNote/
      08-databases/redis/*.md      <- raw captures (never modified here)
      wiki/
        index.md                   <- catalog of synthesized pages
        log.md                     <- append-only record of syntheses
        topics/redis.md            <- ONE good page, cites its sources

Commands: `jar wiki` (suggest clusters), `jar wiki <topic>` (synthesize).
"""

import json
import re
from datetime import date, datetime

from jarvis.config import GEMINI_API_KEY, GROQ_API_KEY, REPO_PATH
from jarvis.index_store import load_index

WIKI_DIR = REPO_PATH / "wiki"
TOPICS_DIR = WIKI_DIR / "topics"
WIKI_INDEX = WIKI_DIR / "index.md"
WIKI_LOG = WIKI_DIR / "log.md"

# A cluster needs at least this many notes to be worth synthesizing.
MIN_CLUSTER = 2
# Minimum search score for the free-text fallback to count as a real topic.
MIN_FALLBACK_SCORE = 2

# Workflow/administrative labels that are not subjects. A wiki page titled
# "Review Needed" or "Unsorted" is noise — these describe a note's *status* or
# the tool that captured it, not what it is about.
_NON_TOPICAL = {
    "unsorted", "review-needed", "review", "todo", "misc", "general",
    "cli", "note", "notes", "knowledge-base", "inbox", "draft", "untitled",
    "patterns", "concept", "dsa", "reference", "other", "tools",
}
# Per-source and total context budgets for the synthesis prompt.
PER_SOURCE_CHARS = 1800
TOTAL_BUDGET = 14000

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FOOTER_RE = re.compile(r"^\*Captured:.*$", re.MULTILINE)


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _clean(raw):
    body = _FRONTMATTER_RE.sub("", raw, count=1)
    body = _PLACEHOLDER_RE.sub("", body)
    body = _FOOTER_RE.sub("", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _note_path(note):
    return REPO_PATH / note.get("folder_path", "") / note.get("filename", "")


def _unique_notes():
    """Index rows deduped by file."""
    seen = {}
    for note in load_index().get("notes", []):
        key = (note.get("folder_path", ""), note.get("filename", ""))
        seen.setdefault(key, note)
    return list(seen.values())


# --------------------------------------------------------------------------- #
# Cluster discovery
# --------------------------------------------------------------------------- #
def suggest_topics(min_size=MIN_CLUSTER):
    """Find note clusters worth synthesizing into a wiki page.

    Clusters by subdomain first (tightest signal), then falls back to tags.
    Returns [{topic, count, notes, basis}] sorted by size.
    """
    notes = _unique_notes()
    clusters = {}

    for note in notes:
        if not _note_path(note).exists():
            continue
        subdomain = (note.get("subdomain") or "").strip().lower()
        if subdomain and subdomain not in _NON_TOPICAL:
            clusters.setdefault(("subdomain", subdomain), []).append(note)

    # Tag-based clusters for notes whose subdomain was empty/generic.
    covered = {id(n) for group in clusters.values() for n in group}
    for note in notes:
        if id(note) in covered or not _note_path(note).exists():
            continue
        for tag in (note.get("tags") or [])[:3]:
            tag = str(tag).strip().lower()
            if tag and tag not in _NON_TOPICAL:
                clusters.setdefault(("tag", tag), []).append(note)

    # A topic can surface under both bases (subdomain "redis" AND tag "redis").
    # Emitting it twice would synthesize the same page twice — wasted AI calls
    # and a confusing suggestion list — so merge by name, keeping the union of
    # notes and preferring the stronger (subdomain) basis.
    merged = {}
    for (basis, name), group in clusters.items():
        entry = merged.get(name)
        if entry is None:
            merged[name] = {"topic": name, "basis": basis, "notes": list(group)}
            continue
        known = {id(n) for n in entry["notes"]}
        entry["notes"].extend(n for n in group if id(n) not in known)
        if basis == "subdomain":
            entry["basis"] = basis

    results = [
        {"topic": e["topic"], "basis": e["basis"],
         "count": len(e["notes"]), "notes": e["notes"]}
        for e in merged.values()
        if len(e["notes"]) >= min_size
    ]
    results.sort(key=lambda c: (-c["count"], c["topic"]))
    return results


def find_cluster(topic):
    """Gather every note relevant to a topic (subdomain, tag, or free text)."""
    topic_low = topic.strip().lower()
    notes = _unique_notes()
    matched = []

    for note in notes:
        if not _note_path(note).exists():
            continue
        subdomain = (note.get("subdomain") or "").lower()
        tags = [str(t).lower() for t in (note.get("tags") or [])]
        title = (note.get("title") or "").lower()
        domain = (note.get("domain") or "").lower()
        if topic_low in (subdomain, domain) or topic_low in tags or topic_low in title:
            matched.append(note)

    if matched:
        return matched

    # Fall back to full-text search so any phrase works as a topic — but only
    # on a genuinely strong match. Boilerplate headings ("## Related Topics")
    # mean almost any word scores 1 against every note, so an unfiltered
    # fallback would happily "cluster" the entire vault for a nonsense topic
    # and synthesize a garbage page from it.
    from jarvis.retrieval import search_notes

    hits = search_notes(topic, limit=12)
    if not hits:
        return []
    top_score = hits[0].get("score", 0)
    if top_score < MIN_FALLBACK_SCORE:
        return []
    cutoff = max(1, top_score * 0.5)
    wanted = {
        (h["folder_path"], h["filename"])
        for h in hits if h.get("score", 0) >= cutoff
    }
    return [
        n for n in notes
        if (n.get("folder_path", ""), n.get("filename", "")) in wanted
    ]


# --------------------------------------------------------------------------- #
# Synthesis
# --------------------------------------------------------------------------- #
def _build_context(notes):
    blocks = []
    used = 0
    for note in notes:
        path = _note_path(note)
        try:
            body = _clean(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not body:
            continue
        chunk = body[:PER_SOURCE_CHARS]
        block = (
            f"### SOURCE: {note.get('title', 'Untitled')}\n"
            f"(file: {note.get('folder_path')}/{note.get('filename')})\n{chunk}"
        )
        if used + len(block) > TOTAL_BUDGET:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _ai(prompt):
    """Delegates to the central AI client (model fallback lives there)."""
    from jarvis.ai import complete

    return complete(prompt, max_tokens=2500, temperature=0.3)


def _fallback_page(topic, notes):
    """Deterministic page when no AI is available — still useful, never fails."""
    lines = [f"# {topic.title()}", "",
             f"_Compiled from {len(notes)} note(s). AI synthesis unavailable, "
             f"so this is a structured collection rather than a rewrite._", ""]
    for note in notes:
        lines.append(f"## {note.get('title', 'Untitled')}")
        try:
            body = _clean(_note_path(note).read_text(encoding="utf-8"))
            body = re.sub(r"^#\s+.*$", "", body, count=1, flags=re.MULTILINE).strip()
            body = re.sub(r"^##\s", "### ", body, flags=re.MULTILINE)
        except Exception:
            body = ""
        lines.append(body or "_(empty)_")
        lines.append("")
    return "\n".join(lines)


def synthesize_topic(topic, notes=None, dry_run=False):
    """Write (or rewrite) one wiki page that supersedes a cluster of notes.

    Returns {"topic", "path", "count", "sources", "used_ai", "content"}.
    """
    notes = notes if notes is not None else find_cluster(topic)
    if not notes:
        return {"topic": topic, "path": "", "count": 0, "sources": [],
                "used_ai": False, "content": ""}

    context = _build_context(notes)
    prompt = f"""You are maintaining a developer's personal engineering wiki.

Below are several raw notes the user captured about "{topic}" at different times.
They overlap, repeat each other, and vary in quality.

Write ONE authoritative wiki page that replaces them all. Requirements:
- Start with `# {topic.title()}`
- Open with a 2-3 sentence summary of what this topic actually is
- Merge duplicate facts; keep every distinct technical detail
- Organise under clear `##` headings that fit THIS topic (don't force a template)
- Preserve concrete specifics: commands, complexities, config values, gotchas
- Include a `## Open Questions` section ONLY if the notes reveal a real gap
- Do not invent anything that is not supported by the notes
- No preamble, no "here is the page" — output only the markdown

Raw notes:
{context}
"""

    generated = None if dry_run else _ai(prompt)
    used_ai = bool(generated)
    body = generated or _fallback_page(topic, notes)

    source_links = "\n".join(
        f"- [[{n.get('filename', '').replace('.md', '')}|{n.get('title', 'Untitled')}]]"
        for n in notes
    )
    today = date.today().isoformat()
    page = (
        f"---\n"
        f"title: \"{topic.title()}\"\n"
        f"type: wiki\n"
        f"topic: {topic}\n"
        f"synthesized: {today}\n"
        f"source_count: {len(notes)}\n"
        f"generated_by: {'ai' if used_ai else 'fallback'}\n"
        f"---\n\n"
        f"{body.strip()}\n\n"
        f"## Sources\n"
        f"_Synthesized from {len(notes)} captured note(s) on {today}._\n"
        f"{source_links}\n"
    )

    path = TOPICS_DIR / f"{_slug(topic)}.md"
    if not dry_run:
        TOPICS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(page, encoding="utf-8")
        _append_log(topic, len(notes), used_ai)
        _index_wiki_page(topic, path, len(notes))

    return {
        "topic": topic,
        "path": str(path),
        "count": len(notes),
        "sources": [n.get("title", "") for n in notes],
        "used_ai": used_ai,
        "content": page,
    }


def _append_log(topic, count, used_ai):
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = (f"## [{stamp}] synth | {topic} "
            f"({count} sources, {'ai' if used_ai else 'fallback'})\n")
    existing = WIKI_LOG.read_text(encoding="utf-8") if WIKI_LOG.exists() else "# Wiki Log\n\n"
    WIKI_LOG.write_text(existing + line, encoding="utf-8")


def _index_wiki_page(topic, path, count):
    """Register the wiki page in index.json so search/ask can find it."""
    from jarvis.index_store import upsert_note

    upsert_note({
        "id": f"wiki-{_slug(topic)}"[:16],
        "title": f"{topic.title()} (wiki)",
        "domain": "wiki",
        "subdomain": topic,
        "folder_path": "wiki/topics",
        "filename": path.name,
        "date": date.today().isoformat(),
        "tags": [topic, "wiki"],
        "type": "wiki",
        "source": "synthesis",
        "confidence": 0.95,
        "classifier_used": "wiki-synth",
        "source_count": count,
    })


def build_index():
    """Regenerate wiki/index.md — the catalog of synthesized pages."""
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    pages = sorted(TOPICS_DIR.glob("*.md"))
    lines = ["# Wiki Index", "",
             f"_{len(pages)} synthesized topic page(s). "
             f"Updated {date.today().isoformat()}._", ""]
    for page in pages:
        try:
            head = page.read_text(encoding="utf-8")[:600]
        except Exception:
            head = ""
        count_match = re.search(r"source_count:\s*(\d+)", head)
        title_match = re.search(r'title:\s*"([^"]+)"', head)
        title = title_match.group(1) if title_match else page.stem.title()
        count = count_match.group(1) if count_match else "?"
        lines.append(f"- [[{page.stem}|{title}]] — {count} sources")
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    WIKI_INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"pages": len(pages), "path": str(WIKI_INDEX)}
