from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from content_studio.cli import app
from content_studio.review_packets import build_packet, build_packets
from content_studio.structured_review import default_review_path, load_review
from test_course_audit import _project


def _item(root: Path):
    return load_review(default_review_path(root)).items[0]


def test_packet_has_source_usage_questions_and_pending_signature(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
    )

    packet = build_packet(root, _item(root))

    assert packet.review_id == "review-table2-enfr"
    assert packet.packet_sha256 and len(packet.packet_sha256) == 64
    assert packet.source.unresolved is False
    assert packet.source.excerpt
    assert packet.source.locator == "§6.1"
    assert packet.paper_title == "Table 2"
    assert any("41.8" in usage.text for usage in packet.course_usage)
    assert packet.reviewer_questions
    assert packet.conclusion_options == ["pass", "needs_revision", "blocked", "fail"]
    assert packet.current_conclusion == "pending"
    assert packet.signature["reviewer"] == ""
    assert packet.signature["conclusion"] == "pending"
    assert "--conflict-ack" in packet.cli_command


def test_packet_hash_is_stable(tmp_path):
    root, _config = _project(tmp_path)

    first = build_packet(root, _item(root))
    second = build_packet(root, _item(root))

    assert first.packet_sha256 == second.packet_sha256


def test_missing_source_is_marked_unresolved(tmp_path):
    root, _config = _project(tmp_path, source_present=False)

    packet = build_packet(root, _item(root))

    assert packet.source.unresolved is True
    assert "not found" in packet.source.note


def test_build_packets_writes_index_and_each_record(tmp_path):
    root, _config = _project(tmp_path)
    output = tmp_path / "packets"

    entries, index = build_packets(root, output)

    assert len(entries) == 1
    assert (output / "index.json").is_file()
    assert (output / "index.md").is_file()
    packet = json.loads((output / f"{entries[0].review_id}.json").read_text(encoding="utf-8"))
    assert packet["packet_sha256"] == entries[0].packet_sha256
    assert index.review_file_sha256
    assert index.source_text_sha256


def test_cli_exports_packets(tmp_path, monkeypatch):
    root, _config = _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "export-review-packets",
            str(root),
            "--output",
            str(tmp_path / "exported"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "exported" / "index.json").is_file()
