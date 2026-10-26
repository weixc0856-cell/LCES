"""The D source audit must align CRLF files with the source-map offsets."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "scripts" / "audit-evidence-sources.py"
    spec = importlib.util.spec_from_file_location("audit_sources", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_numbers_skips_section_refs_and_years():
    numbers = _module().extract_numbers(
        "§6.1 Table 2 (arXiv:1706.03762v7, 2017): 27.3 and 41.0; 4000 steps"
    )

    assert "27.3" in numbers
    assert "41.0" in numbers
    assert "4000" in numbers
    assert "6.1" not in numbers
    assert "2017" not in numbers


def test_audit_aligns_crlf_files_with_normalised_offsets(tmp_path):
    project = tmp_path / "project"
    (project / "internal" / "qa").mkdir(parents=True)
    (project / "internal" / "sources").mkdir(parents=True)
    raw = b"Title\nA 27.3 B\nC 41.8 D\n".replace(b"\n", b"\r\n")
    (project / "internal" / "sources" / "source-001.txt").write_bytes(raw)
    text = "Title\nA 27.3 B\nC 41.8 D\n"
    chunks = [
        {
            "chunk_id": "source-001:b0000",
            "index": 0,
            "page": None,
            "section": "Abstract",
            "char_start": 0,
            "char_end": len(text),
            "text_chars": len(text),
        }
    ]
    (project / "internal" / "source_map.json").write_text(
        json.dumps(
            {
                "project_id": "demo",
                "documents": [
                    {
                        "source_id": "source-001",
                        "extracted_txt_sha256": hashlib.sha256(raw).hexdigest(),
                        "chunks": chunks,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (project / "internal" / "source_registry.json").write_text(
        json.dumps(
            {
                "project_id": "demo",
                "sources": [{"source_id": "source-001", "access_status": "fetched"}],
            }
        ),
        encoding="utf-8",
    )
    (project / "internal" / "qa" / "structured_evidence_review.json").write_text(
        json.dumps(
            {
                "project_id": "demo",
                "items": [
                    {
                        "review_id": "review-001",
                        "source_id": "source-001",
                        "chunk_id": "source-001:b0000",
                        "locator": "§1",
                        "claim": "27.3 and 41.8",
                        "conflict_status": "none",
                        "research_verification": [{"research_finding": "verified"}],
                        "conclusion": "pending",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = _module().audit(project)

    assert report["sources"]["source-001"]["extracted_hash_ok"] is True
    assert report["items"][0]["numbers_missing"] == []
    assert report["summary"]["values_missing"] == 0
