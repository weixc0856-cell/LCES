"""Source maps: page, section and chunk boundaries for ingested text.

The stored ``internal/sources/<source>.txt`` remains the single source of
truth for quotes and excerpts. The map only records where each character came
from, so sectioned research can cover the whole document without a head-only
character budget.

Chunks tile the text exactly: chunk *n* starts where chunk *n-1* ends. A chunk
never crosses a PDF page boundary, and an oversized paragraph is split at a
newline or sentence boundary so no chunk exceeds ``MAX_CHUNK_CHARS``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from content_studio.errors import IngestionError
from content_studio.models import (
    SourceChunk,
    SourceDocumentMap,
    SourceMap,
    SourceRegistry,
)
from content_studio.utils import normalize_quote, read_text_utf8, utc_now, write_json

MAX_CHUNK_CHARS = 2000
# Bump when chunk/section boundaries change; maps without this marker are rebuilt.
SOURCE_MAP_VERSION = "2"

_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(?P<title>.+)$")
_NUMBER = re.compile(r"^\d+(?:\.\d+){0,2}$")
_TITLE_LIKE = re.compile(r"^[A-Z][^\n]{2,59}$")
_NUMBERED_ONE_LINE = re.compile(r"^(?P<num>\d+(?:\.\d+){0,2})\s+(?P<title>[A-Z][^\n]{0,60})$")
_NAMED_HEADING = re.compile(
    r"^(?P<title>Abstract|Introduction|Background|Related Work|Method|Methods"
    r"|Experiments?|Results?|Discussion|Conclusions?|References|Limitations?)$",
    re.IGNORECASE,
)


def _page_spans(
    text: str, pages: list[tuple[int, str]] | None
) -> list[tuple[int | None, int, int]]:
    """Return contiguous ``(page, start, end)`` spans that tile *text*."""

    if not pages:
        return [(None, 0, len(text))]

    usable = [(number, page_text) for number, page_text in pages if page_text]
    if not usable:
        # A scanned PDF with no extractable text is stored as a placeholder;
        # keep one span so the source map still tiles the stored text.
        return [(None, 0, len(text))]
    joined = "\n\n".join(page_text for _, page_text in usable)
    if joined != text:
        raise IngestionError(
            "page texts do not reconstruct the stored source text; "
            "refusing to build a source map with wrong offsets"
        )

    spans: list[tuple[int | None, int, int]] = []
    cursor = 0
    for index, (number, page_text) in enumerate(usable):
        start = cursor
        end = start + len(page_text)
        if index + 1 < len(usable):
            end += 2  # include the "\n\n" separator between pages
        spans.append((number, start, end))
        cursor = end
    return spans


def _blocks(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split a span into blocks at blank lines, covering every character."""

    segment = text[start:end]
    raw: list[tuple[int, int]] = []
    position = 0
    for match in re.finditer(r"(?:\r?\n){2,}", segment):
        if match.start() >= position:
            raw.append((start + position, start + match.end()))
        position = match.end()
    if position < len(segment):
        raw.append((start + position, end))

    cleaned: list[tuple[int, int]] = []
    pending: int | None = None
    for block_start, block_end in raw:
        if not text[block_start:block_end].strip():
            if cleaned:
                cleaned[-1] = (cleaned[-1][0], block_end)
            elif pending is None:
                pending = block_start
            continue
        if pending is not None:
            block_start = pending
            pending = None
        cleaned.append((block_start, block_end))
    if pending is not None:
        if cleaned:
            cleaned[-1] = (cleaned[-1][0], end)
        else:
            cleaned = [(pending, end)]
    return cleaned


def _split_oversize(text: str, start: int, end: int) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > MAX_CHUNK_CHARS:
        window = text[cursor : cursor + MAX_CHUNK_CHARS]
        cut = max(
            window.rfind("\n"),
            window.rfind("。"),
            window.rfind("；"),
            window.rfind(". "),
        )
        if cut < MAX_CHUNK_CHARS // 2:
            cut = MAX_CHUNK_CHARS
        else:
            cut += 1
        pieces.append((cursor, cursor + cut))
        cursor += cut
    if cursor < end:
        pieces.append((cursor, end))
    return pieces


