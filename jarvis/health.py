"""
Knowledge base health check (`jar doctor`).

A knowledge base rots quietly: notes end up empty, links break when a file is
renamed, the index drifts from what's on disk, and things you captured months
ago are never seen again. None of that raises an error — it just makes the
repo slowly less useful.

`jar doctor` surfaces all of it in one pass and tells you exactly what to run
to fix each category.
"""

import re
from datetime import date, datetime

from jarvis.config import REPO_PATH
from jarvis.index_store import load_index

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")

# A note this thin is effectively empty once scaffolding is removed.
_EMPTY_CONTENT_CHARS = 80
_STALE_DAYS = 90

# Generated or structural markdown that is not a knowledge note: README files
# and the wiki's own index/log. Counting these as untracked notes produced
# false "unindexed file" reports, and reindexing them would pollute index.json.
_NON_NOTE_FILES = {"readme.md", "index.md", "log.md"}


def _note_path(note):
    return REPO_PATH / note.get("folder_path", "") / note.get("filename", "")


def _content_without_scaffolding(raw):
    body = _FRONTMATTER_RE.sub("", raw, count=1)
    body = _PLACEHOLDER_RE.sub("", body)
    # drop headings and table rules — they are structure, not content
    lines = [
        l.strip() for l in body.splitlines()
        if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("|")
        and not l.strip().startswith("---") and not l.strip().startswith("*Captured:")
    ]
    return "\n".join(lines)


