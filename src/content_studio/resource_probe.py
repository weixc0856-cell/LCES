"""Resource observation for P3-B.

This module measures; it does not limit. A render is sampled in a background
thread for the process tree's RSS, the descendant count and the size of the
build directory, and the peaks are reported with the method and interval.

A failed measurement is recorded as ``None`` plus an entry in ``unavailable``.
It is never reported as zero: "we could not measure" and "it used nothing"
must not look the same in an evidence file.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PROC = Path("/proc")


def _ppid_map() -> dict[int, int]:
    parents: dict[int, int] = {}
    try:
        entries = list(PROC.iterdir())
    except OSError:
        return parents
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # The command name may contain spaces and parentheses; fields resume
        # after the last ')'. Field 1 is state, field 2 is ppid.
        _, _, rest = stat.rpartition(") ")
        fields = rest.split()
        if len(fields) >= 2:
            try:
                parents[int(entry.name)] = int(fields[1])
            except ValueError:
                continue
    return parents


def tree_pids(root_pid: int) -> list[int]:
    parents = _ppid_map()
    children: dict[int, list[int]] = {}
    for pid, parent in parents.items():
        children.setdefault(parent, []).append(pid)
    seen = {root_pid}
    stack = [root_pid]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return sorted(seen)


def _rss_bytes(pid: int) -> int | None:
    try:
        text = (PROC / str(pid) / "status").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            try:
                return int(parts[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def dir_bytes(root: Path) -> int:
    total = 0
    for directory, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            try:
                total += (Path(directory) / name).stat().st_size
            except OSError:
                continue
    return total


@dataclass
class ResourceProbe:
    root: Path
    interval_s: float = 0.5
    samples: int = 0
    peak_rss_bytes: int = 0
    peak_child_processes: int = 0
    peak_disk_bytes: int = 0
    unavailable: list[str] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _pid: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __enter__(self) -> ResourceProbe:
        self._pid = os.getpid()
        self._sample()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> Literal[False]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._sample()
        return False

    def _sample(self) -> None:
        with self._lock:
            pids = tree_pids(self._pid)
            rss = 0
            read_any = False
            for pid in pids:
                value = _rss_bytes(pid)
                if value is None:
                    # A short-lived child (vite probe, esbuild) can vanish
                    # between the tree walk and the read. Its memory was
                    # already captured by earlier samples; ignore the miss.
                    continue
                read_any = True
                rss += value
            if read_any:
                self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
            elif "rss" not in self.unavailable:
                self.unavailable.append("rss")
            self.peak_child_processes = max(self.peak_child_processes, max(0, len(pids) - 1))
            try:
                size = dir_bytes(self.root)
            except OSError:
                if "disk" not in self.unavailable:
                    self.unavailable.append("disk")
            else:
                self.peak_disk_bytes = max(self.peak_disk_bytes, size)
            self.samples += 1

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._sample()

    def report(self) -> dict[str, Any]:
        rss_missing = "rss" in self.unavailable
        disk_missing = "disk" in self.unavailable
        return {
            "method": "process-tree RSS + build-directory size sampling",
            "interval_s": self.interval_s,
            "samples": self.samples,
            "peak_rss_bytes": None if rss_missing else self.peak_rss_bytes,
            "peak_child_processes": self.peak_child_processes,
            "peak_disk_bytes": None if disk_missing else self.peak_disk_bytes,
            "unavailable": list(self.unavailable),
        }
