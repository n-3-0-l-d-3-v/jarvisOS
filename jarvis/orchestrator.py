import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from jarvis.classifier import classify_note
from jarvis.config import INDEX_PATH, REPO_PATH
from jarvis.dsa_agent import analyze_dsa_note, build_dsa_note
from jarvis.formatter import format_note
from jarvis.leetcode_fetcher import enrich_note_with_leetcode
from jarvis.linker import run_linker, run_linker_for_new_notes, should_run_full_link


def _slugify_title(title: str) -> str:
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
    note_date = timestamp[:10] if timestamp else date.today().isoformat()
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


def run_parallel_dsa_enrichment(text, classification):
    leetcode_data = None
    enriched_data = None

    start = time.time()

    with ThreadPoolExecutor(max_workers=2) as executor:
        lc_future = executor.submit(enrich_note_with_leetcode, text, classification)
        dsa_future = executor.submit(analyze_dsa_note, text, classification, None)

        for future in as_completed([lc_future, dsa_future]):
            try:
                result = future.result()
                if future == lc_future:
                    leetcode_data = result
                    if result:
                        print(
                            "  [Orchestrator] LeetCode fetch complete "
                            f"({time.time() - start:.1f}s)"
                        )
                elif future == dsa_future:
                    enriched_data = result
                    if result:
                        print(
                            "  [Orchestrator] DSA agent complete "
                            f"({time.time() - start:.1f}s)"
                        )
            except Exception as exc:
                print(f"  [Orchestrator] Task failed: {exc}")

    total = time.time() - start
    print(f"  [Orchestrator] Parallel enrichment done in {total:.1f}s")

    if leetcode_data and enriched_data:
        print("  [Orchestrator] Re-enriching DSA with LeetCode context...")
        try:
            enriched_data = analyze_dsa_note(text, classification, leetcode_data)
        except Exception as exc:
            print(f"  [Orchestrator] Re-enrichment failed: {exc}")

    return leetcode_data, enriched_data


