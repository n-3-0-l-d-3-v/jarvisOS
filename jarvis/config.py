from pathlib import Path
import os
from dotenv import load_dotenv

# Load .env from project root
load_dotenv()

REPO_PATH = Path(os.getenv("JARVIS_REPO_PATH", r"C:\Users\neilt\devNote"))

INBOX_RAW = REPO_PATH / "inbox" / "raw"
INBOX_PROCESSED = REPO_PATH / "inbox" / "processed"
INBOX_FAILED = REPO_PATH / "inbox" / "failed"
META_PATH = REPO_PATH / "00-meta"
INDEX_PATH = META_PATH / "index.json"
DAILY_LOGS_PATH = REPO_PATH / "daily-logs"

# API keys (empty by default)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# Ensure directories exist
for p in (INBOX_RAW, INBOX_PROCESSED, INBOX_FAILED, META_PATH, DAILY_LOGS_PATH):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