def _is_section_number(value: str) -> bool:
    """Reject table values such as ``91.7``; section numbers start at 1-20."""

    if not _NUMBER.match(value):
        return False
    try:
        return int(value.split(".", 1)[0]) <= 20
    except ValueError:  # pragma: no cover - the regex already guarantees digits
        return False


def detect_heading(block_text: str) -> str:
    """Return a section label when the block starts with a heading.

    HTML-to-text extraction often puts the heading and the first paragraph in
    the same block ("3.2.1\\nScaled Dot-Product Attention\\nWe call..."), so the
    check looks at the first two lines rather than the whole block. Numbered
    lines inside figure descriptions ("6\\nN=6"), author blocks
    ("1\\nAffiliation:") and table values ("91.7\\nTransformer (4 layers)") are
    rejected.
    """

    stripped = block_text.strip()
    if not stripped:
        return ""
    lines = [line.strip() for line in stripped.split("\n") if line.strip()]
    if not lines:
        return ""
    first = lines[0]
    markdown = _MARKDOWN_HEADING.match(first)
    if markdown:
        return markdown.group("title").strip()
    named = _NAMED_HEADING.match(first)
    if named:
        return named.group("title").strip()
    if len(lines) >= 2 and _is_section_number(first):
        second = lines[1]
        if (
            _TITLE_LIKE.match(second)
            and not second.endswith(":")
            and not second.endswith(".")
            and "=" not in second
            and "," not in second
            and ";" not in second
            and len(second) <= 60
        ):
            return f"{first} {second}"
    one_line = _NUMBERED_ONE_LINE.match(first)
    if one_line and _is_section_number(one_line.group("num")):
        return f"{one_line.group('num')} {one_line.group('title').strip()}"
    return ""


def _find_headings(text: str) -> list[tuple[int, str]]:
    """Locate headings by line, independent of blank-line paragraph blocks.

    HTML-to-text output often keeps a single newline between every line, so
    waiting for blank-line blocks would miss every heading.
    """

    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    position = 0
    for line in lines:
        starts.append(position)
        position += len(line)

    headings: list[tuple[int, str]] = []
    consumed: set[int] = set()
    for index, line in enumerate(lines):
        if index in consumed:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        markdown = _MARKDOWN_HEADING.match(stripped)
        if markdown:
            headings.append((starts[index], markdown.group("title").strip()))
            continue
        named = _NAMED_HEADING.match(stripped)
        if named:
            headings.append((starts[index], named.group("title").strip()))
            continue
        one_line = _NUMBERED_ONE_LINE.match(stripped)
        if one_line and _is_section_number(one_line.group("num")):
            headings.append(
                (
                    starts[index],
                    f"{one_line.group('num')} {one_line.group('title').strip()}",
                )
            )
            continue
        if _is_section_number(stripped) and index + 1 < len(lines):
            second = lines[index + 1].strip()
            if (
                _TITLE_LIKE.match(second)
                and not second.endswith(":")
                and not second.endswith(".")
                and "=" not in second
                and "," not in second
                and ";" not in second
                and len(second) <= 60
            ):
                headings.append((starts[index], f"{stripped} {second}"))
                consumed.add(index + 1)
    return headings


def _section_at(headings: list[tuple[int, str]], start: int, end: int) -> str:
    for offset, label in headings:
        if start <= offset < end:
            return label
    current = ""
    for offset, label in headings:
        if offset <= start:
            current = label
        else:
            break
    return current


