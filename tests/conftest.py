"""
Test harness for Jarvis.

CRITICAL: jarvis.config binds REPO_PATH at import time, and most modules do
`from jarvis.config import REPO_PATH`. So JARVIS_REPO_PATH must be pointed at a
throwaway sandbox *before* any jarvis module is imported. conftest.py is loaded
by pytest before test modules, which makes this the correct place to do it.

Result: the entire pipeline (capture -> classify -> format -> save -> index ->
daily log -> git commit) is exercised against a temp git repo. The real devNote
repo is never touched and nothing is ever pushed to GitHub (the sandbox has no
'origin' remote, so push fails gracefully exactly as the code expects).
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# --- must happen before any `import jarvis.*` -------------------------------
SANDBOX = Path(tempfile.mkdtemp(prefix="jarvis_sandbox_"))
os.environ["JARVIS_REPO_PATH"] = str(SANDBOX)

_SKELETON = [
    "00-meta",
    "inbox/raw",
    "inbox/processed",
    "inbox/failed",
    "daily-logs",
    "weekly-summaries",
    "04-dsa",
    "21-creators",
    "22-knowledge-base",
]


def _git(*args):
    subprocess.run(["git", *args], cwd=SANDBOX, check=False,
                   capture_output=True, text=True)


def _init_sandbox():
    for sub in _SKELETON:
        (SANDBOX / sub).mkdir(parents=True, exist_ok=True)
    (SANDBOX / "00-meta" / "index.json").write_text(
        json.dumps({"total_notes": 0, "notes": []}, indent=2), encoding="utf-8"
    )
    # git repo so git_sync can commit; deliberately NO remote -> no pushes.
    _git("init", "-q")
    _git("config", "user.email", "test@jarvis.local")
    _git("config", "user.name", "Jarvis Test")
    _git("add", "-A")
    _git("commit", "-qm", "test: sandbox baseline")


_init_sandbox()
# ---------------------------------------------------------------------------


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(SANDBOX, ignore_errors=True)


@pytest.fixture
def sandbox():
    """Path to the throwaway knowledge repo."""
    return SANDBOX


@pytest.fixture
def clean_index():
    """Reset index.json to empty before a test that inspects it."""
    index_path = SANDBOX / "00-meta" / "index.json"
    index_path.write_text(
        json.dumps({"total_notes": 0, "notes": []}, indent=2), encoding="utf-8"
    )
    yield index_path
    index_path.write_text(
        json.dumps({"total_notes": 0, "notes": []}, indent=2), encoding="utf-8"
    )


def _wipe_notes():
    """Delete every note .md in the sandbox (leaves logs/inbox structure)."""
    skip = {"daily-logs", "weekly-summaries", "inbox", ".obsidian", ".git"}
    for md in SANDBOX.rglob("*.md"):
        if any(part in skip for part in md.parts):
            continue
        try:
            md.unlink()
        except OSError:
            pass


@pytest.fixture
def pristine_repo():
    """A knowledge repo with no notes at all.

    The sandbox is shared for the whole session, so tests that assert on
    repo-wide counts (health score, untracked files) need a clean slate —
    otherwise notes written by earlier tests leak in and skew the numbers.
    """
    _wipe_notes()
    index_path = SANDBOX / "00-meta" / "index.json"
    index_path.write_text(
        json.dumps({"total_notes": 0, "notes": []}, indent=2), encoding="utf-8"
    )
    (SANDBOX / "00-meta" / "review.json").unlink(missing_ok=True)
    yield SANDBOX
    _wipe_notes()


@pytest.fixture
def write_index():
    """Helper to seed index.json with given note entries."""
    index_path = SANDBOX / "00-meta" / "index.json"

    def _write(notes):
        index_path.write_text(
            json.dumps({"total_notes": len(notes), "notes": notes}, indent=2),
            encoding="utf-8",
        )
        return index_path

    return _write
