"""
Single source of truth for reading and writing 00-meta/index.json.

Before this module existed, four separate call sites (orchestrator, article
fetcher, youtube agent, rss processor) each did an unconditional
`index_data["notes"].append(entry)`. That meant every re-capture and every
`--force` overwrite silently added a *second* index row while overwriting one
file on disk — inflating the note count (the live repo showed 112 index rows
for 80 real files) and corrupting the dashboard stats.

`upsert_note()` fixes that everywhere at once: a note's identity is its file
(folder_path + filename), so re-saving the same file updates the existing row
instead of appending a duplicate. `total_notes` is always recomputed as the
real length, so it can never drift again.
"""

import json
import threading

from jarvis.config import INDEX_PATH

# index.json is touched from the CLI, the orchestrator's linker pass, and the
# API server's threadpool. A process-local lock keeps concurrent upserts from
# clobbering each other.
_lock = threading.RLock()


def _note_key(entry):
    """Identity of a note = the file it lives in."""
    return (entry.get("folder_path", ""), entry.get("filename", ""))


def load_index():
    """Return the index as {"total_notes": int, "notes": [...]} (never raises)."""
    try:
        if INDEX_PATH.exists():
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("notes", [])
                data.setdefault("total_notes", len(data["notes"]))
                return data
    except Exception:
        pass
    return {"total_notes": 0, "notes": []}


def save_index(data):
    """Persist the index, always recomputing total_notes from the real length."""
    with _lock:
        notes = data.get("notes", [])
        data["notes"] = notes
        data["total_notes"] = len(notes)
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return data


def upsert_note(entry):
    """Insert a note, or update it in place if its file is already indexed.

    Returns "added" or "updated" so callers can report accurately.
    """
    with _lock:
        data = load_index()
        notes = data["notes"]
        key = _note_key(entry)
        for i, existing in enumerate(notes):
            if _note_key(existing) == key:
                # Preserve the original id/date unless the caller supplied one,
                # so links and history stay stable across re-captures.
                entry.setdefault("id", existing.get("id", ""))
                entry.setdefault("date", existing.get("date", ""))
                notes[i] = entry
                save_index(data)
                return "updated"
        notes.append(entry)
        save_index(data)
        return "added"


def remove_note(folder_path, filename):
    """Drop a note row by its file identity. Returns True if one was removed."""
    with _lock:
        data = load_index()
        before = len(data["notes"])
        data["notes"] = [
            n for n in data["notes"]
            if _note_key(n) != (folder_path, filename)
        ]
        if len(data["notes"]) != before:
            save_index(data)
            return True
    return False


def dedupe_index():
    """Collapse any pre-existing duplicate rows (last write wins per file).

    One-shot repair for indexes corrupted before upsert_note existed.
    Returns {"removed": n, "remaining": m}.
    """
    with _lock:
        data = load_index()
        seen = {}
        for note in data["notes"]:
            seen[_note_key(note)] = note  # later entry overwrites earlier
        deduped = list(seen.values())
        removed = len(data["notes"]) - len(deduped)
        data["notes"] = deduped
        save_index(data)
    return {"removed": removed, "remaining": len(deduped)}
