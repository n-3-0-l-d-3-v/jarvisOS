import json
import re
import datetime
import sys

import click
from rich.console import Console
from rich.panel import Panel

from .config import (
    REPO_PATH,
    INDEX_PATH,
    INBOX_RAW,
    INBOX_PROCESSED,
    INBOX_FAILED,
    DAILY_LOGS_PATH,
)
from .capture import capture_note, list_pending
from .daily_log import (
    append_to_log,
    finalize_log,
    generate_weekly_summary,
    get_log_path,
    update_technologies,
)
from .processor import process_inbox
from .scheduler import setup_scheduler
from .git_sync import sync, get_status

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

console = Console()


def _parse_date_value(date_value):
    if not date_value:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(date_value)
    except Exception as exception:
        raise click.BadParameter("Date must be in YYYY-MM-DD format") from exception


def _extract_summary_from_log(content):
    marker = "## Summary"
    next_marker = "## Captured Notes"
    if marker not in content:
        return ""
    start = content.index(marker) + len(marker)
    remainder = content[start:]
    if next_marker in remainder:
        summary_block = remainder.split(next_marker, 1)[0]
    else:
        summary_block = remainder
    lines = [line.strip() for line in summary_block.splitlines() if line.strip()]
    return "\n".join(lines)


def _collect_latest_result(results, text, source, source_url):
    for result in reversed(results):
        if not result.get("success"):
            continue
        if result.get("text") == text and result.get("source") == source and result.get("source_url") == source_url:
            return result
    return None


@click.group()
def cli():
    """Jarvis CLI"""


@cli.command()
@click.argument("text")
@click.option(
    "--source",
    default="cli",
    type=click.Choice(["cli", "youtube", "article", "leetcode", "telegram"]),
)
@click.option("--url", default="")
def note(text, source, url):
    """Capture a quick note to the inbox."""
    path = capture_note(text, source=source, source_url=url)
    body = f":white_heavy_check_mark:  {text}\n\nSource: {source}  Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nFile: {path}"
    console.print(Panel(body, title="Jarvis", border_style="green"))
    console.print("[dim]Processing...[/dim]")
    results = process_inbox()
    latest = _collect_latest_result(results.get("results", []), text, source, url)
    if latest and latest.get("classification"):
        timestamp = latest.get("timestamp")
        target_date = datetime.date.fromisoformat(timestamp[:10]) if timestamp else datetime.date.today()
        note_type = latest.get("note_type") or latest["classification"].get("type", "concept")
        append_to_log(text, source, url, note_type, latest["classification"], target_date=target_date)
        update_technologies(latest["classification"], target_date=target_date)
    console.print("[dim]✓ Done[/dim]")


@cli.command()
def process():
    """Process pending notes from the inbox."""
    files = list_pending()
    if not files:
        console.print("Inbox is empty — nothing to process.")
        return
    console.print(Panel(f"Found {len(files)} pending note(s)", title="Jarvis Processing", border_style="green"))
    result = process_inbox()
    console.print(f"Processed: {result['processed']} | Failed: {result['failed']}")


@cli.command()
@click.option("--date", "date_value", default=None, help="Date in YYYY-MM-DD format")
def log(date_value):
    """Show a daily log file."""
    log_date = _parse_date_value(date_value)
    log_path = get_log_path(log_date)
    if not log_path.exists():
        console.print(f"No log found for {log_date.isoformat()}")
        return
    console.print(log_path.read_text(encoding="utf-8"))


@cli.command()
@click.option("--date", "date_value", default=None, help="Date in YYYY-MM-DD format")
def finalize(date_value):
    """Finalize a daily log with an AI summary."""
    log_date = _parse_date_value(date_value)
    log_path = get_log_path(log_date)
    result = finalize_log(log_date)
    if result.startswith("No log found"):
        console.print(result)
        return
    summary = _extract_summary_from_log(log_path.read_text(encoding="utf-8"))
    body = f"{summary}\n\nSaved to: {log_path}"
    console.print(Panel(body, title="Jarvis — Log Finalized", border_style="green"))


