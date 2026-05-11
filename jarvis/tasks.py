import sys
from datetime import date

from jarvis.daily_log import finalize_log, generate_weekly_summary


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "finalize":
        print("Usage: python -m jarvis.tasks finalize")
        return

    finalize_message = finalize_log()
    print(finalize_message)

    if date.today().weekday() == 6:
        weekly_path = generate_weekly_summary()
        print(f"Weekly summary saved to: {weekly_path}")


if __name__ == "__main__":
    main()
