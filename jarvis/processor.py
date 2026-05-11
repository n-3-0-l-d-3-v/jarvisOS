import json
import re
from datetime import datetime

from jarvis.config import REPO_PATH, INDEX_PATH
from jarvis.capture import list_pending, mark_processed, mark_failed
from jarvis.classifier import classify_note
from jarvis.formatter import format_note


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


def _update_index(note_id, classification, timestamp):
    index_data = _load_index()
    index_data["notes"].append(
        {
            "id": note_id,
            "title": classification.get("title", "Untitled Note"),
            "domain": classification.get("domain", "knowledge-base"),
            "folder_path": classification.get("folder_path", "22-knowledge-base"),
            "filename": f"{_slugify_title(classification.get('title', 'Untitled Note'))}.md",
            "date": timestamp[:10] if timestamp else datetime.now().date().isoformat(),
            "tags": classification.get("tags", []),
            "type": classification.get("type", "concept"),
        }
    )
    index_data["total_notes"] = int(index_data.get("total_notes", 0)) + 1
    _save_index(index_data)


def process_inbox():
    processed = 0
    failed = 0
    results = []

    for filepath in list_pending():
        payload = {}
        classification = None
        try:
            with open(filepath, encoding="utf-8") as f:
                payload = json.load(f)

            text = payload.get("text", "")
            source = payload.get("source", "cli")
            source_url = payload.get("source_url", "")
            timestamp = payload.get("timestamp", datetime.now().isoformat())
            note_id = payload.get("id", "")
            note_type = payload.get("type", "")

            print(f"Processing: {text[:50]}...")
            classification = classify_note(text, source, source_url)
            markdown = format_note(text, classification, source, source_url, timestamp)

            full_folder = REPO_PATH / classification["folder_path"]
            full_folder.mkdir(parents=True, exist_ok=True)

            filename = f"{_slugify_title(classification.get('title', 'Untitled Note'))}.md"
            target_file = full_folder / filename

            if target_file.exists():
                print(f"Already exists: {filename}")
            else:
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(markdown)

            _update_index(note_id, classification, timestamp)
            mark_processed(filepath)
            print(f"\u2713 Saved: {classification['folder_path']}/{filename}")
            processed += 1
            results.append(
                {
                    "text": text,
                    "source": source,
                    "source_url": source_url,
                    "timestamp": timestamp,
                    "note_type": classification.get("type", note_type),
                    "classification": classification,
                    "filepath": str(target_file),
                    "success": True,
                }
            )
        except Exception as exception:
            print(f"\u2717 Failed: {str(exception)}")
            try:
                mark_failed(filepath, str(exception))
            except Exception:
                pass
            failed += 1
            results.append(
                {
                    "text": payload.get("text", "") if "payload" in locals() else "",
                    "source": payload.get("source", "") if "payload" in locals() else "",
                    "source_url": payload.get("source_url", "") if "payload" in locals() else "",
                    "timestamp": payload.get("timestamp", "") if "payload" in locals() else "",
                    "note_type": payload.get("type", "") if "payload" in locals() else "",
                    "classification": classification if "classification" in locals() else None,
                    "filepath": str(filepath),
                    "success": False,
                    "error": str(exception),
                }
            )

    return {"processed": processed, "failed": failed, "results": results}