@cli.command()
def weekly():
    """Generate a weekly summary from the last seven daily logs."""
    summary_path = generate_weekly_summary()
    preview = summary_path.read_text(encoding="utf-8")[:500]
    body = f"Saved to: {summary_path}\n\n{preview}"
    console.print(Panel(body, title="Jarvis — Weekly Summary", border_style="blue"))


@cli.command()
def logs():
    """List all daily logs grouped by month."""
    log_files = [
        path
        for path in DAILY_LOGS_PATH.rglob("*.md")
        if re.match(r"^\d{4}-\d{2}-\d{2}\.md$", path.name)
    ]
    if not log_files:
        console.print("No daily logs found.")
        return

    grouped = {}
    for path in log_files:
        month_key = f"{path.parent.parent.name}/{path.parent.name}"
        grouped.setdefault(month_key, 0)
        grouped[month_key] += 1

    for month_key in sorted(grouped):
        console.print(f"{month_key}: {grouped[month_key]} logs")
    console.print(f"Total logs: {len(log_files)}")


@cli.command()
def schedule():
    """Set up the midnight log finalizer task."""
    message = setup_scheduler()
    console.print(Panel(message, title="Jarvis — Scheduler", border_style="green" if "Failed" not in message else "red"))


@cli.command()
def inbox():
    """List pending notes in the inbox."""
    files = list_pending()
    if not files:
        console.print("[dim]Inbox is empty — all notes processed.[/dim]")
        return
    console.print(f"Pending: {len(files)}")
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            time = data.get("time", "")
            text = data.get("text", "").replace("\n", " ")
            if len(text) > 70:
                text = text[:67] + "..."
            source = data.get("source", "")
            console.print(f"{time}  {text}  [{source}]")
        except Exception:
            console.print(f"{f.name} — could not read file")


@cli.command()
def status():
    """Show Jarvis status."""
    total_notes = 0
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            idx = json.load(f)
            total_notes = idx.get("total_notes", 0)
    except Exception:
        total_notes = 0
    pending = len(list(INBOX_RAW.glob("*.json")))
    processed = len(list(INBOX_PROCESSED.glob("*.json")))
    failed = len(list(INBOX_FAILED.glob("*.json")))
    
    # Get git status
    git_info = ""
    try:
        git_status = get_status()
        branch = git_status.get("branch", "unknown")
        ahead = git_status.get("ahead", 0)
        git_info = f"\nBranch: {branch} | Ahead: {ahead} commits"
    except Exception:
        git_info = "\nGit: not initialized"
    
    body = f"Repo: {REPO_PATH}\nTotal notes: {total_notes}\nPending: {pending}\nProcessed: {processed}\nFailed: {failed}{git_info}"
    console.print(Panel(body, title="Jarvis Status", border_style="blue"))


@cli.command(name="sync")
def sync_cmd():
    """Sync notes to GitHub."""
    try:
        # Show current status
        git_status = get_status()
        branch = git_status.get("branch", "unknown")
        modified = len(git_status.get("modified", []))
        untracked = len(git_status.get("untracked", []))
        
        status_info = f"Branch: {branch} | Modified: {modified} files | Untracked: {untracked} files"
        console.print(Panel(status_info, title="Git Status", border_style="cyan"))
        
        # Perform sync
        sync_result = sync()
        
        if sync_result.get("synced"):
            body = f"Commit: {sync_result['commit_sha']}\nMessage: {sync_result['commit_message']}\nRemote: {git_status['branch']}"
            console.print(Panel(body, title="✓ Synced to GitHub", border_style="green"))
        elif sync_result.get("committed") and sync_result.get("push_error"):
            body = f"Error: {sync_result['push_error']}\nRun 'jar sync' again to retry pushing."
            console.print(Panel(body, title="⚠ Committed, push failed", border_style="yellow"))
        else:
            console.print(Panel("Already up to date. Nothing to push.", title="— Nothing new", border_style="dim"))
    except Exception as e:
        console.print(Panel(f"Error: {str(e)}", title="✗ Sync failed", border_style="red"))


@cli.command()
def today():
    """Show today's daily log."""
    today = datetime.date.today()
    filep = get_log_path(today)
    if not filep.exists():
        console.print("No log for today yet. Capture your first note.")
        return
    console.print(filep.read_text(encoding="utf-8"))


def main():
    cli()


if __name__ == "__main__":
    main()
