import json
import re
from datetime import datetime

from jarvis.config import REPO_PATH, INDEX_PATH
from jarvis.capture import list_pending, mark_processed, mark_failed
from jarvis.classifier import classify_note
from jarvis.formatter import format_note
from jarvis.dsa_agent import analyze_dsa_note, build_dsa_note
from jarvis.leetcode_fetcher import enrich_note_with_leetcode
from jarvis.orchestrator import process_inbox_orchestrated
from jarvis.git_sync import sync, build_commit_message


def _slugify_title(title):
    slug = title.lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled-note"


def _load_index():
    try:
        if INDEX_PATH.exists():
            with open(INDEX_PATH, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("total_notes", 0)
                    data.setdefault("notes", [])
                    return data
    except Exception:
        pass
    return {"total_notes": 0, "notes": []}


def _save_index(index_data):
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def _update_index(note_id, classification, timestamp, filename, source, enriched_data=None):
    index_data = _load_index()
    note_date = timestamp[:10] if timestamp else datetime.now().date().isoformat()
    entry = {
        "id": note_id,
        "title": classification.get("title", "Untitled Note"),
        "domain": classification.get("domain", "knowledge-base"),
        "subdomain": classification.get("subdomain", ""),
        "folder_path": classification.get("folder_path", "22-knowledge-base"),
        "filename": filename,
        "date": note_date,
        "tags": classification.get("tags", []),
        "type": classification.get("type", "concept"),
        "source": source,
        "confidence": classification.get("confidence", 0.5),
        "dsa_pattern": classification.get("dsa_pattern", ""),
        "classifier_used": classification.get("classifier_used", "gemini"),
    }
    if enriched_data:
        entry["problem_number"] = enriched_data.get("problem_number", "")
        entry["difficulty"] = enriched_data.get("difficulty", "")
        entry["pattern"] = enriched_data.get("pattern", "")
        entry["companies"] = enriched_data.get("companies", [])
    if "lc_difficulty" in classification:
        entry["lc_difficulty"] = classification.get("lc_difficulty", "")
    if "lc_companies" in classification:
        entry["lc_companies"] = classification.get("lc_companies", [])
    index_data["notes"].append(entry)
    index_data["total_notes"] = int(index_data.get("total_notes", 0)) + 1
    _save_index(index_data)


def process_inbox(force=False):
    return process_inbox_orchestrated(force=force)


# Legacy sequential processing — replaced by orchestrator
# def process_inbox(force=False):
#     processed = 0
#     failed = 0
#     results = []
#
#     for filepath in list_pending():
#         payload = {}
#         classification = None
#         try:
#             with open(filepath, encoding="utf-8") as f:
#                 payload = json.load(f)
#
#             text = payload.get("text", "")
#             source = payload.get("source", "cli")
#             source_url = payload.get("source_url", "")
#             timestamp = payload.get("timestamp", datetime.now().isoformat())
#             note_id = payload.get("id", "")
#             note_type = payload.get("type", "")
#             enriched_data = None
#
#             print(f"Processing: {text[:50]}...")
#             classification = classify_note(text, source, source_url)
#
#             leetcode_data = None
#             if classification.get("type") == "dsa" or source == "leetcode":
#                 leetcode_data = enrich_note_with_leetcode(text, classification)
#                 if leetcode_data:
#                     if leetcode_data.get("difficulty"):
#                         classification["lc_difficulty"] = leetcode_data["difficulty"]
#                     if leetcode_data.get("tags"):
#                         existing_tags = classification.get("tags", [])
#                         lc_tags = [tag.lower() for tag in leetcode_data["tags"][:3]]
#                         classification["tags"] = list(set(existing_tags + lc_tags))[:6]
#                     classification["lc_companies"] = leetcode_data.get("companies", [])
#
#             if classification.get("type") == "dsa" or source == "leetcode":
#                 print("  [Jarvis] DSA note detected — activating specialist agent...")
#                 enriched_data = analyze_dsa_note(text, classification, leetcode_data)
#                 if enriched_data:
#                     print(
#                         "  [Jarvis] DSA Agent: enriched with pattern="
#                         f"{enriched_data.get('pattern')} difficulty={enriched_data.get('difficulty')}"
#                     )
#                     markdown = build_dsa_note(text, classification, enriched_data, timestamp, leetcode_data)
#                 else:
#                     print("  [Jarvis] DSA Agent unavailable — using standard formatter")
#                     markdown = format_note(text, classification, source, source_url, timestamp)
#             else:
#                 markdown = format_note(text, classification, source, source_url, timestamp)
#
#             full_folder = REPO_PATH / classification["folder_path"]
#             full_folder.mkdir(parents=True, exist_ok=True)
#
#             filename = None
#             if classification.get("type") == "dsa":
#                 problem_number = ""
#                 if enriched_data:
#                     problem_number = enriched_data.get("problem_number", "")
#
#                 if not problem_number:
#                     lc_match = re.search(r"LC-?(\d+)", text, re.IGNORECASE)
#                     if lc_match:
#                         problem_number = f"LC-{lc_match.group(1)}"
#
#                 if problem_number:
#                     number_part = problem_number.lower().replace("-", "-")
#                     if enriched_data and enriched_data.get("problem_name"):
#                         name_part = enriched_data["problem_name"].lower()
#                     else:
#                         name_part = classification.get("title", "").lower()
#
#                     name_part = re.sub(r"^lc-?\d+\s*", "", name_part)
#                     name_part = re.sub(r"[^a-z0-9\s-]", "", name_part)
#                     name_part = name_part.strip().replace(" ", "-")
#                     name_part = re.sub(r"-+", "-", name_part)
#
#                     filename = f"{number_part}-{name_part}.md"
#
#             if not filename:
#                 filename = f"{_slugify_title(classification.get('title', 'Untitled Note'))}.md"
#             target_file = full_folder / filename
#
#             if target_file.exists() and not force:
#                 print(f"  Already exists (use --force to overwrite): {filename}")
#                 mark_processed(filepath)
#                 continue
#             elif target_file.exists() and force:
#                 print(f"  Force overwriting: {filename}")
#
#             with open(target_file, "w", encoding="utf-8") as f:
#                 f.write(markdown)
#
#             _update_index(note_id, classification, timestamp, filename, source, enriched_data)
#
#             # Sync to GitHub
#             commit_msg = build_commit_message(classification, text)
#             sync_result = sync(commit_msg)
#
#             mark_processed(filepath)
#             print(f"\u2713 Saved: {classification['folder_path']}/{filename}")
#
#             # Print sync status
#             if sync_result.get("synced"):
#                 print(f"  \u2191 Pushed to GitHub [{sync_result['commit_sha']}]")
#             elif sync_result.get("committed") and sync_result.get("push_error"):
#                 print(f"  \u26a0 Committed but push failed: {sync_result['push_error']}")
#             elif sync_result.get("reason") == "nothing to commit":
#                 print(f"  \u2014 Nothing new to push")
#
#             processed += 1
#             results.append(
#                 {
#                     "text": text,
#                     "source": source,
#                     "source_url": source_url,
#                     "timestamp": timestamp,
#                     "note_type": classification.get("type", note_type),
#                     "classification": classification,
#                     "filepath": str(target_file),
#                     "success": True,
#                     "synced": sync_result.get("synced", False),
#                     "commit_sha": sync_result.get("commit_sha", ""),
#                     "push_error": sync_result.get("push_error", ""),
#                 }
#             )
#         except Exception as exception:
#             print(f"\u2717 Failed: {str(exception)}")
#             try:
#                 mark_failed(filepath, str(exception))
#             except Exception:
#                 pass
#             failed += 1
#             results.append(
#                 {
#                     "text": payload.get("text", "") if "payload" in locals() else "",
#                     "source": payload.get("source", "") if "payload" in locals() else "",
#                     "source_url": payload.get("source_url", "") if "payload" in locals() else "",
#                     "timestamp": payload.get("timestamp", "") if "payload" in locals() else "",
#                     "note_type": payload.get("type", "") if "payload" in locals() else "",
#                     "classification": classification if "classification" in locals() else None,
#                     "filepath": str(filepath),
#                     "success": False,
#                     "error": str(exception),
#                 }
#             )
#
#     return {"processed": processed, "failed": failed, "results": results}
