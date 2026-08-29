import sys
from datetime import date

from jarvis.daily_log import finalize_log, generate_weekly_summary


def _run_finalize():
    finalize_message = finalize_log()
    print(finalize_message)

    if date.today().weekday() == 6:
        weekly_path = generate_weekly_summary()
        print(f"Weekly summary saved to: {weekly_path}")


def _run_rss():
    from jarvis.rss_processor import process_feeds

    summary = process_feeds()
    print(
        f"RSS: fetched {summary['fetched']}, new {summary['new']}, "
        f"saved {summary['saved']}"
    )


def _run_curate():
    """The external clock for the curator.

    Scheduled rather than agent-initiated on purpose: a maintenance rule that
    exists is not a maintenance rule that runs. Only SAFE actions execute here;
    anything destructive is journalled for the human.
    """
    from jarvis.curator import run_cycle

    result = run_cycle(dry_run=False)
    done = sum(1 for e in result["entries"] if e["done"])
    deferred = len(result["entries"]) - done
    print(
        f"Curate: cycle {result['cycles']}, {done} action(s) applied, "
        f"{deferred} deferred, health "
        f"{result['score_before']} -> {result['score_after']}"
    )


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "finalize":
        _run_finalize()
    elif command == "rss":
        _run_rss()
    elif command == "curate":
        _run_curate()
    else:
        print("Usage: python -m jarvis.tasks [finalize|rss|curate]")


if __name__ == "__main__":
    main()
