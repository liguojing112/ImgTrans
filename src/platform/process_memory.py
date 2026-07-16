from __future__ import annotations

import ctypes
import os
from pathlib import Path
import platform
from threading import Event, Thread
from time import sleep


def process_rss_bytes() -> int:
    system = platform.system()
    if system == "Windows":
        return _windows_rss()
    if system == "Linux":
        statm = Path("/proc/self/statm").read_text(encoding="ascii").split()
        return int(statm[1]) * os.sysconf("SC_PAGE_SIZE")
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage) if system == "Darwin" else int(usage) * 1024


class PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.01) -> None:
        if interval_seconds <= 0:
            raise ValueError("RSS sample interval must be positive")
        self._interval = interval_seconds
        self._stop = Event()
        self._thread: Thread | None = None
        self.peak_bytes = 0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("RSS sampler is already running")
        self.peak_bytes = process_rss_bytes()
        self._stop.clear()
        self._thread = Thread(target=self._sample, name="imgtrans-rss", daemon=True)
        self._thread.start()

    def stop(self) -> int:
        thread = self._thread
        if thread is None:
            return self.peak_bytes
        self._stop.set()
        thread.join(timeout=1)
        self.peak_bytes = max(self.peak_bytes, process_rss_bytes())
        self._thread = None
        return self.peak_bytes

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak_bytes = max(self.peak_bytes, process_rss_bytes())
            sleep(self._interval)


def _windows_rss() -> int:
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        )

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    )
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    process = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    ):
        raise OSError("Unable to read process memory information")
    return int(counters.WorkingSetSize)
