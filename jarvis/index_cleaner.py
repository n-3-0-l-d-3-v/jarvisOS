import json
from pathlib import Path
from jarvis.config import REPO_PATH, INDEX_PATH


def clean_index():
    """Remove stale index entries where files no longer exist on disk.
    
    Returns:
        dict: {"removed": count_removed, "remaining": count_valid}
    """
    # Load index
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception as e:
        return {"removed": 0, "remaining": 0, "error": str(e)}
    
    notes = index_data.get("notes", [])
    
    # Separate valid and stale entries
    valid = []
    stale = []
    
    for note in notes:
        filepath = REPO_PATH / note.get("folder_path", "") / note.get("filename", "")
        if filepath.exists():
            valid.append(note)
        else:
            stale.append(note)
    
    # Print summary
    if not stale:
        print("  Index is clean. No stale entries found.")
        return {"removed": 0, "remaining": len(valid)}
    
    print(f"  Found {len(stale)} stale entries, {len(valid)} valid")
    for note in stale:
        folder = note.get("folder_path", "")
        filename = note.get("filename", "")
        print(f"  Removing: {folder}/{filename}")
    
    # Update index
    index_data["notes"] = valid
    index_data["total_notes"] = len(valid)
    
    # Write back to disk
    try:
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        return {"removed": 0, "remaining": len(valid), "error": f"Write failed: {str(e)}"}
    
    return {"removed": len(stale), "remaining": len(valid)}
