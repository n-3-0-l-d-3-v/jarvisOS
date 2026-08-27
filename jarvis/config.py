from pathlib import Path
import os
from dotenv import load_dotenv

# Load .env from project root (one level above this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

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
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")

# --------------------------------------------------------------------------- #
# AI models — the ONLY place model names live.
#
# These are lists, tried in order, because providers retire models without
# warning: `gemini-2.0-flash` and `llama-3.3-70b-versatile` both started
# returning 404 mid-2026 and silently killed the whole AI layer. The first
# entries are moving aliases that survive deprecation; the rest are pinned
# fallbacks. Override with JARVIS_GEMINI_MODELS / JARVIS_GROQ_MODELS (CSV).
# --------------------------------------------------------------------------- #
def _model_list(env_key, defaults):
    raw = os.getenv(env_key, "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    return defaults


GEMINI_MODELS = _model_list("JARVIS_GEMINI_MODELS", [
    "gemini-2.5-flash",        # pinned + stable; the -latest alias was slow
    "gemini-flash-latest",     # moving alias — survives deprecations
    "gemini-3-flash-preview",
    "gemini-flash-lite-latest",
])

GROQ_MODELS = _model_list("JARVIS_GROQ_MODELS", [
    "qwen/qwen3.8-27b",        # verified fast (~2s) on the free tier
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
    "groq/compound",
])

# Which provider to try first. Groq is the default because it answered in ~2s
# in testing while the Gemini alias hit a 45s deadline. Set to "gemini" to flip.
AI_PRIMARY = os.getenv("JARVIS_AI_PRIMARY", "groq").strip().lower()

# Free speech-to-text on Groq — powers `jar listen`.
WHISPER_MODEL = os.getenv("JARVIS_WHISPER_MODEL", "whisper-large-v3-turbo")

# Note style. Lean notes keep only the sections that actually carry content,
# instead of a 10-section scaffold that is mostly empty placeholders.
# Set JARVIS_LEAN_NOTES=false (or pass `jar note --full`) for the rich template.
LEAN_NOTES = os.getenv("JARVIS_LEAN_NOTES", "true").strip().lower() not in {"false", "0", "no"}

# Ensure directories exist
for p in (INBOX_RAW, INBOX_PROCESSED, INBOX_FAILED, META_PATH, DAILY_LOGS_PATH):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
