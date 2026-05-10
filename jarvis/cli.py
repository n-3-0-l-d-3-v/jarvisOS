import json
from pathlib import Path
import datetime

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

console = Console()


def _append_to_daily_log(text, source, url):
    today = datetime.date.today()
    dirp = DAILY_LOGS_PATH / str(today.year) / f"{today:%m}"
    dirp.mkdir(parents=True, exist_ok=True)
    filep = dirp / f"{today:%Y-%m-%d}.md"
    if not filep.exists():
        filep.write_text(f"# {today:%Y-%m-%d}\n\n## Captured Notes\n\n", encoding="utf-8")
    t = datetime.datetime.now().strftime("%H:%M")
    line = f"- `{t}` [{source}] {text}"
    if url:
        line += f" — [{url}]({url})"
    line += "\n"
    with open(filep, "a", encoding="utf-8") as f:
        f.write(line)


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
    _append_to_daily_log(text, source, url)


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
    body = f"Repo: {REPO_PATH}\nTotal notes: {total_notes}\nPending: {pending}\nProcessed: {processed}\nFailed: {failed}"
    console.print(Panel(body, title="Jarvis Status", border_style="blue"))


@cli.command()
def today():
    """Show today's daily log."""
    today = datetime.date.today()
    filep = DAILY_LOGS_PATH / str(today.year) / f"{today:%m}" / f"{today:%Y-%m-%d}.md"
    if not filep.exists():
        console.print("No log for today yet. Capture your first note.")
        return
    console.print(filep.read_text(encoding="utf-8"))


def main():
    cli()


if __name__ == "__main__":
    main()
