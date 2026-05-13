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
from .classifier import reclassify_unsorted
from .index_cleaner import clean_index
from .youtube_agent import process_youtube_url
from .linker import run_linker_for_new_notes

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
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Overwrite existing note if it already exists",
)
def note(text, source, url, force):
    """Capture a quick note to the inbox."""
    # Check if text is a YouTube URL
    if text.startswith(("https://youtube.com", "https://youtu.be", "https://www.youtube.com")):
        console.print("[dim]YouTube URL detected — routing to YouTube agent...[/dim]\n")
        result = process_youtube_url(text)
        if not result:
            console.print("[red]Failed to process YouTube video.[/red]")
            return
        sync_result = sync(
            f"feat: add video-summary — {result['title'][:50]} [creator-content]"
        )
        # Auto-link
        try:
            index_data = json.loads(INDEX_PATH.read_text())
            all_notes = index_data.get("notes", [])
            if all_notes:
                run_linker_for_new_notes([all_notes[-1]])
        except Exception:
            pass
        console.print(
            Panel(
                f"[bold green]✓ Video captured[/bold green]\n\n"
                f"Title   : {result['title'][:60]}\n"
                f"Channel : {result['channel']}\n"
                f"Saved   : {result['folder_path']}/{result['filename']}\n"
                f"GitHub  : {'pushed' if sync_result.get('synced') else 'synced'}",
                title="[bold]Jarvis — YouTube[/bold]",
                border_style="green",
                width=65,
            )
        )
        return

    elif (text.startswith("https://") or text.startswith("http://")) and not any(
        yt in text for yt in ["youtube.com", "youtu.be"]
    ):
        console.print("[dim]URL detected — routing to article fetcher...[/dim]")
        from jarvis.article_fetcher import process_article_url

        timestamp = datetime.datetime.now().isoformat()
        result = process_article_url(text, "", timestamp)
        if result:
            sync_result = sync(
                f"feat: add article note — {result['title'][:50]} [knowledge-base]"
            )
            try:
                index_data = json.loads(INDEX_PATH.read_text())
                all_notes = index_data.get("notes", [])
                if all_notes:
                    run_linker_for_new_notes([all_notes[-1]])
            except Exception:
                pass
            console.print(f"[green]✓ Article saved: {result['folder_path']}/{result['filename']}[/green]")
        else:
            console.print("[red]Failed to process article.[/red]")
        return

    path = capture_note(text, source=source, source_url=url)
    body = f":white_heavy_check_mark:  {text}\n\nSource: {source}  Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nFile: {path}"
    console.print(Panel(body, title="Jarvis", border_style="green"))
    console.print("[dim]Processing...[/dim]")
    results = process_inbox(force=force)
    latest = _collect_latest_result(results.get("results", []), text, source, url)
    if latest and latest.get("classification"):
        timestamp = latest.get("timestamp")
        target_date = datetime.date.fromisoformat(timestamp[:10]) if timestamp else datetime.date.today()
        note_type = latest.get("note_type") or latest["classification"].get("type", "concept")
        append_to_log(text, source, url, note_type, latest["classification"], target_date=target_date)
        update_technologies(latest["classification"], target_date=target_date)
    console.print("[dim]✓ Done[/dim]")


@cli.command()
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Overwrite existing note if it already exists",
)
def process(force):
    """Process pending notes from the inbox."""
    files = list_pending()
    if not files:
        console.print("Inbox is empty — nothing to process.")
        return
    console.print(Panel(f"Found {len(files)} pending note(s)", title="Jarvis Processing", border_style="green"))
    result = process_inbox(force=force)
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


@cli.command(name="cleanup")
def cleanup_cmd():
    """Reclassify unsorted notes and sync changes."""
    reclassify_unsorted()
    sync_result = sync("fix: reclassify unsorted notes to correct folders")
    if sync_result.get("synced"):
        console.print(Panel("Cleanup complete and synced.", title="Jarvis Cleanup", border_style="green"))
    elif sync_result.get("committed") and sync_result.get("push_error"):
        console.print(Panel("Cleanup committed but push failed.", title="Jarvis Cleanup", border_style="yellow"))
    else:
        console.print(Panel("Cleanup complete.", title="Jarvis Cleanup", border_style="blue"))


