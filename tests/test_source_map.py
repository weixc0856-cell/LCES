from __future__ import annotations

from pathlib import Path

import pytest

from content_studio.errors import IngestionError
from content_studio.models import SourceMap
from content_studio.source_map import (
    MAX_CHUNK_CHARS,
    build_document_map,
    chunk_text,
    detect_heading,
    ensure_source_map,
)
from content_studio.utils import write_json

LONG_PARAGRAPH = "这是一个很长的段落。" * 400


def _text() -> str:
    return (
        "Title page\n\n"
        "1\nIntroduction\n\n"
        "The first paragraph explains the problem.\n\n"
        "3\nModel Architecture\n\n"
        "3.2.1\nScaled Dot-Product Attention\n\n" + LONG_PARAGRAPH + "\n\n"
        "6\nResults\n\n"
        "Table 2 reports 28.4 BLEU.\n"
    )


def test_chunks_tile_the_whole_text():
    text = _text()
    document = build_document_map("source-001", text)

    assert document.text_chars == len(text)
    assert document.chunks[0].char_start == 0
    assert document.chunks[-1].char_end == len(text)
    for previous, current in zip(document.chunks, document.chunks[1:], strict=False):
        assert current.char_start == previous.char_end
        assert current.index == previous.index + 1
    assert sum(chunk.text_chars for chunk in document.chunks) == len(text)


def test_chunks_never_exceed_the_size_limit():
    document = build_document_map("source-001", _text())
    assert max(chunk.text_chars for chunk in document.chunks) <= MAX_CHUNK_CHARS
    assert len(document.chunks) > 1


def test_sections_are_detected_and_carried_forward():
    text = _text()
    document = build_document_map("source-001", text)

    assert detect_heading("3.2.1\nScaled Dot-Product Attention") == (
        "3.2.1 Scaled Dot-Product Attention"
    )
    assert detect_heading("## Method") == "Method"
    assert detect_heading("This is a normal paragraph, not a heading.") == ""
    # HTML extraction keeps the heading and the first paragraph in one block.
    assert (
        detect_heading(
            "3.2.1\nScaled Dot-Product Attention\nWe call our particular attention "
            '"Scaled Dot-Product Attention".'
        )
        == "3.2.1 Scaled Dot-Product Attention"
    )
    # Figure labels and author blocks must not become sections.
    assert detect_heading("6\nN=6\nd_model") == ""
    assert detect_heading("1\nAffiliation:\nGoogle Brain") == ""
    # A table value followed by a short label is not a section heading.
    assert detect_heading("91.7\nTransformer (4 layers)") == ""
    # A line-wrapped sentence is not a heading either.
    assert detect_heading("2.0\nBLEU, establishing a new state-of-the-art BLEU score of") == ""

    sections = [chunk.section for chunk in document.chunks]
    assert "1 Introduction" in sections
    assert "3.2.1 Scaled Dot-Product Attention" in sections
    assert "6 Results" in sections
    assert "+sections" in document.parser


def test_headings_survive_single_newline_extraction():
    # HTML-to-text output keeps one newline per line, without blank lines.
    text = (
        "Title page\n"
        "Abstract\n"
        "The paper reports results.\n"
        "1\n"
        "Introduction\n"
        "The problem is described here.\n"
        "3.2.1\n"
        "Scaled Dot-Product Attention\n"
        "We call our attention scaled.\n"
    )
    document = build_document_map("source-001", text)

    sections = {chunk.section for chunk in document.chunks}
    assert "Abstract" in sections
    assert "1 Introduction" in sections
    assert "3.2.1 Scaled Dot-Product Attention" in sections
    assert "+sections" in document.parser


def test_page_spans_keep_page_numbers():
    page_one = "Abstract\n\nFirst page text."
    page_two = "6\nResults\n\nSecond page text."
    text = f"{page_one}\n\n{page_two}"
    document = build_document_map(
        "source-001",
        text,
        pages=[(1, page_one), (2, ""), (3, page_two)],
        parser="pdf/v1",
    )

    pages = {chunk.page for chunk in document.chunks}
    assert pages == {1, 3}
    assert document.chunks[-1].char_end == len(text)


def test_scanned_pdf_without_text_keeps_a_placeholder_chunk():
    document = build_document_map(
        "source-001",
        "[NO EXTRACTED TEXT]",
        pages=[(1, ""), (2, "")],
        parser="pdf/v1",
    )
    assert len(document.chunks) == 1
    assert document.chunks[0].page is None
    assert document.chunks[0].char_end == len("[NO EXTRACTED TEXT]")


def test_page_mismatch_is_rejected_instead_of_producing_wrong_offsets():
    with pytest.raises(IngestionError, match="reconstruct"):
        build_document_map("source-001", "different text", pages=[(1, "page one")])


def test_ensure_source_map_backfills_old_projects(tmp_path: Path):
    (tmp_path / "internal" / "sources").mkdir(parents=True)
    (tmp_path / "internal" / "sources" / "source-001.txt").write_text(
        "# Heading\n\nBody text.\n", encoding="utf-8"
    )
    registry = _registry()

    source_map = ensure_source_map(tmp_path, "demo", registry)

    assert source_map.documents[0].source_id == "source-001"
    assert (tmp_path / "internal" / "source_map.json").is_file()
    stored = SourceMap.model_validate_json(
        (tmp_path / "internal" / "source_map.json").read_text(encoding="utf-8")
    )
    assert stored.documents[0].chunks[0].chunk_id == "source-001:b0000"


def test_chunk_text_returns_the_exact_slice():
    text = _text()
    document = build_document_map("source-001", text)
    for chunk in document.chunks:
        assert chunk_text(text, chunk) == text[chunk.char_start : chunk.char_end]


def _registry():
    from content_studio.models import SourceRecord, SourceRegistry

    return SourceRegistry(
        project_id="demo",
        sources=[
            SourceRecord(
                source_id="source-001",
                title="Demo",
                kind="markdown",
                origin="input/demo.md",
            )
        ],
    )


def test_source_map_roundtrip(tmp_path: Path):
    document = build_document_map("source-001", _text())
    source_map = SourceMap(project_id="demo", documents=[document])
    path = write_json(tmp_path / "map.json", source_map)
    loaded = SourceMap.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded == source_map
