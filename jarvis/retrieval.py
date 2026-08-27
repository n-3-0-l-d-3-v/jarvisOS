"""
Retrieval layer for Jarvis — the recall half of the second brain.

Two entry points:

  search_notes(query)  -> ranked full-text search over note BODIES, offline,
                          instant. Returns matches with a highlighted snippet.

  ask(question)        -> finds the most relevant notes, feeds them to the AI
                          (Gemini -> Groq), and returns a synthesized answer that
                          cites the notes it used. Degrades to plain search
                          results when no API key is available, so it never fails.

Deliberately NO embeddings / vector DB. At the scale of a personal knowledge base
(hundreds to low thousands of notes) a keyword pass over the files is sub-100ms
and needs zero extra dependencies or model downloads — consistent with the rest
of Jarvis. An inverted index can be added later if a repo ever gets huge.
"""

import re

from jarvis.config import GEMINI_API_KEY, GROQ_API_KEY, REPO_PATH
from jarvis.index_store import load_index

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "be", "how", "what", "why", "when", "which", "with",
    "do", "does", "did", "i", "you", "it", "this", "that", "my", "me", "can",
    "using", "use", "vs", "into", "at", "by", "as", "from", "about",
}

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _tokenize(text):
    words = re.findall(r"[a-z0-9+#.]+", (text or "").lower())
    return [w for w in words if len(w) > 1 and w not in _STOPWORDS]


def _strip_body(content):
    """Remove YAML frontmatter and template placeholders for clean searching."""
    body = _FRONTMATTER_RE.sub("", content, count=1)
    body = _PLACEHOLDER_RE.sub(" ", body)
    return body


def _note_path(note):
    return REPO_PATH / note.get("folder_path", "") / note.get("filename", "")


def _make_snippet(body, terms, width=160):
    """A short excerpt centered on the first matching term."""
    low = body.lower()
    pos = -1
    for term in terms:
        found = low.find(term)
        if found != -1 and (pos == -1 or found < pos):
            pos = found
    if pos == -1:
        text = body.strip()[:width]
    else:
        start = max(0, pos - width // 3)
        text = body[start:start + width]
    text = re.sub(r"\s+", " ", text).strip()
    return ("…" if pos > width // 3 else "") + text + "…"


def search_notes(query, limit=10):
    """Rank indexed notes against a free-text query. Returns list of dicts:
    {title, domain, folder_path, filename, path, score, snippet}.
    """
    terms = _tokenize(query)
    if not terms:
        return []

    query_low = query.lower().strip()
    results = {}  # keyed by file identity so a duplicated index can't dupe hits
    for note in load_index().get("notes", []):
        path = _note_path(note)
        try:
            raw = path.read_text(encoding="utf-8") if path.exists() else ""
        except Exception:
            raw = ""
        body = _strip_body(raw)
        body_low = body.lower()
        title_low = (note.get("title", "") or "").lower()
        tag_blob = " ".join(note.get("tags", []) or []).lower()
        subdomain = (note.get("subdomain", "") or "").lower()

        score = 0
        for term in terms:
            if term in title_low:
                score += 5
            if term in subdomain:
                score += 3
            if term in tag_blob:
                score += 3
            occurrences = body_low.count(term)
            if occurrences:
                score += min(occurrences, 5)  # cap so one note can't dominate
        # exact phrase bonus
        if len(terms) > 1 and query_low in body_low:
            score += 8
        if len(terms) > 1 and query_low in title_low:
            score += 12

        if score > 0:
            key = (note.get("folder_path", ""), note.get("filename", ""))
            existing = results.get(key)
            if existing and existing["score"] >= score:
                continue
            results[key] = {
                "title": note.get("title", "Untitled"),
                "domain": note.get("domain", ""),
                "folder_path": note.get("folder_path", ""),
                "filename": note.get("filename", ""),
                "path": str(path),
                "score": score,
                "snippet": _make_snippet(body, terms) if body.strip() else "(empty note)",
            }

    ranked = sorted(results.values(), key=lambda r: r["score"], reverse=True)
    return ranked[:limit]


# --------------------------------------------------------------------------- #
# AI completion (Gemini -> Groq -> None)
# --------------------------------------------------------------------------- #
def _complete_with_gemini(prompt):
    from jarvis.ai import _try_gemini

    return _try_gemini(prompt, 1200, 0.2)


def _complete_with_groq(prompt):
    from jarvis.ai import _try_groq

    return _try_groq(prompt, 1200, 0.2)


def _ai_complete(prompt):
    """Central AI client handles provider order and model fallback."""
    from jarvis.ai import complete

    return complete(prompt, max_tokens=1200, temperature=0.2)


def _build_context(candidates, per_note_chars=1200, total_budget=8000):
    blocks = []
    used = 0
    for note in candidates:
        path = _note_path(note) if "path" not in note else None
        try:
            from pathlib import Path

            raw = Path(note["path"]).read_text(encoding="utf-8")
        except Exception:
            raw = ""
        body = _strip_body(raw).strip()
        if not body:
            continue
        chunk = body[:per_note_chars]
        block = f"### Note: {note['title']} ({note['folder_path']}/{note['filename']})\n{chunk}"
        if used + len(block) > total_budget:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def ask(question, k=8):
    """Answer a question from the user's own notes.

    Returns {"answer": str, "sources": [note...], "used_ai": bool}.
    """
    candidates = search_notes(question, limit=k)
    if not candidates:
        return {
            "answer": "I couldn't find any notes related to that. Try `jar search` "
                      "with different words, or capture a note on it first.",
            "sources": [],
            "used_ai": False,
        }

    context = _build_context(candidates)
    prompt = f"""You are Jarvis, answering from a developer's personal notes.
Use ONLY the notes below to answer the question. Be concise and practical.
If the notes don't fully answer it, say what they do cover and what's missing.
After the answer, add a line "Sources:" listing the note titles you actually used.

Question: {question}

Notes:
{context}
"""
    answer = _ai_complete(prompt)
    if not answer:
        # Degrade gracefully to the raw search results.
        lines = ["(AI unavailable — showing the most relevant notes instead)\n"]
        for c in candidates[:5]:
            lines.append(f"• {c['title']}  [{c['folder_path']}/{c['filename']}]")
            lines.append(f"    {c['snippet']}")
        return {"answer": "\n".join(lines), "sources": candidates[:5], "used_ai": False}

    return {"answer": answer, "sources": candidates, "used_ai": True}
