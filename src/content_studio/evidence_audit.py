"""Audit uploaded evidence for secrets and host paths (P2.3-E).

Evidence is copied out of the build directory and uploaded as CI artifacts.
Passing tests do not make a leaked key or a runner's home path harmless: the
artifact outlives the build. This module scans the evidence tree for the two
things that must never appear there:

* secrets: API keys, bearer tokens, private-key blocks;
* user home paths: ``/home/<name>``, ``/Users/<name>``, ``C:\\Users\\<name>``.

Runner temp paths (``/tmp/...``, ``/__w/...``) and relative build paths are
not findings; they do not identify a person or a credential. Binary files are
skipped by extension and by a NUL byte in the first kilobyte.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SKIP_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".mp4",
        ".webm",
        ".mp3",
        ".wav",
        ".zip",
        ".gz",
        ".xz",
        ".pdf",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
    }
)
MAX_BYTES = 8 * 1024 * 1024

HOME_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:/(?:home|Users)/[A-Za-z0-9._-]+(?:/|$)"
    r"|[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9._-]+)"
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{24,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    preview: str

    def line_text(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.preview}"


def _redact(line: str, match: re.Match[str]) -> str:
    return (line[: match.start()] + "<redacted>" + line[match.end() :]).strip()[:120]


def _iter_files(root: Path) -> Iterator[Path]:
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        for name in sorted(filenames):
            candidate = Path(directory) / name
            if candidate.is_symlink():
                continue
            if candidate.suffix.lower() in SKIP_EXTENSIONS:
                continue
            try:
                if candidate.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield candidate


def _scan_file(path: Path, root: Path) -> Iterator[Finding]:
    try:
        payload = path.read_bytes()
    except OSError:
        return
    if b"\x00" in payload[:1024]:
        return
    relative = path.relative_to(root).as_posix()
    for number, raw in enumerate(payload.decode("utf-8", errors="replace").splitlines(), 1):
        home = HOME_PATH.search(raw)
        if home:
            yield Finding(relative, number, "home-path", _redact(raw, home))
        for pattern in SECRET_PATTERNS:
            match = pattern.search(raw)
            if match:
                yield Finding(relative, number, "secret", _redact(raw, match))
                break


def audit_evidence(root: Path) -> list[Finding]:
    """Every secret or home path under *root*, in stable path/line order."""

    findings: list[Finding] = []
    for path in _iter_files(root):
        findings.extend(_scan_file(path, root))
    return findings
