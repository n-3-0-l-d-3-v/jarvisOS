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
    finalize_log,
    generate_weekly_summary,
    get_log_path,
)
from .processor import process_inbox
from .scheduler import setup_scheduler, setup_rss_scheduler
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
@click.option(
    "--no-push",
    is_flag=True,
    default=False,
    help="Commit locally only — skip the GitHub push for instant capture (run 'jar push' later)",
)
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Use the full multi-section template instead of the lean default",
)
def note(text, source, url, force, no_push, full):
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

    extra = {"lean": False} if full else None
    path = capture_note(text, source=source, source_url=url, extra=extra)
    body = f":white_heavy_check_mark:  {text}\n\nSource: {source}  Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nFile: {path}"
    console.print(Panel(body, title="Jarvis", border_style="green"))
    console.print("[dim]Processing...[/dim]")
    # The orchestrator (process_single_note) writes the daily log and updates
    # technologies for each note as it is saved — it is the single source of
    # truth for logging, so we intentionally do not append here again.
    process_inbox(force=force, push=not no_push)
    console.print("[dim]✓ Done[/dim]")


@cli.command()
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Overwrite existing note if it already exists",
)
@click.option(
    "--no-push",
    is_flag=True,
    default=False,
    help="Commit locally only — skip the GitHub push (run 'jar push' later)",
)
def process(force, no_push):
    """Process pending notes from the inbox."""
    files = list_pending()
    if not files:
        console.print("Inbox is empty — nothing to process.")
        return
    console.print(Panel(f"Found {len(files)} pending note(s)", title="Jarvis Processing", border_style="green"))
    result = process_inbox(force=force, push=not no_push)
    console.print(f"Processed: {result['processed']} | Failed: {result['failed']}")


@cli.command(name="push")
def push_cmd():
    """Push any locally-committed notes to GitHub (use after 'jar note --no-push')."""
    from jarvis.git_sync import get_status, push_to_remote, stage_and_commit

    # Sweep up anything uncommitted first, then push everything.
    stage_and_commit("chore: jarvis batch sync")
    try:
        status = get_status()
        ahead = status.get("ahead", 0)
    except Exception:
        ahead = 0

    push_result = push_to_remote()
    if push_result.get("pushed"):
        console.print(
            Panel(
                f"Pushed {ahead if ahead else 'all pending'} local commit(s) to GitHub.",
                title="✓ Synced to GitHub",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"Push failed: {push_result.get('error', 'unknown')}\n"
                "Commits are safe locally — try again when online.",
                title="⚠ Push deferred",
                border_style="yellow",
            )
        )


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
@click.option("--rss", is_flag=True, default=False, help="Also schedule the daily RSS processor")
@click.option("--rss-time", default="08:00", help="Time of day for the RSS job (HH:MM)")
def schedule(rss, rss_time):
    """Set up the midnight log finalizer (and optionally the daily RSS job)."""
    messages = [setup_scheduler()]
    if rss:
        messages.append(setup_rss_scheduler(rss_time))
    body = "\n".join(messages)
    failed = any("Failed" in m for m in messages)
    console.print(Panel(body, title="Jarvis — Scheduler", border_style="red" if failed else "green"))


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
@click.option("--fix-domains", is_flag=True, default=False,
              help="Also repair domain values containing leaked AI prompt text")