@cli.command(name="index-clean")
def index_clean_cmd():
    """Remove stale index entries where files no longer exist."""
    console.print("[dim]Scanning index for stale entries...[/dim]")
    result = clean_index()
    sync_result = sync("fix: remove stale entries from index.json")
    console.print(
        Panel(
            f"Removed  : {result['removed']} stale entries\n"
            f"Remaining: {result['remaining']} valid entries\n"
            f"GitHub   : {'pushed' if sync_result.get('synced') else 'up to date'}",
            title="[bold]Jarvis — Index Cleanup[/bold]",
            border_style="green",
            width=50,
        )
    )


@cli.command(name="article")
@click.argument("url")
@click.option("--note", "personal_note", "-n", default="", help="Optional personal note or context about this article")
def article_cmd(url, personal_note):
    """Fetch and save an article as a structured knowledge note."""
    from jarvis.article_fetcher import process_article_url

    console.print(f"[dim]Fetching article...[/dim]")
    console.print(f"[dim]{url}[/dim]\n")

    timestamp = datetime.datetime.now().isoformat()
    result = process_article_url(url, personal_note, timestamp)

    if not result:
        console.print("[red]Failed to process article.[/red]")
        return

    sync_result = sync(
        f"feat: add article note — {result['title'][:50]} [knowledge-base]"
    )

    try:
        index_data = json.loads(INDEX_PATH.read_text())
        all_notes = index_data.get("notes", [])
        if all_notes:
            run_linker_for_new_notes([all_notes[-1]])
    except Exception:
        pass

    console.print(
        Panel(
            f"[bold green]✓ Article captured[/bold green]\n\n"
            f"Title  : {result['title'][:60]}\n"
            f"Site   : {result['site']}\n"
            f"Saved  : {result['folder_path']}/{result['filename']}\n"
            f"GitHub : {'pushed' if sync_result.get('synced') else 'synced'}",
            title="[bold]Jarvis — Article[/bold]",
            border_style="green",
            width=65,
        )
    )


@cli.command(name="youtube")
@click.argument("url")
def youtube_cmd(url):
    """Capture a YouTube video as a structured knowledge note."""
    console.print(f"[dim]Processing YouTube video...[/dim]")
    console.print(f"[dim]{url}[/dim]\n")

    timestamp = datetime.datetime.now().isoformat()
    result = process_youtube_url(url, timestamp)

    if not result:
        console.print("[red]Failed to process YouTube video.[/red]")
        return

    # Git sync
    sync_result = sync(
        f"feat: add video-summary — {result['title'][:50]} [creator-content]"
    )

    # Auto-link
    try:
        index_data = json.loads(INDEX_PATH.read_text())
        all_notes = index_data.get("notes", [])
        if all_notes:
            run_linker_for_new_notes([all_notes[-1]])
    except Exception:
        pass

    console.print(
        Panel(
            f"[bold green]✓ Video captured[/bold green]\n\n"
            f"Title   : {result['title'][:60]}\n"
            f"Channel : {result['channel']}\n"
            f"Saved   : {result['folder_path']}/{result['filename']}\n"
            f"GitHub  : {'pushed' if sync_result.get('synced') else 'synced'}",
            title="[bold]Jarvis — YouTube[/bold]",
            border_style="green",
            width=65,
        )
    )


@cli.command(name="dsa")
@click.option("--pattern", "pattern_filter", default="", help="Filter by DSA pattern")
def dsa_cmd(pattern_filter):
    """Show DSA notes grouped by pattern."""
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            idx = json.load(f)
            notes = idx.get("notes", []) if isinstance(idx, dict) else []
    except Exception:
        notes = []

    dsa_notes = [note for note in notes if note.get("type") == "dsa"]
    if pattern_filter:
        dsa_notes = [
            note
            for note in dsa_notes
            if (note.get("pattern") or note.get("dsa_pattern", "")) == pattern_filter
        ]

    grouped = {}
    for note in dsa_notes:
        pattern = note.get("pattern") or note.get("dsa_pattern", "arrays")
        grouped.setdefault(pattern, []).append(note)

    for pattern in sorted(grouped):
        items = grouped[pattern]
        console.print(f"{pattern} ({len(items)} notes)")
        for item in items:
            problem_number = item.get("problem_number", "")
            title = item.get("title", "Untitled")
            difficulty = item.get("difficulty", "")
            date = item.get("date", "")
            console.print(f"  {problem_number:<6} {title:<28} {difficulty:<7} {date}")

    console.print(f"Total DSA notes: {len(dsa_notes)}")


