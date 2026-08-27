import subprocess
import sys


def _create_task(task_name, task_arg, run_time):
    """Create (or replace) a Windows Scheduled Task that runs a jarvis task."""
    command = f'"{sys.executable}" -m jarvis.tasks {task_arg}'
    schtasks_command = [
        "schtasks",
        "/create",
        "/tn",
        task_name,
        "/tr",
        command,
        "/sc",
        "daily",
        "/st",
        run_time,
        "/f",
    ]

    try:
        result = subprocess.run(schtasks_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            message = result.stdout.strip() or f"Scheduled task '{task_name}' configured for {run_time} daily."
            print(message)
            return message
        error_message = result.stderr.strip() or result.stdout.strip() or "Unknown scheduler error"
        print(f"Failed to create scheduler: {error_message}")
        return f"Failed to create scheduler: {error_message}"
    except Exception as exception:
        message = f"Failed to create scheduler: {exception}"
        print(message)
        return message


def setup_scheduler():
    """Daily log finalizer at 23:59."""
    return _create_task("JarvisDailyLog", "finalize", "23:59")


def setup_rss_scheduler(run_time="08:00"):
    """Daily RSS feed processor (default 08:00)."""
    return _create_task("JarvisRSS", "rss", run_time)
