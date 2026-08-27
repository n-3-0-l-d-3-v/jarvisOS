"""
RSS feed processor (Task 3.5).

Daily batch job that reads free developer RSS feeds, uses Groq to keep only the
items relevant to the user's engineering domains, and saves them as brief notes
in the devNote repo.

Design notes:
  - No external RSS library. Feeds are parsed with the stdlib xml.etree, which
    handles both RSS 2.0 (<item>) and Atom (<entry>) shapes. Keeps Jarvis light.
  - A small "seen" store (00-meta/rss_seen.json) dedupes items across runs so a
    feed item is only ever evaluated once.
  - If GROQ_API_KEY is missing, a keyword heuristic is used as an offline-ish
    fallback so `jar rss` still does something useful.

Run manually:   jar rss
Run scheduled:  python -m jarvis.tasks rss   (wired via `jar schedule --rss`)
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path

import httpx

from jarvis.config import REPO_PATH, INDEX_PATH, GROQ_API_KEY

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
# Free developer feeds. Bytes.dev has no public RSS endpoint (email-first
# newsletter), so JavaScript Weekly is used as the JS newsletter source.
# Add/remove entries freely — unreachable feeds are skipped gracefully.
FEEDS = [
    {"name": "Hacker News", "url": "https://news.ycombinator.com/rss"},
    {"name": "TLDR Tech", "url": "https://tldr.tech/rss"},
    {"name": "JavaScript Weekly", "url": "https://javascriptweekly.com/rss"},
]

# Where RSS notes live in the knowledge repo.
RSS_FOLDER = "22-knowledge-base/rss"
SEEN_PATH = REPO_PATH / "00-meta" / "rss_seen.json"

# Safety limits so a run never floods the repo or the API.
MAX_CANDIDATES_TO_AI = 40   # items sent to Groq per run
MAX_SAVED_PER_RUN = 8       # notes actually written per run
MAX_SEEN_KEPT = 800         # bound the dedupe store size

# Keywords used by the offline fallback relevance filter.
_RELEVANCE_KEYWORDS = {
    "python", "javascript", "typescript", "react", "vue", "svelte", "node",
    "rust", "go", "golang", "java", "kotlin", "c++", "backend", "frontend",
    "database", "postgres", "redis", "sql", "nosql", "docker", "kubernetes",
    "k8s", "devops", "cloud", "aws", "gcp", "azure", "api", "graphql", "ml",
    "ai", "llm", "gpt", "model", "algorithm", "data structure", "leetcode",
    "system design", "scalability", "security", "auth", "linux", "shell",
    "git", "compiler", "performance", "cache", "async", "concurrency",
    "framework", "library", "open source", "webassembly", "wasm", "css",
    "testing", "ci/cd", "microservice", "architecture", "networking",
}

# Precompile word-boundary patterns so short keywords like "go" or "ai" don't
# match inside unrelated words ("gossip", "email"). Alphanumerics are treated as
# word chars; separators (space, +, /) act as boundaries so "c++" / "ci/cd" work.
_RELEVANCE_PATTERNS = [
    (kw, re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"))
    for kw in _RELEVANCE_KEYWORDS
]


# --------------------------------------------------------------------------- #
# Feed fetching + parsing (stdlib only)
# --------------------------------------------------------------------------- #
def _strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_text(item, names):
    for child in item:
        if _strip_ns(child.tag).lower() in names:
            if child.text and child.text.strip():
                return child.text.strip()
    return ""


def _find_link(item):
    # RSS: <link>url</link>. Atom: <link href="url"/> (prefer rel="alternate").
    fallback = ""
    for child in item:
        if _strip_ns(child.tag).lower() != "link":
            continue
        if child.text and child.text.strip():
            return child.text.strip()
        href = child.attrib.get("href", "")
        if href:
            if child.attrib.get("rel", "alternate") == "alternate":
                return href
            fallback = fallback or href
    return fallback


def _clean_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_feed(xml_bytes):
    """Parse RSS 2.0 or Atom bytes into a list of normalized item dicts."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    items = []
    # RSS 2.0 items live under channel/item; Atom entries are top-level entries.
    nodes = [n for n in root.iter() if _strip_ns(n.tag).lower() in ("item", "entry")]
    for node in nodes:
        title = _find_text(node, {"title"})
        link = _find_link(node)
        summary = _find_text(node, {"description", "summary", "content"})
        published = _find_text(node, {"pubdate", "published", "updated", "date"})
        guid = _find_text(node, {"guid", "id"}) or link or title
        if not title:
            continue
        items.append(
            {
                "title": _clean_html(title)[:160],
                "link": link.strip(),
                "summary": _clean_html(summary)[:600],
                "published": published,
                "id": guid.strip(),
            }
        )
    return items