def index_clean_cmd(fix_domains):
    """Remove stale index entries where files no longer exist."""
    console.print("[dim]Scanning index for stale entries...[/dim]")
    result = clean_index()

    from jarvis.index_store import dedupe_index

    dedup = dedupe_index()
    dedup_line = f"Duplicates: {dedup['removed']} collapsed\n" if dedup["removed"] else ""

    domain_line = ""
    if fix_domains:
        console.print("[dim]Repairing malformed domain values...[/dim]")
        from jarvis.index_cleaner import fix_domains as run_fix_domains

        fixed = run_fix_domains()
        domain_line = f"Domains  : {fixed['fixed']} repaired\n"

    sync_result = sync("fix: remove stale entries from index.json")
    console.print(
        Panel(
            f"Removed  : {result['removed']} stale entries\n"
            f"{dedup_line}"
            f"Remaining: {result['remaining']} valid entries\n"
            f"{domain_line}"
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


@cli.command(name="discord")
def discord_cmd():
    """Start the Jarvis Discord bot for mobile capture."""
    from jarvis.discord_bot import run_bot
    console.print(
        Panel(
            "Starting Jarvis Discord bot...\n\n"
            "Message your bot in Discord to capture notes.\n"
            "Press Ctrl+C to stop.\n\n"
            "Commands in Discord:\n"
            "  Any text    → saves as note\n"
            "  YouTube URL → saves as video\n"
            "  Article URL → saves as article\n"
            "  !status     → show stats\n"
            "  !today      → today's captures\n"
            "  !dsa        → DSA progress\n"
            "  !help       → show all commands",
            title="[bold]Jarvis — Discord Bot[/bold]",
            border_style="blue",
            width=55,
        )
    )
    run_bot()


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


@cli.command(name="daily")
@click.option("--date", "date_value", default=None, help="Briefing for a specific date (YYYY-MM-DD)")
def daily_cmd(date_value):
    """Your morning briefing: yesterday, what's due, and one next action."""
    from jarvis.briefing import build_briefing

    target = _parse_date_value(date_value) if date_value else None
    b = build_briefing(target_date=target)

    streak = b["streak"]
    flame = "🔥" if streak["current"] >= 3 else ""
    header = (
        f"[bold]{b['date']}[/bold]   "
        f"streak [bold cyan]{streak['current']}[/bold cyan]d {flame}  "
        f"[dim](best {streak['longest']}d · {b['total_notes']} notes)[/dim]"
    )
    console.print(Panel(header, title="[bold]Jarvis — Daily[/bold]",
                        border_style="cyan", width=76))

    if b["yesterday"]:
        console.print(f"\n[bold]Yesterday[/bold] [dim]({b['yesterday_count']} captured)[/dim]")
        for item in b["yesterday"]:
            console.print(f"  • {item['title'][:56]} [dim]{item['domain']}[/dim]")
    else:
        console.print("\n[dim]Nothing captured yesterday.[/dim]")

    if b["due"]:
        console.print(f"\n[bold]Due for review[/bold] [dim]({b['review'].get('due', 0)} total)[/dim]")
        for item in b["due"]:
            late = f"[red]{item['overdue_days']}d late[/red]" if item["overdue_days"] else "[dim]due[/dim]"
            console.print(f"  • {item['title'][:48]:<48} {late}")

    if b["actions"]:
        console.print("\n[bold]Next[/bold]")
        for action in b["actions"]:
            console.print(f"  [cyan]→[/cyan] {action['text']}")

    if b["today_count"]:
        console.print(f"\n[dim]Already captured {b['today_count']} today.[/dim]")
    console.print()


@cli.command(name="listen")
@click.option("--seconds", "-s", default=0, type=int,
              help="Record for a fixed number of seconds (0 = until you press Enter)")
@click.option("--file", "audio_file", default=None,
              help="Transcribe an existing audio file instead of recording")
@click.option("--ask", "ask_mode", is_flag=True, default=False,
              help="Treat what you say as a question and answer it from your notes")
@click.option("--dry-run", is_flag=True, default=False,
              help="Transcribe and show the text without capturing it")
def listen_cmd(seconds, audio_file, ask_mode, dry_run):
    """Speak a note (or a question) instead of typing it."""
    from jarvis.voice import has_microphone, record_fixed, record_until, transcribe_file

    if audio_file:
        path = audio_file
        console.print(f"[dim]Transcribing {audio_file}...[/dim]")
    else:
        if not has_microphone():
            console.print("[red]No microphone detected.[/red] "
                          "Use --file to transcribe an audio file instead.")
            return
        if seconds > 0:
            console.print(f"[bold cyan]🎙  Recording {seconds}s...[/bold cyan]")
            path = record_fixed(seconds)
        else:
            console.print("[bold cyan]🎙  Recording — press Enter to stop.[/bold cyan]")
            import threading

            done = threading.Event()

            def _wait_for_enter():
                try:
                    input()
                except Exception:
                    pass
                done.set()

            threading.Thread(target=_wait_for_enter, daemon=True).start()
            path = record_until(done.is_set)
        console.print("[dim]Transcribing...[/dim]")

    text = transcribe_file(path)
    if not text:
        console.print("[red]Could not transcribe (no speech detected, or "
                      "Groq unavailable — run 'jar doctor').[/red]")
        return

    console.print(Panel(text, title="[bold]Heard[/bold]", border_style="cyan", width=80))

    if dry_run:
        return

    if ask_mode:
        from jarvis.retrieval import ask

        result = ask(text)
        console.print(
            Panel(result["answer"], title="[bold]Jarvis — Answer[/bold]",
                  border_style="green", width=88)
        )
        return

    path_obj = capture_note(text, source="voice", source_url="")
    console.print("[dim]Processing...[/dim]")
    process_inbox(force=False, push=True)
    console.print("[dim]✓ Captured[/dim]")


@cli.command(name="wiki")
@click.argument("topic", required=False)
@click.option("--all", "synth_all", is_flag=True, default=False,
              help="Synthesize every suggested cluster")
@click.option("--min-size", default=2, type=int, help="Min notes to form a cluster")
@click.option("--dry-run", is_flag=True, default=False, help="Preview without writing or calling AI")
def wiki_cmd(topic, synth_all, min_size, dry_run):
    """Synthesize scattered notes into ONE authoritative wiki page per topic."""
    from jarvis.wiki import build_index, suggest_topics, synthesize_topic

    if not topic and not synth_all:
        clusters = suggest_topics(min_size=min_size)
        if not clusters:
            console.print("[dim]No clusters big enough to synthesize yet.[/dim]")
            return
        console.print(f"\n[bold]{len(clusters)} topic(s) worth synthesizing[/bold]")
        console.print("[dim]Run: jar wiki \"<topic>\"[/dim]\n")
        for c in clusters[:20]:
            bar = "█" * min(c["count"], 12)
            console.print(f"  [cyan]{bar:<12}[/cyan] [bold]{c['topic']}[/bold] "
                          f"[dim]({c['count']} notes, by {c['basis']})[/dim]")
        return

    targets = ([c["topic"] for c in suggest_topics(min_size=min_size)]
               if synth_all else [topic])

    built = 0
    for name in targets:
        console.print(f"[dim]Synthesizing '{name}'...[/dim]")
        result = synthesize_topic(name, dry_run=dry_run)
        if not result["count"]:
            console.print(f"  [yellow]No notes found for '{name}'[/yellow]")
            continue
        built += 1
        tag = "AI" if result["used_ai"] else "fallback"
        console.print(
            f"  [green]✓[/green] {name} — merged [bold]{result['count']}[/bold] "
            f"notes [dim]({tag})[/dim]"
        )
        if dry_run:
            console.print(f"  [dim]sources: {', '.join(result['sources'][:6])}[/dim]")

    if built and not dry_run:
        index_result = build_index()
        console.print(
            Panel(
                f"Synthesized : {built} topic page(s)\n"
                f"Wiki index  : {index_result['path']}\n\n"
                f"[dim]Your raw notes are untouched — wiki pages cite them.[/dim]",
                title="[bold]Jarvis — Wiki[/bold]", border_style="green", width=72,
            )
        )


@cli.command(name="review")
@click.option("--limit", "-n", default=10, type=int, help="How many notes to review")
@click.option("--domain", "-d", default=None, help="Only review one domain")
@click.option("--list", "list_only", is_flag=True, default=False,
              help="Just list what's due, don't run the session")
def review_cmd(limit, domain, list_only):
    """Resurface notes due for revision (spaced repetition)."""
    from jarvis.review import due_notes, record_review, review_stats

    due = due_notes(limit=limit, domain=domain)
    stats = review_stats()

    if not due:
        console.print(
            Panel(f"Nothing due for review.\n\nTracked: {stats['tracked']} notes | "
                  f"Mastered: {stats['mastered']}",
                  title="Jarvis — Review", border_style="green", width=60)
        )
        return

    console.print(
        Panel(f"{len(due)} note(s) due for review\n"
              f"[dim]Tracked: {stats['tracked']} | Mastered: {stats['mastered']}[/dim]",
              title="[bold]Jarvis — Review[/bold]", border_style="cyan", width=60)
    )

    if list_only:
        for item in due:
            overdue = f"[red]{item['overdue_days']}d overdue[/red]" if item["overdue_days"] else "[dim]due[/dim]"
            console.print(f"  • {item['title'][:50]:<50} {overdue}  [dim]L{item['level']}[/dim]")
        return

    for index, item in enumerate(due, 1):
        console.print(f"\n[bold cyan]{index}/{len(due)}[/bold cyan]  "
                      f"[bold]{item['title']}[/bold] [dim]({item['domain']})[/dim]")
        console.print(f"[dim]{item['path']}[/dim]")
        answer = click.prompt("  Still know it? [y]es / [n]o / [s]kip / [q]uit",
                              default="y", show_default=False)
        answer = (answer or "y").strip().lower()[:1]
        if answer == "q":
            break
        if answer == "s":
            continue
        record_review(item["key"], remembered=(answer == "y"))
        console.print("  [green]✓ scheduled further out[/green]" if answer == "y"
                      else "  [yellow]↺ reset to tomorrow[/yellow]")

    console.print("\n[dim]Review session done.[/dim]")


@cli.command(name="quiz")
@click.option("--count", "-n", default=5, type=int, help="Number of questions")
@click.option("--domain", "-d", default=None, help="Restrict to one domain")
@click.option("--type", "note_type", default=None, help="Restrict to a note type (e.g. dsa)")
def quiz_cmd(count, domain, note_type):
    """Quiz yourself on your own notes (great before interviews)."""
    from jarvis.review import generate_quiz

    console.print("[dim]Building quiz from your notes...[/dim]\n")
    questions = generate_quiz(count=count, domain=domain, note_type=note_type)

    if not questions:
        console.print("[dim]No notes matched — capture some first.[/dim]")
        return

    score = 0
    for index, item in enumerate(questions, 1):
        console.print(f"[bold cyan]Q{index}.[/bold cyan] {item['question']}")
        click.prompt("  [press Enter to reveal]", default="", show_default=False)
        console.print(f"  [green]Answer:[/green] {item.get('answer', '(see note)')}")
        if item.get("source"):
            console.print(f"  [dim]from: {item['source']}[/dim]")
        got_it = click.prompt("  Did you get it? [y/n]", default="y", show_default=False)
        if (got_it or "y").strip().lower().startswith("y"):
            score += 1
        console.print()

    console.print(
        Panel(f"Score: {score}/{len(questions)}",
              title="Jarvis — Quiz", border_style="cyan", width=40)
    )


@cli.command(name="export")
@click.option("--domain", "-d", default=None, help="Export one domain")
@click.option("--tag", "-t", default=None, help="Export everything with a tag")
@click.option("--type", "note_type", default=None, help="Export one note type")
@click.option("--query", "-q", default=None, help="Export notes matching a search")
@click.option("--limit", default=None, type=int, help="Max notes to include")
@click.option("--title", default=None, help="Document title")
@click.option("--output", "-o", default=None, help="Write to this path")
@click.option("--no-toc", is_flag=True, default=False, help="Skip the table of contents")
def export_cmd(domain, tag, note_type, query, limit, title, output, no_toc):
    """Compile notes into ONE shareable Markdown document."""
    from jarvis.exporter import export

    if not any([domain, tag, note_type, query]):
        console.print("[yellow]Pick at least one filter: --domain / --tag / --type / --query[/yellow]")
        return

    console.print("[dim]Building document...[/dim]")
    result = export(domain=domain, tag=tag, note_type=note_type, query=query,
                    limit=limit, title=title, output=output, include_toc=not no_toc)

    console.print(
        Panel(
            f"Title : {result['title']}\n"
            f"Notes : {result['count']}\n"
            f"Saved : {result['path']}",
            title="[bold]Jarvis — Export[/bold]",
            border_style="green", width=76,
        )
    )


@cli.command(name="open")
@click.argument("query")
def open_cmd(query):
    """Find the best-matching note and open it in your default editor."""
    import subprocess
    import sys as _sys

    from jarvis.retrieval import search_notes

    results = search_notes(query, limit=1)
    if not results:
        console.print(f"[dim]No note matches '{query}'.[/dim]")
        return

    target = results[0]
    console.print(f"[green]Opening:[/green] {target['title']} [dim]{target['path']}[/dim]")
    try:
        if _sys.platform.startswith("win"):
            import os

            os.startfile(target["path"])  # noqa: S606 - user-initiated
        elif _sys.platform == "darwin":
            subprocess.run(["open", target["path"]], check=False)
        else:
            subprocess.run(["xdg-open", target["path"]], check=False)
    except Exception as exc:
        console.print(f"[yellow]Could not open automatically: {exc}[/yellow]")
        console.print(f"[dim]{target['path']}[/dim]")


@cli.command(name="doctor")
@click.option("--details", "-d", is_flag=True, default=False,
              help="List the actual files in each category")
@click.option("--stale-days", default=90, type=int, help="Age before a note counts as stale")
def doctor_cmd(details, stale_days):
    """Health-check your knowledge base and report what needs fixing."""
    from jarvis.health import check_health, health_score, summarize

    console.print("[dim]Scanning knowledge base...[/dim]\n")
    findings = check_health(stale_days=stale_days)
    score = health_score(findings)

    colour = "green" if score >= 85 else "yellow" if score >= 60 else "red"
    console.print(
        Panel(
            f"[bold {colour}]Health score: {score}/100[/bold {colour}]\n"
            f"{findings['total_indexed']} notes indexed",
            title="[bold]Jarvis — Doctor[/bold]",
            border_style=colour,
            width=60,
        )
    )

    # AI connectivity — a deprecated model silently disables classification,
    # summaries, and synthesis, so check it explicitly rather than discovering
    # it weeks later through bad note titles.
    from jarvis.ai import health as ai_health

    console.print("\n[bold]AI providers[/bold]")
    ai = ai_health()
    for provider in ("groq", "gemini"):
        info = ai[provider]
        if info["ok"]:
            console.print(f"  [green]✓[/green] {provider}: [dim]{info['model']}[/dim]")
        else:
            console.print(f"  [red]✗[/red] {provider}: [dim]{info['error'][:70]}[/dim]")
    if not ai["any"]:
        console.print("  [red]No AI provider is reachable — Jarvis is running on the "
                      "offline keyword classifier only.[/red]")
    console.print()

    icons = {"error": "[red]✗[/red]", "warn": "[yellow]![/yellow]", "info": "[dim]·[/dim]"}
    for severity, label, count, hint in summarize(findings):
        if count == 0:
            console.print(f"  [green]✓[/green] {label}: [dim]none[/dim]")
        else:
            console.print(f"  {icons[severity]} {label}: [bold]{count}[/bold]  [dim]→ {hint}[/dim]")

    if details:
        for key in ("missing_files", "duplicate_rows", "empty_notes",
                    "broken_links", "untracked_files", "stale_notes"):
            items = findings[key]
            if not items:
                continue
            console.print(f"\n[bold]{key.replace('_', ' ').title()}[/bold]")
            for item in items[:15]:
                console.print(f"  [dim]{item}[/dim]")
            if len(items) > 15:
                console.print(f"  [dim]... and {len(items) - 15} more[/dim]")


@cli.command(name="reindex")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be added without writing")
def reindex_cmd(dry_run):
    """Re-add notes that exist on disk but are missing from index.json."""
    from jarvis.health import reindex

    console.print("[dim]Scanning repo for unindexed notes...[/dim]")
    result = reindex(dry_run=dry_run)
    added = result["added"]

    if not added:
        console.print(
            Panel(f"All {result['scanned']} notes on disk are indexed.",
                  title="Jarvis — Reindex", border_style="green", width=60)
        )
        return

    for item in added[:20]:
        console.print(f"  [green]+[/green] {item['title'][:45]} [dim]{item['file']}[/dim]")
    if len(added) > 20:
        console.print(f"  [dim]... and {len(added) - 20} more[/dim]")

    verb = "Would add" if dry_run else "Added"
    console.print(
        Panel(
            f"{verb}: {len(added)} note(s)\nScanned: {result['scanned']} files on disk"
            + ("\n\n[dim]Dry run — nothing written.[/dim]" if dry_run else ""),
            title="Jarvis — Reindex", border_style="green", width=60,
        )
    )


@cli.command(name="search")
@click.argument("query")
@click.option("--limit", "-n", default=10, type=int, help="Max results")
def search_cmd(query, limit):
    """Full-text search across your note contents (offline, instant)."""
    from jarvis.retrieval import search_notes

    results = search_notes(query, limit=limit)
    if not results:
        console.print(f"[dim]No notes match '{query}'.[/dim]")
        return

    console.print(f"\n[bold]{len(results)} result(s) for[/bold] [cyan]{query}[/cyan]\n")
    for r in results:
        bar = "█" * min(r["score"] // 3, 8)
        console.print(
            f"[dim]{bar:<8}[/dim] [bold]{r['title']}[/bold] "
            f"[dim][{r['folder_path']}/{r['filename']}][/dim]"
        )
        console.print(f"          [dim]{r['snippet'][:150]}[/dim]\n")


@cli.command(name="ask")
@click.argument("question")
def ask_cmd(question):
    """Ask a question and get an answer synthesized from your own notes."""
    from jarvis.retrieval import ask

    console.print("[dim]Searching your notes...[/dim]")
    result = ask(question)

    source_titles = ", ".join(s["title"] for s in result["sources"][:5])
    footer = ""
    if result["sources"]:
        tag = "AI" if result["used_ai"] else "search"
        footer = f"\n\n[dim]Based on {len(result['sources'])} note(s) via {tag}: {source_titles}[/dim]"

    console.print(
        Panel(
            result["answer"] + footer,
            title=f"[bold]Jarvis — {question[:50]}[/bold]",
            border_style="cyan",
            width=88,
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


@cli.command(name="rss")
@click.option("--no-sync", is_flag=True, default=False, help="Do not push to GitHub after saving")
def rss_cmd(no_sync):
    """Fetch developer RSS feeds and save relevant items as notes."""
    from jarvis.rss_processor import process_feeds

    console.print("[dim]Running RSS processor...[/dim]")
    summary = process_feeds(sync_git=not no_sync)

    files_block = (
        "\n".join(f"  • {f}" for f in summary["files"])
        if summary["files"]
        else "  (nothing new to save)"
    )
    console.print(
        Panel(
            f"Fetched : {summary['fetched']} items\n"
            f"New     : {summary['new']} (after dedupe)\n"
            f"Saved   : {summary['saved']} relevant note(s)\n"
            f"{files_block}",
            title="[bold]Jarvis — RSS[/bold]",
            border_style="green",
            width=64,
        )
    )


@cli.command(name="serve")
@click.option("--host", default="127.0.0.1", help="Host to bind (use 0.0.0.0 to allow LAN/phone access)")
@click.option("--port", default=7823, type=int, help="Port to serve on")
def serve_cmd(host, port):
    """Start the local web dashboard + capture API (bookmarklet backend)."""
    display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    dashboard_url = f"http://{display_host}:{port}/dashboard"
    console.print(
        Panel(
            f"[bold green]Jarvis API server starting...[/bold green]\n\n"
            f"Dashboard : [link]{dashboard_url}[/link]\n"
            f"Health    : http://{display_host}:{port}/health\n"
            f"Repo      : {REPO_PATH}\n\n"
            f"Open the dashboard, then drag the [bold]⚡ Save to Jarvis[/bold] button\n"
            f"to your bookmarks bar to capture pages from any browser.\n\n"
            f"[dim]Press Ctrl+C to stop.[/dim]",
            title="[bold]Jarvis — Serve[/bold]",
            border_style="green",
            width=68,
        )
    )
    from jarvis.api_server import run_server

    try:
        run_server(host=host, port=port)
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/dim]")


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
