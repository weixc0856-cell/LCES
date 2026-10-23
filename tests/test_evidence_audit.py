"""P2.3-E: evidence must not carry secrets or user-home paths."""

from __future__ import annotations

import json
import os

from content_studio.evidence_audit import audit_evidence


def test_clean_evidence_passes(tmp_path):
    (tmp_path / "encode_report.json").write_text(
        json.dumps(
            {
                "command": [
                    "ffmpeg",
                    "-i",
                    "<build>/frames/project/%06d.png",
                    "-y",
                    "<build>/media/course.mp4",
                ],
                "manifest_sha256": "f" * 64,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "doctor.txt").write_text(
        "解释器: /app/.venv/bin/python\n模板目录: /app/templates\n", encoding="utf-8"
    )
    (tmp_path / "e2e.log").write_text(
        "collected 6 items from /tmp/lces-p1-builds/test_x\n", encoding="utf-8"
    )
    assert audit_evidence(tmp_path) == []


def test_home_path_in_json_fails(tmp_path):
    (tmp_path / "report.json").write_text(
        json.dumps({"command": ["-i", "/home/alice/work/frames/project/%06d.png"]}),
        encoding="utf-8",
    )
    findings = audit_evidence(tmp_path)
    assert len(findings) == 1
    assert findings[0].path == "report.json"
    assert findings[0].line == 1
    assert findings[0].kind == "home-path"
    assert "/home/alice" not in findings[0].preview


def test_macos_and_windows_home_paths_fail(tmp_path):
    (tmp_path / "a.txt").write_text("root: /Users/bob/project\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("root: C:\\Users\\carol\\project\n", encoding="utf-8")
    findings = audit_evidence(tmp_path)
    assert {finding.kind for finding in findings} == {"home-path"}
    assert {finding.path for finding in findings} == {"a.txt", "b.txt"}


def test_secret_patterns_fail(tmp_path):
    (tmp_path / "keys.txt").write_text(
        "sk-abcdefghijklmnopqrstuvwxyz012345\n"
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    findings = audit_evidence(tmp_path)
    assert len(findings) == 3
    assert all(finding.kind == "secret" for finding in findings)
    assert all("abcdefghijklmnop" not in finding.preview for finding in findings)


def test_binary_files_are_skipped(tmp_path):
    (tmp_path / "after.png").write_bytes(b"\x00\x01sk-abcdefghijklmnopqrstuvwxyz012345")
    (tmp_path / "blob.bin").write_bytes(b"\x00/home/alice/x")
    assert audit_evidence(tmp_path) == []


def test_symlinks_are_not_followed(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("/home/alice/secret\n", encoding="utf-8")
    link = tmp_path / "evidence" / "link.txt"
    link.parent.mkdir()
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        import pytest

        pytest.skip("this host cannot create symlinks without extra privileges")
    assert audit_evidence(tmp_path / "evidence") == []
