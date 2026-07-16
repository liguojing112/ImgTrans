from __future__ import annotations

from threading import Event, Thread
import os
import time

import psutil


class PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.01) -> None:
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self.peak = 0
        self._thread: Thread | None = None

    def __enter__(self) -> "PeakRssSampler":
        process = psutil.Process(os.getpid())

        def sample() -> None:
            while not self._stop.is_set():
                self.peak = max(self.peak, process.memory_info().rss)
                time.sleep(self.interval_seconds)

        self._thread = Thread(target=sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

