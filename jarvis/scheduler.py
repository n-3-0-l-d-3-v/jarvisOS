import subprocess
import sys


def setup_scheduler():
    command = f'"{sys.executable}" -m jarvis.tasks finalize'
    schtasks_command = [
        "schtasks",
        "/create",
        "/tn",
        "JarvisDailyLog",
        "/tr",
        command,
        "/sc",
        "daily",
        "/st",
        "23:59",
        "/f",
    ]

    try:
        result = subprocess.run(schtasks_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            message = result.stdout.strip() or "Jarvis daily log scheduler configured successfully."
            print(message)
            return message
        error_message = result.stderr.strip() or result.stdout.strip() or "Unknown scheduler error"
        print(f"Failed to create scheduler: {error_message}")
        return f"Failed to create scheduler: {error_message}"
    except Exception as exception:
        message = f"Failed to create scheduler: {exception}"
        print(message)
        return message
