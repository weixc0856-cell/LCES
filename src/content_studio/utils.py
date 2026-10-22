"""Small, dependency-free helpers shared across modules."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_UNSAFE_SLUG = re.compile(r"[^a-z0-9一-鿿]+")


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


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
    """Write beside the target, then ``os.replace``; never expose half a file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = text if text.endswith("\n") else text + "\n"
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
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
