"""Small, dependency-free helpers shared across modules."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_UNSAFE_SLUG = re.compile(r"[^a-z0-9一-鿿]+")


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def redact_home(value: str) -> str:
    """Replace the current user's home prefix with ``~``.

    Doctor output is uploaded as CI evidence; ``/home/runner/...`` identifies
    an account rather than a build. Both slash styles are handled so Windows
    output is covered too. Other users' home directories are left alone: the
    step must not pretend to sanitise what it did not recognise.
    """

    try:
        home = str(Path.home())
    except (RuntimeError, OSError):  # pragma: no cover - no home configured
        return value
    if not home or home in {"/", "\\"}:
        return value
    for prefix in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        if prefix:
            value = value.replace(prefix, "~")
    return value


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Always LF: `.gitattributes` normalises to LF, and Windows' default
    # newline translation would make generated files look modified.
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="\n")
    return path


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, data: Any, *, sort_keys: bool = False) -> Path:
    if isinstance(data, BaseModel):
        payload: Any = data.model_dump(mode="json")
    else:
        payload = data
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=sort_keys,
        default=_json_default,
    )
    return write_text(path, text)


def write_text_atomic(path: Path, text: str) -> Path:
    """Write beside the target, then ``os.replace``; never expose half a file.

    The temporary file is created exclusively with a random name. A fixed
    ``.tmp`` name could be pre-created as a symlink by another process with the
    same OS account, and a plain write would then follow it and clobber the
    link target.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text if text.endswith("\n") else text + "\n"
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # mkstemp creates 0600; keep the target's mode when it already exists.
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o644
        try:
            os.chmod(name, mode)
        except OSError:
            pass
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise
    return path


def write_json_atomic(path: Path, data: Any, *, sort_keys: bool = False) -> Path:
    if isinstance(data, BaseModel):
        payload: Any = data.model_dump(mode="json")
    else:
        payload = data
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=sort_keys,
        default=_json_default,
    )
    return write_text_atomic(path, text)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text_utf8(path: Path) -> str:
    """Read UTF-8 (with BOM) and fall back to GB18030 for Windows-authored files."""

    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str, *, max_length: int = 48) -> str:
    slug = _UNSAFE_SLUG.sub("-", value.strip().lower()).strip("-")
    return (slug or "source")[:max_length].strip("-") or "source"


_QUOTE_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        " ": " ",
        # HTML-to-text extraction inserts these around rendered math; they are
        # not part of the visible quote and must not defeat the substring test.
        "​": "",
        "‌": "",
        "‍": "",
        "⁠": "",
        "﻿": "",
        "­": "",
    }
)


def normalize_quote_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize a quote and keep a normalized-index -> original-index map.

    The map lets the locator turn a normalized match back into a contiguous
    slice of the original text. Only typography is changed (quotes, dashes,
    invisible characters, whitespace, case); math symbols are left alone.
    """

    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        translated = char.translate(_QUOTE_TRANSLATION)
        if not translated:
            continue
        for part in translated:
            if part.isspace():
                if not chars or chars[-1] == " ":
                    continue
                chars.append(" ")
                positions.append(index)
            else:
                for folded in part.lower():
                    chars.append(folded)
                    positions.append(index)
    start = 0
    end = len(chars)
    while start < end and chars[start] == " ":
        start += 1
    while end > start and chars[end - 1] == " ":
        end -= 1
    return "".join(chars[start:end]), positions[start:end]


def normalize_quote(text: str) -> str:
    """Normalise a quote for a whitespace/case/typography-tolerant match."""

    return normalize_quote_with_map(text)[0]


def truncate(text: str, limit: int, suffix: str = "\n...[truncated]") -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + suffix


def extract_json_object(text: str) -> Any:
    """Parse a JSON object from model output, tolerating code fences and prose."""

    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    for attempt in (candidate, _slice_braces(candidate)):
        if attempt is None:
            continue
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    raise ValueError("model output did not contain a parsable JSON object")


def _slice_braces(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