@cli.command()
@click.option("--domain", "-d", default=None, help="Only link notes in this domain")
def link(domain):
    """Add [[wikilinks]] to Related Topics sections across all notes."""
    console.print("[dim]Running cross-linker...[/dim]")

    from jarvis.git_sync import sync
    from jarvis.linker import load_index, run_linker

    all_notes = load_index()
    if domain:
        target = [note for note in all_notes if note.get("domain") == domain]
        console.print(f"[dim]Linking {len(target)} notes in domain: {domain}[/dim]")
    else:
        target = None
        console.print(f"[dim]Linking all {len(all_notes)} notes...[/dim]")

    result = run_linker(notes_to_link=target, verbose=True)
    sync_result = sync("feat: add wikilinks to related topics sections")

    console.print(
        Panel(
            f"Linked  : {result['linked']} notes\n"
            f"Skipped : {result['skipped']} notes\n"
            f"GitHub  : {'pushed' if sync_result.get('synced') else 'not pushed'}",
            title="[bold]Jarvis — Cross-Linker[/bold]",
            border_style="cyan",
            width=50,
        )
    )


@cli.command()
@click.argument("search_term")
def graph(search_term):
    """Show related notes for a given search term."""
    from jarvis.linker import find_related_notes, load_index

    all_notes = load_index()
    search_lower = search_term.lower()
    matches = [
        note
        for note in all_notes
        if search_lower in note.get("title", "").lower()
        or search_lower in " ".join(note.get("tags", [])).lower()
        or search_lower in note.get("subdomain", "").lower()
    ]

    if not matches:
        console.print(f"[dim]No notes found matching '{search_term}'[/dim]")
        return

    def _match_rank(entry):
        title = entry.get("title", "").lower()
        is_dsa = entry.get("type") == "dsa"
        exact = title == search_lower
        contains = search_lower in title
        return (is_dsa, exact, contains, len(title))

    matches.sort(key=_match_rank, reverse=True)
    note = matches[0]
    related = find_related_notes(note, all_notes, max_results=8)

    console.print(f"\n[bold]{note['title']}[/bold] [{note['domain']}]\n")

    if not related:
        console.print("[dim]No related notes found yet.[/dim]")
        return

    console.print("[bold]Related notes:[/bold]")
    for related_note in related:
        score_bar = "█" * min(related_note.get("score", 0), 8)
        console.print(
            f"  {score_bar} [dim]{related_note.get('score', 0)}pt[/dim]  "
            f"{related_note.get('title', '?')} [{related_note.get('domain', '?')}]"
        )


@cli.command()
@click.argument("number", type=int)
def lc(number):
    """Fetch and preview a LeetCode problem by number."""
    console.print(f"Fetching LC-{number}...")

    from jarvis.leetcode_fetcher import fetch_problem

    data = fetch_problem(number)
    if not data:
        console.print("[red]Could not fetch problem. Check connection.[/red]")
        return

    console.print(
        Panel(
            f"[bold]{data['problem_number']}. {data['title']}[/bold]\n\n"
            f"Difficulty : {data['difficulty']}\n"
            f"Tags       : {', '.join(data['tags'][:5])}\n"
            f"Companies  : {', '.join(data['companies'][:5]) or 'Not available'}\n"
            f"URL        : {data['url']}\n\n"
            f"[dim]{data['problem_summary'][:300]}...[/dim]",
            title="LeetCode Problem",
            border_style="yellow",
            width=70,
        )
    )


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
