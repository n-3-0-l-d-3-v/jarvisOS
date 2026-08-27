"""
Retention tools: spaced repetition (`jar review`) and self-testing (`jar quiz`).

Capturing a note is not learning it. Without a resurfacing mechanism a
knowledge base becomes a write-only archive — which is exactly how most
personal wikis die.

`jar review` uses a simple SM-2-style ladder: each time you confirm you still
know a note, its next review is pushed further out (1 -> 3 -> 7 -> 16 -> 35 ->
75 days). Notes you forget reset to the start. State lives in
00-meta/review.json, keyed by the note's file, so it survives re-captures and
never touches the note files themselves.

`jar quiz` turns your own notes into questions — useful before an interview.
"""

import json
import random
from datetime import date, datetime, timedelta

from jarvis.config import GEMINI_API_KEY, GROQ_API_KEY, REPO_PATH
from jarvis.index_store import load_index

REVIEW_PATH = REPO_PATH / "00-meta" / "review.json"

# Days until the next review, indexed by how many times you've recalled it.
INTERVALS = [1, 3, 7, 16, 35, 75, 150]


def _key(note):
    return f"{note.get('folder_path', '')}/{note.get('filename', '')}"


def _load_state():
    try:
        if REVIEW_PATH.exists():
            data = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_state(state):
    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _parse(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def due_notes(limit=10, domain=None, today=None):
    """Notes whose next review date has arrived (or that were never reviewed)."""
    today = today or date.today()
    state = _load_state()
    seen = set()
    due = []

    for note in load_index().get("notes", []):
        key = _key(note)
        if key in seen:
            continue
        seen.add(key)
        if domain and note.get("domain") != domain:
            continue
        path = REPO_PATH / note.get("folder_path", "") / note.get("filename", "")
        if not path.exists():
            continue

        entry = state.get(key)
        if entry:
            next_due = _parse(entry.get("next_review", ""))
            level = entry.get("level", 0)
        else:
            # Never reviewed: due once it is a day old.
            created = _parse(note.get("date", "")) or today
            next_due = created + timedelta(days=INTERVALS[0])
            level = 0

        if next_due is None or next_due <= today:
            overdue = (today - next_due).days if next_due else 0
            due.append({
                "title": note.get("title", "Untitled"),
                "domain": note.get("domain", ""),
                "key": key,
                "path": str(path),
                "level": level,
                "overdue_days": max(0, overdue),
            })

    due.sort(key=lambda d: d["overdue_days"], reverse=True)
    return due[:limit]


def record_review(key, remembered=True, today=None):
    """Advance (or reset) a note's spaced-repetition level."""
    today = today or date.today()
    state = _load_state()
    entry = state.get(key, {"level": 0, "reviews": 0})

    if remembered:
        entry["level"] = min(entry.get("level", 0) + 1, len(INTERVALS) - 1)
    else:
        entry["level"] = 0

    entry["reviews"] = entry.get("reviews", 0) + 1
    entry["last_review"] = today.isoformat()
    entry["next_review"] = (today + timedelta(days=INTERVALS[entry["level"]])).isoformat()
    state[key] = entry
    _save_state(state)
    return entry


def review_stats():
    state = _load_state()
    total = len(state)
    mastered = sum(1 for e in state.values() if e.get("level", 0) >= 4)
    return {"tracked": total, "mastered": mastered, "due": len(due_notes(limit=999))}


# --------------------------------------------------------------------------- #
# Quiz
# --------------------------------------------------------------------------- #
def _read_note_body(path, limit=1500):
    try:
        raw = open(path, encoding="utf-8").read()
    except Exception:
        return ""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        raw = parts[2] if len(parts) > 2 else raw
    return raw.strip()[:limit]


def generate_quiz(count=5, domain=None, note_type=None):
    """Build quiz questions from the user's own notes.

    Uses AI when available for real comprehension questions; otherwise falls
    back to recall prompts built from note titles (still useful, zero deps).
    """
    notes = []
    seen = set()
    for note in load_index().get("notes", []):
        key = _key(note)
        if key in seen:
            continue
        seen.add(key)
        if domain and note.get("domain") != domain:
            continue
        if note_type and note.get("type") != note_type:
            continue
        path = REPO_PATH / note.get("folder_path", "") / note.get("filename", "")
        if path.exists():
            notes.append((note, path))

    if not notes:
        return []

    picked = random.sample(notes, min(count, len(notes)))
    context_blocks = []
    for note, path in picked:
        body = _read_note_body(path)
        if body:
            context_blocks.append(f"### {note.get('title')}\n{body}")

    questions = _quiz_with_ai(context_blocks, len(picked)) if context_blocks else None
    if questions:
        return questions

    # Offline fallback: title-based recall prompts.
    return [
        {
            "question": f"Explain: {note.get('title')}",
            "answer": f"(open {note.get('folder_path')}/{note.get('filename')})",
            "source": note.get("title", ""),
        }
        for note, _ in picked
    ]


def _quiz_with_ai(context_blocks, count):
    prompt = f"""You are quizzing a developer on their own engineering notes.
Write exactly {count} questions that test real understanding (not trivia),
based ONLY on the notes below.

Return ONLY a JSON array:
[{{"question": "...", "answer": "concise correct answer", "source": "note title"}}]

Notes:
{chr(10).join(context_blocks)}
"""
    text = _ai(prompt)
    if not text:
        return None
    try:
        cleaned = text.strip()
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end <= start:
            return None
        parsed = json.loads(cleaned[start:end + 1])
        return [q for q in parsed if isinstance(q, dict) and q.get("question")]
    except Exception:
        return None


def _ai(prompt):
    """Delegates to the central AI client (model fallback lives there)."""
    from jarvis.ai import complete

    return complete(prompt, max_tokens=1200, temperature=0.4)
