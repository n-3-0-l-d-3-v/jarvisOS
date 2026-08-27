"""
Near-duplicate detection and merging (`jar dedupe`).

Capture is intentionally frictionless, which means the same idea gets written
down more than once. The live repo shows the shape clearly: four separate notes
saying Redis sorted sets use a skiplist, two Two Sum notes, two Coin Change
notes. Exact-filename duplicate detection never caught these because the titles
differ ("Redis Sorted Sets Use Skiplist Internally" vs "Redis Sorted Sets
Internally Use A").

Detection is content-based: notes are reduced to a normalized token set and
compared with Jaccard similarity, blended with title similarity. No embeddings —
at personal-KB scale an O(n^2) pass over a few hundred notes is milliseconds,
and the result is inspectable rather than a black box.

SAFETY: this is the only part of Jarvis that deletes notes, so it is DRY-RUN BY
DEFAULT. `--apply` is required to touch anything, the richest note in each
cluster is always kept, and merged notes can optionally be archived rather than
deleted.
"""

import re
from difflib import SequenceMatcher

from jarvis.config import REPO_PATH
from jarvis.index_store import load_index, remove_note

# Similarity at or above this counts as a duplicate. 0.72 was chosen against the
# live repo: it catches the Redis/Two Sum/Coin Change families without pulling
# in merely related notes.
DEFAULT_THRESHOLD = 0.72
TITLE_WEIGHT = 0.35
BODY_WEIGHT = 0.65
# Below this many tokens a note is too thin for Jaccard to mean anything.
MIN_TOKENS = 4

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[[^\]]*\]\]")
_FOOTER_RE = re.compile(r"^\*Captured:.*$", re.MULTILINE)

_STOP = {
    "the", "a", "an", "and", "or", "to", "in", "on", "for", "is", "are", "of",
    "it", "this", "that", "with", "as", "by", "be", "can", "you", "your",
    "add", "notes", "note", "related", "topics", "source", "summary",
    "overview", "resources", "examples", "key", "points",
}


def _note_path(note):
    return REPO_PATH / note.get("folder_path", "") / note.get("filename", "")


# Titles produced by the offline keyword classifier are often a truncated
# sentence fragment ("Redis Sorted Sets Internally Use A"). Those make poor
# survivors even when the file happens to hold the most text.
_TRUNCATION_TAIL = {
    "a", "an", "the", "for", "use", "uses", "used", "to", "of", "in", "on",
    "with", "and", "or", "is", "are", "by", "as", "that", "this", "it",
}


def _title_quality(title):
    """Higher is better. Penalises fragments left by keyword-classified titles."""
    words = re.findall(r"[A-Za-z0-9]+", title or "")
    if not words:
        return 0.0
    score = 1.0
    if words[-1].lower() in _TRUNCATION_TAIL:
        score -= 0.6          # clearly cut off mid-phrase
    if len(words) < 2:
        score -= 0.2
    return score


def _folder_matches_domain(note):
    """A note filed under a folder unrelated to its domain is a worse survivor."""
    domain = (note.get("domain") or "").strip().lower()
    folder = (note.get("folder_path") or "").lower()
    if not domain or not folder:
        return 0
    return 1 if domain.replace(" ", "-") in folder else 0


def _normalize(raw):
    body = _FRONTMATTER_RE.sub("", raw, count=1)
    body = _PLACEHOLDER_RE.sub(" ", body)
    body = _WIKILINK_RE.sub(" ", body)
    body = _FOOTER_RE.sub(" ", body)
    body = re.sub(r"[#*`>|_-]+", " ", body)
    return body.lower()