def fetch_feed(feed):
    url = feed["url"]
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Jarvis-Knowledge-OS/1.0"})
        if resp.status_code != 200:
            print(f"  [RSS] {feed['name']}: HTTP {resp.status_code}")
            return []
        items = parse_feed(resp.content)
        print(f"  [RSS] {feed['name']}: {len(items)} items")
        for it in items:
            it["feed"] = feed["name"]
        return items
    except Exception as exc:
        print(f"  [RSS] {feed['name']}: fetch failed ({exc})")
        return []


# --------------------------------------------------------------------------- #
# Seen store (dedupe)
# --------------------------------------------------------------------------- #
def _load_seen():
    try:
        if SEEN_PATH.exists():
            data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return set(data.get("seen", []))
    except Exception:
        pass
    return set()


def _save_seen(seen):
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    trimmed = list(seen)[-MAX_SEEN_KEPT:]
    SEEN_PATH.write_text(
        json.dumps({"seen": trimmed}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Relevance filtering
# --------------------------------------------------------------------------- #
def _extract_json(text):
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return None


def _filter_with_ai(candidates):
    """Ask Groq which candidate items are worth keeping. Returns list of dicts."""
    listing = "\n".join(
        f"{i}. [{c['feed']}] {c['title']} :: {c['summary'][:120]}"
        for i, c in enumerate(candidates)
    )
    prompt = f"""You are Jarvis, curating a developer's engineering knowledge base.
From the list of RSS items below, keep ONLY the ones genuinely useful to a
software engineer (programming, DSA, backend, frontend, devops, cloud, AI/ML,
databases, security, system design, tools). Skip generic news, funding,
politics, and non-technical items.

Return ONLY a JSON array (max {MAX_SAVED_PER_RUN} items). Each element:
{{"index": <number from list>, "domain": "one of: dsa|frontend|backend|devops|cloud|ai-ml|system-design|databases|security|programming|tools|research",
  "subdomain": "specific tech/topic", "tags": ["3-5","lowercase","tags"],
  "why": "one sentence on why it matters to a developer"}}

Items:
{listing}
"""
    try:
        from jarvis.ai import complete_json, last_error

        parsed = complete_json(prompt, max_tokens=1600, temperature=0.2)
        if not isinstance(parsed, list):
            if parsed is None:
                print(f"  [RSS] AI filtering unavailable ({last_error()})")
            return None
        results = []
        for entry in parsed:
            try:
                idx = int(entry["index"])
            except (KeyError, ValueError, TypeError):
                continue
            if 0 <= idx < len(candidates):
                from jarvis.classifier import normalize_domain

                item = dict(candidates[idx])
                item["domain"] = normalize_domain(entry.get("domain"), "research")
                item["subdomain"] = entry.get("subdomain", "")
                item["tags"] = entry.get("tags", []) or []
                item["why"] = entry.get("why", "")
                results.append(item)
        return results[:MAX_SAVED_PER_RUN]
    except Exception as exc:
        print(f"  [RSS] Groq filtering failed: {exc}")
        return None


def _filter_with_keywords(candidates):
    """Offline fallback: rank by keyword hits, keep the best few."""
    scored = []
    for c in candidates:
        text = f"{c['title']} {c['summary']}".lower()
        hits = [kw for kw, pat in _RELEVANCE_PATTERNS if pat.search(text)]
        if hits:
            item = dict(c)
            item["domain"] = "research"
            item["subdomain"] = ""
            item["tags"] = hits[:5]
            item["why"] = "Matched engineering keywords (offline filter)."
            item["_score"] = len(hits)
            scored.append(item)
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored[:MAX_SAVED_PER_RUN]


# --------------------------------------------------------------------------- #
# Note building + saving
# --------------------------------------------------------------------------- #
def _slugify(text):
    slug = re.sub(r"[^a-z0-9\s-]", "", text.lower()).strip()
    slug = re.sub(r"[\s-]+", "-", slug)
    return slug.strip("-")[:60] or "rss-item"


def _build_note(item, timestamp):
    tags = json.dumps(item.get("tags", []))
    summary = item.get("summary") or "<!-- No summary provided by feed -->"
    return f"""---
title: "{item['title'].replace('"', "'")}"
date: {timestamp[:10]}
domain: {item.get('domain', 'research')}
subdomain: {item.get('subdomain', '')}
type: rss
source: rss
source_url: "{item.get('link', '')}"
feed: "{item.get('feed', '')}"
tags: {tags}
reviewed: false
---

# {item['title']}

## Source
- Feed: {item.get('feed', '')}
- URL: [{item.get('link', '')}]({item.get('link', '')})

## Why It Matters
{item.get('why', '') or '<!-- relevance -->'}

## Summary
{summary}

## My Notes
<!-- Add your own thoughts / whether to dig deeper -->

## Related Topics
<!-- [[wikilinks]] added automatically -->

---
*Captured via Jarvis RSS on {timestamp[:10]} | Feed: {item.get('feed', '')}*
"""


def _load_index():
    try:
        if INDEX_PATH.exists():
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("notes", [])
                data.setdefault("total_notes", len(data["notes"]))
                return data
    except Exception:
        pass
    return {"notes": [], "total_notes": 0}


def _existing_source_urls():
    """Every source_url already recorded in index.json (second dedupe layer).

    The rss_seen store is the fast path, but if it is ever lost or reset this
    keeps Jarvis from re-saving an item it already has a note for.
    """
    urls = set()
    for note in _load_index().get("notes", []):
        url = note.get("source_url")
        if url:
            urls.add(url.strip())
    return urls


def _save_note(item, timestamp):
    folder = REPO_PATH / RSS_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{timestamp[:10]}-{_slugify(item['title'])}.md"
    filepath = folder / filename
    if filepath.exists():
        return None  # already have this exact item today
    filepath.write_text(_build_note(item, timestamp), encoding="utf-8")

    from jarvis.index_store import upsert_note

    upsert_note({
        "id": _slugify(item["title"])[:8] + timestamp[11:13] + timestamp[14:16],
        "title": item["title"],
        "domain": item.get("domain", "research"),
        "subdomain": item.get("subdomain", ""),
        "folder_path": RSS_FOLDER,
        "filename": filename,
        "date": timestamp[:10],
        "tags": item.get("tags", []),
        "type": "rss",
        "source": "rss",
        "source_url": item.get("link", ""),
        "feed": item.get("feed", ""),
        "confidence": 0.7,
        "classifier_used": "rss-agent",
    })
    return f"{RSS_FOLDER}/{filename}"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def process_feeds(sync_git=True, verbose=True):
    """Fetch all feeds, filter, save new relevant notes. Returns a summary dict."""
    timestamp = datetime.now().isoformat()
    if verbose:
        print("  [RSS] Fetching feeds...")

    all_items = []
    for feed in FEEDS:
        all_items.extend(fetch_feed(feed))

    seen = _load_seen()
    known_urls = _existing_source_urls()
    new_items = []
    for it in all_items:
        key = it.get("id") or it.get("link") or it.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        # Second dedupe layer: skip anything already indexed by source_url.
        link = (it.get("link") or "").strip()
        if link and link in known_urls:
            continue
        new_items.append(it)

    if verbose:
        print(f"  [RSS] {len(all_items)} total, {len(new_items)} new (after dedupe)")

    if not new_items:
        _save_seen(seen)
        return {"fetched": len(all_items), "new": 0, "saved": 0, "files": []}

    candidates = new_items[:MAX_CANDIDATES_TO_AI]
    kept = None
    if GROQ_API_KEY:
        kept = _filter_with_ai(candidates)
    if kept is None:
        if verbose:
            print("  [RSS] Using keyword fallback filter")
        kept = _filter_with_keywords(candidates)

    if verbose:
        print(f"  [RSS] Keeping {len(kept)} relevant item(s)")

    saved_files = []
    for item in kept:
        path = _save_note(item, timestamp)
        if path:
            saved_files.append(path)
            if verbose:
                print(f"  [RSS] Saved: {path}")

    # Persist dedupe store only after processing so a crash mid-run re-evaluates.
    _save_seen(seen)

    if sync_git and saved_files:
        try:
            from jarvis.git_sync import sync
            from jarvis.linker import run_linker_for_new_notes

            result = sync(f"feat: add {len(saved_files)} RSS note(s) [research]")
            if verbose and result.get("synced"):
                print(f"  [RSS] Pushed to GitHub [{result.get('commit_sha', '')}]")
            # Link the newly added notes.
            index = _load_index()
            new_entries = index.get("notes", [])[-len(saved_files):]
            if new_entries:
                run_linker_for_new_notes(new_entries)
        except Exception as exc:
            print(f"  [RSS] Post-save sync/link skipped: {exc}")

    return {
        "fetched": len(all_items),
        "new": len(new_items),
        "saved": len(saved_files),
        "files": saved_files,
    }


if __name__ == "__main__":
    summary = process_feeds()
    print(summary)
