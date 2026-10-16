"""SmartCar Session Logger — Logs all events with timestamps to file + console."""

import os
import time
from datetime import datetime


class SessionLogger:
    """Logs events to a timestamped file in logs/ folder."""

    def __init__(self):
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.filepath = os.path.join(log_dir, f"session_{timestamp}.log")
        self.start_time = time.time()
        self._write_header()

    def _write_header(self):
        with open(self.filepath, "w") as f:
            f.write("=" * 60 + "\n")
            f.write(f"  SmartCar Session Log\n")
            f.write(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")

    def log(self, category, message):
        """Log an event. Category: MOTOR, AI, MODE, LED, BUZZER, SYSTEM, etc."""
        now = datetime.now().strftime("%H:%M:%S")
        elapsed = time.time() - self.start_time
        line = f"[{now}] [{elapsed:7.1f}s] [{category:10s}] {message}"
        print(line)
        try:
            with open(self.filepath, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def get_summary(self):
        """Return session summary for Telegram."""
        duration = round(time.time() - self.start_time)
        mins = duration // 60
        secs = duration % 60
        try:
            with open(self.filepath, "r") as f:
                lines = f.readlines()
            total_events = len([l for l in lines if l.startswith("[")])
            motor_events = len([l for l in lines if "MOTOR" in l])
            ai_events = len([l for l in lines if "AI" in l])
            mode_events = len([l for l in lines if "MODE" in l])
        except Exception:
            total_events = motor_events = ai_events = mode_events = 0

        return {
            "duration": f"{mins}m {secs}s",
            "total_events": total_events,
            "motor_events": motor_events,
            "ai_events": ai_events,
            "mode_events": mode_events,
            "log_file": self.filepath,
        }
