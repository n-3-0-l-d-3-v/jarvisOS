import json
import re
from pathlib import Path

import httpx

from jarvis.config import GROQ_API_KEY, INDEX_PATH, REPO_PATH


def load_index():
    try:
        if INDEX_PATH.exists():
            with open(INDEX_PATH, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("notes", [])
    except Exception:
        pass
    return []


def find_related_notes(note_entry, all_notes, max_results=5):
    tags = set(note_entry.get("tags", []) or [])
    domain = note_entry.get("domain", "")
    subdomain = note_entry.get("subdomain", "")
    dsa_pattern = note_entry.get("dsa_pattern", "")
    note_type = note_entry.get("type", "")
    note_date = note_entry.get("date", "")

    results = []
    for other in all_notes:
        if other.get("id") == note_entry.get("id"):
            continue

        score = 0
        if subdomain and subdomain == other.get("subdomain", ""):
            score += 3
        if domain and domain == other.get("domain", ""):
            score += 2
        if dsa_pattern and dsa_pattern == other.get("dsa_pattern", ""):
            score += 2
        if note_type and note_type == other.get("type", ""):
            score += 1

        shared_tags = tags.intersection(set(other.get("tags", []) or []))
        score += min(len(shared_tags), 4)

        if note_date and other.get("date", ""):
            try:
                note_parts = [int(part) for part in note_date.split("-")]
                other_parts = [int(part) for part in other.get("date", "").split("-")]
                note_ordinal = _date_to_ordinal(note_parts)
                other_ordinal = _date_to_ordinal(other_parts)
                if note_ordinal - other_ordinal > 180:
                    score -= 1
            except Exception:
                pass

        if score >= 2:
            results.append(
                {
                    "title": other.get("title", "Untitled"),
                    "domain": other.get("domain", ""),
                    "folder_path": other.get("folder_path", ""),
                    "filename": other.get("filename", ""),
                    "score": score,
                }
            )

    results.sort(key=lambda item: item.get("score", 0), reverse=True)
    return results[:max_results]


def _date_to_ordinal(date_parts):
    year, month, day = date_parts
    return year * 365 + month * 30 + day


def build_wikilinks(related_notes):
    links = []
    for note in related_notes:
        filename_no_ext = note.get("filename", "").replace(".md", "")
        display = note.get("title", "Untitled")
        if filename_no_ext:
            links.append(f"- [[{filename_no_ext}|{display}]]")
    return "\n".join(links)


def inject_wikilinks(filepath, wikilinks_text):
    content = filepath.read_text(encoding="utf-8")
    old_placeholder = "<!-- [[wikilinks]] added automatically -->"

    if old_placeholder in content:
        content = content.replace(old_placeholder, wikilinks_text)
        filepath.write_text(content, encoding="utf-8")
        return True

    related_section_match = re.search(
        r"## Related Topics\n(.*?)(?=\n## |\Z)", content, re.DOTALL
    )
    if related_section_match:
        section_content = related_section_match.group(1).strip()
        existing_links = section_content.count("[[")
        if existing_links <= 2:
            new_section = f"## Related Topics\n{wikilinks_text}"
            content = re.sub(
                r"## Related Topics\n.*?(?=\n## |\Z)",
                new_section,
                content,
                flags=re.DOTALL,
            )
            filepath.write_text(content, encoding="utf-8")
            return True

    related_section_match = re.search(
        r"## Related Patterns\n(.*?)(?=\n## |\Z)", content, re.DOTALL
    )
    if related_section_match:
        section_content = related_section_match.group(1).strip()
        existing_links = section_content.count("[[")
        if existing_links <= 2:
            new_section = f"## Related Patterns\n{wikilinks_text}"
            content = re.sub(
                r"## Related Patterns\n.*?(?=\n## |\Z)",
                new_section,
                content,
                flags=re.DOTALL,
            )
            filepath.write_text(content, encoding="utf-8")
            return True

    return False


def link_note(note_entry, all_notes):
    related = find_related_notes(note_entry, all_notes)
    if not related:
        return False

    wikilinks_text = build_wikilinks(related)
    filepath = REPO_PATH / note_entry.get("folder_path", "") / note_entry.get("filename", "")
    if not filepath.exists():
        return False

    return inject_wikilinks(filepath, wikilinks_text)


def run_linker(notes_to_link=None, verbose=True):
    all_notes = load_index()
    if not all_notes:
        print("  [Linker] Index empty, nothing to link")
        return {"linked": 0, "skipped": 0}

    if notes_to_link is None:
        target_notes = all_notes
    else:
        target_notes = notes_to_link

    linked = 0
    skipped = 0

    for note in target_notes:
        result = link_note(note, all_notes)
        if result:
            linked += 1
            if verbose:
                print(f"  [Linker] Linked: {note.get('title', '?')[:50]}")
        else:
            skipped += 1

    if verbose:
        print(f"  [Linker] Done — linked {linked}, skipped {skipped}")

    return {"linked": linked, "skipped": skipped}


def run_linker_for_new_notes(new_note_entries):
    return run_linker(notes_to_link=new_note_entries, verbose=False)


def should_run_full_link():
    try:
        index_data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        total = index_data.get("total_notes", 0)
        return total > 0 and total % 10 == 0
    except Exception:
        return False