def _tokens(text):
    """Tokenize for similarity.

    Interior dots are kept so 'node.js' and '3.5' survive, but leading and
    trailing ones are stripped — otherwise sentence-final 'members.' and plain
    'members' count as different tokens and every comparison is pushed
    artificially far apart.
    """
    words = re.findall(r"[a-z0-9+#.]+", text)
    cleaned = (w.strip(".") for w in words)
    return {w for w in cleaned if len(w) > 2 and w not in _STOP}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _title_ratio(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def similarity(note_a, note_b):
    """Blended title + body similarity in [0, 1]."""
    body = _jaccard(note_a["_tokens"], note_b["_tokens"])
    title = _title_ratio(note_a.get("title", ""), note_b.get("title", ""))
    return BODY_WEIGHT * body + TITLE_WEIGHT * title


def _load_candidates():
    """Index rows deduped by file, with content loaded and tokenized."""
    seen = {}
    for note in load_index().get("notes", []):
        key = (note.get("folder_path", ""), note.get("filename", ""))
        if key in seen:
            continue
        path = REPO_PATH / key[0] / key[1]
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        # Never fold synthesized wiki pages into raw-note clusters — they are
        # *supposed* to overlap their sources.
        if note.get("type") == "wiki" or key[0].startswith("wiki"):
            continue
        entry = dict(note)
        entry["_path"] = path
        entry["_raw"] = raw
        entry["_tokens"] = _tokens(_normalize(raw))
        entry["_content_len"] = len(_normalize(raw).strip())
        seen[key] = entry
    return [n for n in seen.values() if len(n["_tokens"]) >= MIN_TOKENS]


def find_duplicate_clusters(threshold=DEFAULT_THRESHOLD, notes=None):
    """Group near-identical notes. Returns a list of clusters, richest first.

    Each cluster: {"keep": note, "duplicates": [note...], "scores": [float...]}
    """
    candidates = notes if notes is not None else _load_candidates()
    n = len(candidates)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    pair_scores = {}
    for i in range(n):
        for j in range(i + 1, n):
            score = similarity(candidates[i], candidates[j])
            if score >= threshold:
                union(i, j)
                pair_scores[(i, j)] = score

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        # Pick the best survivor, not merely the longest file. Ranked by:
        # a well-formed (non-truncated) title, then correct filing, then
        # content volume, then recency. Content alone would elect a fragment
        # title like "Redis Sorted Sets Internally Use A" sitting in the wrong
        # folder, which is a worse note to keep than a slightly shorter one.
        members.sort(
            key=lambda i: (
                _title_quality(candidates[i].get("title", "")),
                _folder_matches_domain(candidates[i]),
                candidates[i]["_content_len"],
                candidates[i].get("date", ""),
            ),
            reverse=True,
        )
        keep = candidates[members[0]]
        dupes = [candidates[i] for i in members[1:]]
        scores = [similarity(keep, d) for d in dupes]
        clusters.append({"keep": keep, "duplicates": dupes, "scores": scores})

    clusters.sort(key=lambda c: len(c["duplicates"]), reverse=True)
    return clusters


def merge_cluster(cluster, archive=True):
    """Remove the duplicates in a cluster, keeping the richest note.

    Returns {"kept": path, "removed": [paths], "archived": bool}.
    """
    kept = cluster["keep"]
    removed = []
    archive_dir = REPO_PATH / "00-meta" / "merged"

    for dupe in cluster["duplicates"]:
        path = dupe["_path"]
        label = f"{dupe.get('folder_path', '')}/{dupe.get('filename', '')}"
        try:
            if archive:
                archive_dir.mkdir(parents=True, exist_ok=True)
                target = archive_dir / dupe.get("filename", "note.md")
                # Preserve provenance: record what it was merged into.
                header = (
                    f"<!-- Merged into "
                    f"{kept.get('folder_path')}/{kept.get('filename')} "
                    f"by jar dedupe. Original path: {label} -->\n"
                )
                stem, suffix = target.stem, target.suffix
                counter = 1
                while target.exists():
                    target = archive_dir / f"{stem}-{counter}{suffix}"
                    counter += 1
                target.write_text(header + dupe["_raw"], encoding="utf-8")
            path.unlink()
        except Exception:
            continue
        remove_note(dupe.get("folder_path", ""), dupe.get("filename", ""))
        removed.append(label)

    return {
        "kept": f"{kept.get('folder_path')}/{kept.get('filename')}",
        "removed": removed,
        "archived": archive,
    }


def dedupe(threshold=DEFAULT_THRESHOLD, apply=False, archive=True):
    """Find (and optionally merge) duplicate clusters."""
    clusters = find_duplicate_clusters(threshold=threshold)
    results = []
    if apply:
        for cluster in clusters:
            results.append(merge_cluster(cluster, archive=archive))
    return {
        "clusters": clusters,
        "cluster_count": len(clusters),
        "duplicate_count": sum(len(c["duplicates"]) for c in clusters),
        "applied": apply,
        "results": results,
    }