def _days_since(iso_date):
    try:
        d = datetime.strptime(iso_date[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


def check_health(stale_days=_STALE_DAYS):
    """Run every check. Returns a dict of findings (each a list)."""
    index = load_index()
    notes = index.get("notes", [])

    findings = {
        "total_indexed": len(notes),
        "missing_files": [],     # indexed but not on disk
        "empty_notes": [],       # exist but have no real content
        "orphan_notes": [],      # no outgoing wikilinks
        "stale_notes": [],       # not touched in a long time
        "broken_links": [],      # wikilink target doesn't exist
        "no_frontmatter": [],
        "duplicate_rows": [],    # same file indexed more than once
        "untracked_files": [],   # .md on disk with no index row
    }

    # --- duplicate index rows ---
    seen = {}
    for note in notes:
        key = (note.get("folder_path", ""), note.get("filename", ""))
        seen[key] = seen.get(key, 0) + 1
    findings["duplicate_rows"] = [
        {"file": f"{k[0]}/{k[1]}", "count": v} for k, v in seen.items() if v > 1
    ]

    # --- known filenames for link resolution ---
    # Resolve against what is actually ON DISK as well as what is indexed: a
    # link to a real-but-unindexed file is an indexing problem, not a broken
    # link, and reporting it as broken sends you chasing the wrong bug.
    known_stems = set()
    for note in notes:
        fn = note.get("filename", "")
        if fn.endswith(".md"):
            known_stems.add(fn[:-3].lower())
    for md in REPO_PATH.rglob("*.md"):
        known_stems.add(md.stem.lower())

    checked = set()
    for note in notes:
        key = (note.get("folder_path", ""), note.get("filename", ""))
        if key in checked:
            continue
        checked.add(key)

        path = _note_path(note)
        label = f"{key[0]}/{key[1]}"
        title = note.get("title", "Untitled")

        if not path.exists():
            findings["missing_files"].append({"file": label, "title": title})
            continue

        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue

        if not _FRONTMATTER_RE.match(raw):
            findings["no_frontmatter"].append({"file": label, "title": title})

        content = _content_without_scaffolding(raw)
        if len(content) < _EMPTY_CONTENT_CHARS:
            findings["empty_notes"].append(
                {"file": label, "title": title, "chars": len(content)})

        # Extract links from the content only. The unfilled template carries
        # `<!-- [[wikilinks]] added automatically -->`, and reading links out of
        # the raw text counted that placeholder as a broken link to a note
        # called "wikilinks" — 15 phantom failures on the live repo.
        links = _WIKILINK_RE.findall(_PLACEHOLDER_RE.sub(" ", raw))
        if not links:
            findings["orphan_notes"].append({"file": label, "title": title})
        for target in links:
            if target.strip().lower() not in known_stems:
                findings["broken_links"].append(
                    {"file": label, "target": target.strip()})

        age = _days_since(note.get("date", ""))
        if age is not None and age > stale_days:
            findings["stale_notes"].append(
                {"file": label, "title": title, "days": age})

    # --- files on disk with no index row ---
    indexed_paths = {str(_note_path(n).resolve()).lower() for n in notes}
    skip_dirs = {"daily-logs", "weekly-summaries", "inbox", ".obsidian", ".git"}
    for md in REPO_PATH.rglob("*.md"):
        if any(part in skip_dirs for part in md.parts):
            continue
        if md.name.lower() in _NON_NOTE_FILES:
            continue
        if str(md.resolve()).lower() not in indexed_paths:
            findings["untracked_files"].append(
                {"file": str(md.relative_to(REPO_PATH)).replace("\\", "/")})

    findings["stale_notes"].sort(key=lambda x: x["days"], reverse=True)
    return findings


def summarize(findings):
    """Turn findings into (severity, label, count, hint) rows for display."""
    rows = [
        ("error", "Missing files (indexed but gone)", len(findings["missing_files"]),
         "jar index-clean"),
        ("error", "Duplicate index rows", len(findings["duplicate_rows"]),
         "jar index-clean"),
        ("warn", "Empty / scaffolding-only notes", len(findings["empty_notes"]),
         "fill them in or delete them"),
        ("warn", "Broken wikilinks", len(findings["broken_links"]),
         "jar link"),
        ("warn", "Untracked .md files (not in index)", len(findings["untracked_files"]),
         "re-capture or add to index"),
        ("info", "Orphan notes (no outgoing links)", len(findings["orphan_notes"]),
         "jar link"),
        ("info", "Notes missing frontmatter", len(findings["no_frontmatter"]),
         "add YAML frontmatter"),
        ("info", f"Stale notes (>{_STALE_DAYS}d untouched)", len(findings["stale_notes"]),
         "jar review"),
    ]
    return rows


def _parse_frontmatter(raw):
    """Minimal YAML frontmatter reader (no PyYAML dependency).

    Handles the flat `key: value` and `tags:\\n  - "x"` shapes Jarvis emits.
    """
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}
    data = {}
    current_list_key = None
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list_key:
            data.setdefault(current_list_key, []).append(
                stripped[2:].strip().strip("\"'"))
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if not value:
                current_list_key = key
                data.setdefault(key, [])
            else:
                current_list_key = None
                if value.startswith("[") and value.endswith("]"):
                    inner = value[1:-1].strip()
                    data[key] = [
                        v.strip().strip("\"'") for v in inner.split(",") if v.strip()
                    ] if inner else []
                else:
                    data[key] = value.strip("\"'")
    return data


def reindex(dry_run=False):
    """Add notes that exist on disk but are missing from index.json.

    Notes can fall out of the index (manual file creation, an over-eager
    cleanup, migrations). Once unindexed they are invisible to search, ask,
    dsa and graph — they effectively stop existing. This walks the repo and
    puts them back, reading metadata from each file's frontmatter.

    Returns {"added": [...], "scanned": n}.
    """
    from jarvis.index_store import upsert_note

    index = load_index()
    indexed = {
        (n.get("folder_path", ""), n.get("filename", "")) for n in index.get("notes", [])
    }
    skip_dirs = {"daily-logs", "weekly-summaries", "inbox", ".obsidian", ".git"}

    added = []
    scanned = 0
    for md in sorted(REPO_PATH.rglob("*.md")):
        if any(part in skip_dirs for part in md.parts):
            continue
        # Same exclusions as check_health, so reindex never adds generated
        # infrastructure (wiki/index.md, wiki/log.md) to the note index.
        if md.name.lower() in _NON_NOTE_FILES:
            continue
        scanned += 1

        rel_folder = str(md.parent.relative_to(REPO_PATH)).replace("\\", "/")
        rel_folder = "" if rel_folder == "." else rel_folder
        if (rel_folder, md.name) in indexed:
            continue

        try:
            raw = md.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = _parse_frontmatter(raw)

        title = fm.get("title") or md.stem.replace("-", " ").title()
        heading = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
        if not fm.get("title") and heading:
            title = heading.group(1).strip()

        entry = {
            "id": md.stem[:8],
            "title": title,
            "domain": fm.get("domain", "") or (rel_folder.split("/")[0][3:] if rel_folder else "knowledge-base"),
            "subdomain": fm.get("subdomain", ""),
            "folder_path": rel_folder,
            "filename": md.name,
            "date": fm.get("date", "") or date.fromtimestamp(md.stat().st_mtime).isoformat(),
            "tags": fm.get("tags", []) if isinstance(fm.get("tags"), list) else [],
            "type": fm.get("type", "concept"),
            "source": fm.get("source", "reindex"),
            "source_url": fm.get("source_url", ""),
            "confidence": 0.5,
            "classifier_used": "reindex",
        }
        added.append({"file": f"{rel_folder}/{md.name}".lstrip("/"), "title": title})
        if not dry_run:
            upsert_note(entry)

    return {"added": added, "scanned": scanned}


def health_score(findings):
    """A rough 0-100 score so you can watch it improve over time."""
    total = max(findings["total_indexed"], 1)
    penalties = (
        len(findings["missing_files"]) * 3
        + len(findings["duplicate_rows"]) * 2
        + len(findings["empty_notes"]) * 2
        + len(findings["broken_links"]) * 1
        + len(findings["untracked_files"]) * 1
    )
    score = max(0, 100 - int((penalties / total) * 100))
    return score
