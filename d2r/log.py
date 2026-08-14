"""Persistent, rotating event log written next to the config file.

The Log tab renders events in memory; this module additionally appends them to
``config/autopotion.log`` so a session can be reviewed after the tool closes.
Stdlib only, thread-safe, and every public method is best-effort (never raises).
"""

from __future__ import annotations

import os
import threading
import time

from .config import CONFIG_DIR

LOG_PATH = os.path.join(CONFIG_DIR, "autopotion.log")
MAX_LOG_BYTES = 256 * 1024  # rotate the file when it exceeds this


class EventLog:
    def __init__(self, path: str = LOG_PATH, max_bytes: int = MAX_LOG_BYTES):
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def append(self, kind: str, message: str, timestamp: float | None = None) -> None:
        """Append one event line.  Never raises."""
        with self._lock:
            try:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(timestamp or time.time()))
                line = f"[{stamp}] {kind.upper():9s} {message}\n"
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                self._rotate()
            except Exception:
                pass

    def _rotate(self) -> None:
        """Drop the oldest lines until the file fits under max_bytes."""
        try:
            size = os.path.getsize(self.path)
            if size <= self.max_bytes:
                return
            with open(self.path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            if not lines:
                return
            total = sum(len(line) for line in lines)
            start = 0
            while start < len(lines) - 1 and total > self.max_bytes:
                total -= len(lines[start])
                start += 1
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write("".join(lines[start:]))
        except Exception:
            pass

    def clear(self) -> None:
        """Delete the log file.  Never raises."""
        with self._lock:
            try:
                if os.path.exists(self.path):
                    os.remove(self.path)
            except Exception:
                pass