def process_single_note(inbox_file_path: Path, force=False):
    from jarvis.capture import mark_processed

    try:
        with open(inbox_file_path, encoding="utf-8") as f:
            payload = json.load(f)

        text = payload.get("text", "")
        source = payload.get("source", "cli")
        source_url = payload.get("source_url", "")
        timestamp = payload.get("timestamp", "")
        note_id = payload.get("id", "")

        print(f"  Processing: {text[:60]}...")
        total_start = time.time()

        t1 = time.time()
        classification = classify_note(text, source, source_url)
        print(
            "  [Orchestrator] Classify: "
            f"{time.time() - t1:.1f}s via {classification.get('classifier_used', '?')}"
        )

        is_dsa = classification.get("type") == "dsa" or source == "leetcode"
        leetcode_data = None
        enriched_data = None

        if is_dsa:
            print("  [Orchestrator] Starting parallel DSA enrichment...")
            leetcode_data, enriched_data = run_parallel_dsa_enrichment(text, classification)

            if leetcode_data:
                if leetcode_data.get("difficulty"):
                    classification["lc_difficulty"] = leetcode_data["difficulty"]
                if leetcode_data.get("tags"):
                    existing = classification.get("tags", [])
                    lc_tags = [tag.lower() for tag in leetcode_data["tags"][:3]]
                    classification["tags"] = list(set(existing + lc_tags))[:6]
                if leetcode_data.get("companies"):
                    classification["lc_companies"] = leetcode_data["companies"]

        if is_dsa and enriched_data:
            markdown_content = build_dsa_note(
                text, classification, enriched_data, timestamp, leetcode_data
            )
        else:
            markdown_content = format_note(text, classification, source, source_url, timestamp)

        folder = REPO_PATH / classification["folder_path"]
        folder.mkdir(parents=True, exist_ok=True)

        filename = None
        if classification.get("type") == "dsa":
            problem_number = ""
            if enriched_data:
                problem_number = enriched_data.get("problem_number", "")

            if not problem_number:
                lc_match = re.search(r"LC-?(\d+)", text, re.IGNORECASE)
                if lc_match:
                    problem_number = f"LC-{lc_match.group(1)}"

            if problem_number:
                number_part = problem_number.lower().replace("-", "-")
                if enriched_data and enriched_data.get("problem_name"):
                    name_part = enriched_data["problem_name"].lower()
                else:
                    name_part = classification.get("title", "").lower()

                name_part = re.sub(r"^lc-?\d+\s*", "", name_part)
                name_part = re.sub(r"[^a-z0-9\s-]", "", name_part)
                name_part = name_part.strip().replace(" ", "-")
                name_part = re.sub(r"-+", "-", name_part)

                filename = f"{number_part}-{name_part}.md"

        if not filename:
            filename = f"{_slugify_title(classification.get('title', 'Untitled Note'))}.md"

        filepath = folder / filename
        if filepath.exists() and not force:
            print(f"  Already exists (use --force to overwrite): {filename}")
            mark_processed(inbox_file_path)
            return {
                "success": False,
                "text": text,
                "classification": classification,
                "enriched_data": enriched_data,
                "leetcode_data": leetcode_data,
                "filepath": str(filepath),
                "error": "already_exists",
                "already_processed": True,
            }

        if filepath.exists() and force:
            print(f"  Force overwriting: {filename}")

        filepath.write_text(markdown_content, encoding="utf-8")
        print(f"  Saved: {classification['folder_path']}/{filename}")

        _update_index(note_id, classification, timestamp, filename, source, enriched_data)

        print(f"  [Orchestrator] Total: {time.time() - total_start:.1f}s")
        return {
            "success": True,
            "id": note_id,
            "text": text,
            "classification": classification,
            "enriched_data": enriched_data,
            "leetcode_data": leetcode_data,
            "filepath": str(filepath),
            "error": "",
        }
    except Exception as exc:
        print(f"  Failed: {str(exc)}")
        return {
            "success": False,
            "id": payload.get("id", "") if "payload" in locals() else "",
            "text": payload.get("text", "") if "payload" in locals() else "",
            "classification": None,
            "enriched_data": None,
            "leetcode_data": None,
            "filepath": "",
            "error": str(exc),
        }


def process_inbox_orchestrated(force=False):
    from jarvis.capture import list_pending, mark_processed, mark_failed
    from jarvis.git_sync import sync, build_commit_message

    pending = list_pending()
    if not pending:
        return {"processed": 0, "failed": 0, "results": []}

    processed = 0
    failed = 0
    results = []

    for inbox_file in pending:
        result = process_single_note(inbox_file, force=force)

        if result.get("success"):
            processed += 1
            classification = result.get("classification") or {}
            msg = build_commit_message(classification, result.get("text", ""))
            sync_result = sync(msg)
            if sync_result.get("synced"):
                print(f"  Pushed to GitHub [{sync_result.get('commit_sha', '')}]")
            mark_processed(inbox_file)
        else:
            if result.get("error") == "already_exists" and not result.get("already_processed"):
                mark_processed(inbox_file)
            elif result.get("error") == "already_exists":
                pass
            else:
                failed += 1
                mark_failed(inbox_file, result.get("error", "unknown"))

        results.append(result)

    successful_results = [result for result in results if result.get("success")]
    if successful_results:
        new_ids = {result.get("id", "") for result in successful_results if result.get("id")}
        try:
            index_data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            all_notes = index_data.get("notes", [])
        except Exception:
            all_notes = []

        new_entries = [note for note in all_notes if note.get("id") in new_ids]
        if new_entries:
            print(f"\n  [Linker] Linking {len(new_entries)} new notes...")
            run_linker_for_new_notes(new_entries)

        if should_run_full_link():
            print("  [Linker] Running full repo link pass (every 10 notes)...")
            run_linker(verbose=False)
            print("  [Linker] Full link pass complete")

    return {"processed": processed, "failed": failed, "results": results}
