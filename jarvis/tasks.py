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


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "finalize":
        _run_finalize()
    elif command == "rss":
        _run_rss()
    else:
        print("Usage: python -m jarvis.tasks [finalize|rss]")


if __name__ == "__main__":
    main()
