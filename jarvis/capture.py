from pathlib import Path
import json
import datetime
import secrets
from .config import INBOX_RAW, INBOX_PROCESSED, INBOX_FAILED


def _now():
    return datetime.datetime.now()


def _random_id(n=8):
    # return hex string of length n
    token = secrets.token_hex((n + 1) // 2)
    return token[:n]


def capture_note(text, source="cli", source_url="", extra=None):
    ts = _now()
    rid = _random_id(8)
    filename = ts.strftime("%Y%m%d_%H%M%S_") + rid + ".json"
    path = INBOX_RAW / filename
    payload = {
        "id": rid,
        "timestamp": ts.isoformat(),
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M:%S"),
        "source": source,
        "source_url": source_url or "",
        "text": text,
        "status": "pending",
        "extra": extra or {}
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def list_pending():
    files = sorted(INBOX_RAW.glob("*.json"))
    return files


def mark_processed(filepath):
    p = Path(filepath)
    dest = INBOX_PROCESSED / p.name
    p.rename(dest)
    return dest


def mark_failed(filepath, reason):
    p = Path(filepath)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data["failure_reason"] = reason
    data["status"] = "failed"
    dest = INBOX_FAILED / p.name
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        p.unlink()
    except Exception:
        pass
    return dest