def build_document_map(
    source_id: str,
    text: str,
    *,
    pages: list[tuple[int, str]] | None = None,
    sha256: str = "",
    parser: str = "",
    raw_archive_sha256: str = "",
) -> SourceDocumentMap:
    if not text:
        raise IngestionError(f"cannot build a source map for empty source {source_id}")

    headings = _find_headings(text)
    heading_offsets = [offset for offset, _ in headings]
    chunks: list[SourceChunk] = []
    for page, span_start, span_end in _page_spans(text, pages):
        for block_start, block_end in _blocks(text, span_start, span_end):
            # Start a new segment at every heading inside the block, so a
            # chunk never mixes two sections and its label is exact.
            boundaries = [
                block_start,
                *[offset for offset in heading_offsets if block_start < offset < block_end],
                block_end,
            ]
            for segment_start, segment_end in zip(boundaries, boundaries[1:], strict=False):
                if segment_end <= segment_start:
                    continue
                for chunk_start, chunk_end in _split_oversize(text, segment_start, segment_end):
                    if chunk_end <= chunk_start:
                        continue
                    index = len(chunks)
                    chunks.append(
                        SourceChunk(
                            chunk_id=f"{source_id}:b{index:04d}",
                            index=index,
                            page=page,
                            section=_section_at(headings, chunk_start, chunk_end),
                            char_start=chunk_start,
                            char_end=chunk_end,
                            text_chars=chunk_end - chunk_start,
                        )
                    )

    if not chunks:
        chunks.append(
            SourceChunk(
                chunk_id=f"{source_id}:b0000",
                index=0,
                section=_section_at(headings, 0, len(text)),
                char_start=0,
                char_end=len(text),
                text_chars=len(text),
            )
        )

    base = parser or "text/v1"
    mode = "sections" if headings else "paragraphs"
    return SourceDocumentMap(
        source_id=source_id,
        sha256=sha256 or raw_archive_sha256,
        raw_archive_sha256=raw_archive_sha256 or sha256,
        extracted_txt_sha256=sha256_text(text),
        normalized_locator_sha256=normalized_locator_sha256(text),
        parser=f"{base}+v{SOURCE_MAP_VERSION}+{mode}",
        text_chars=len(text),
        chunks=chunks,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_locator_sha256(text: str) -> str:
    """Hash of the text exactly as the quote locator compares it.

    Three different byte objects appear around one source, and reviewers need
    to know which is which:

    - ``raw_archive_sha256``: the downloaded/original file bytes;
    - ``extracted_txt_sha256``: ``internal/sources/<id>.txt`` as stored;
    - ``normalized_locator_sha256``: the same text after
      :func:`content_studio.utils.normalize_quote` (typography and whitespace
      only), which is what quote matching actually sees.
    """

    return sha256_text(normalize_quote(text))


def load_source_map(project_dir: Path) -> SourceMap | None:
    path = project_dir / "internal" / "source_map.json"
    if not path.exists():
        return None
    try:
        return SourceMap.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise IngestionError(f"invalid source map: {path}: {exc}") from exc


def write_source_map(project_dir: Path, source_map: SourceMap) -> Path:
    path = project_dir / "internal" / "source_map.json"
    write_json(path, source_map)
    return path


def ensure_source_map(
    project_dir: Path,
    project_id: str,
    registry: SourceRegistry,
) -> SourceMap:
    """Load the map, or build one for projects ingested before maps existed."""

    existing = load_source_map(project_dir)
    if existing is not None:
        mapped = {document.source_id for document in existing.documents}
        current = all(
            f"+v{SOURCE_MAP_VERSION}+" in document.parser
            and bool(document.extracted_txt_sha256 and document.normalized_locator_sha256)
            for document in existing.documents
        )
        if current and {record.source_id for record in registry.sources} <= mapped:
            return existing

    documents: list[SourceDocumentMap] = []
    for record in registry.sources:
        text = read_text_utf8(project_dir / "internal" / "sources" / f"{record.source_id}.txt")
        if not text:
            continue
        documents.append(
            build_document_map(
                record.source_id,
                text,
                sha256=record.sha256 or "",
                parser=f"{record.kind}/v1",
            )
        )
    source_map = SourceMap(project_id=project_id, generated_at=utc_now(), documents=documents)
    write_source_map(project_dir, source_map)
    return source_map


def chunk_text(text: str, chunk: SourceChunk) -> str:
    return text[chunk.char_start : chunk.char_end]
