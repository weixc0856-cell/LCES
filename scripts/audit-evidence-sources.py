#!/usr/bin/env python
"""Read-only source check for the structured evidence reviews (P9-D, item 1).

    python scripts/audit-evidence-sources.py \
        --project projects/attention-is-all-you-need \
        --out var/evidence-source-audit

It answers, deterministically:

- does every review item name a real source, chunk and locator?
- do the numbers in the claim occur in that chunk?
- if not, where do they occur, and is the locator/chunk label consistent?
- what do the conflict values look like in the source?
- which items still have no human conclusion?

It never concludes "supported". It writes `*.json` and `*.md` and says
`NOT_SIGNED`; a person still has to review every item.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

NUMBER = re.compile(r"\d+\.\d+|\b\d{2,}\b")
SECTION = re.compile(r"§\s*(\d+(?:\.\d+)*)")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_newlines(raw: bytes) -> str:
    """Decode UTF-8 and normalise CRLF/CR to LF (the source-map offset space)."""

    return raw.decode("utf-8").replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))


def extract_numbers(text: str) -> list[str]:
    """Numeric values, excluding section references and four-digit years."""

    cleaned = SECTION.sub(" ", text)
    seen: list[str] = []
    for value in NUMBER.findall(cleaned):
        if len(value) == 4 and value.isdigit() and 1900 <= int(value) <= 2099:
            continue
        if value not in seen:
            seen.append(value)
    return seen


def text_occurrences(value: str, text: str, chunks: list[dict]) -> list[dict[str, object]]:
    """Find a value in the full text and name every chunk its span touches.

    A number can straddle a chunk boundary (for example ``26.30`` split into
    ``2`` + ``6.30``); searching per-chunk slices would miss it and wrongly
    report "not found".
    """

    found: list[dict[str, object]] = []
    start = 0
    while len(found) < 8:
        position = text.find(value, start)
        if position < 0:
            break
        span_end = position + len(value)
        owners = [
            chunk["chunk_id"]
            for chunk in chunks
            if chunk["char_start"] < span_end and position < chunk["char_end"]
        ]
        window_start = max(0, position - 60)
        window_end = min(len(text), span_end + 60)
        found.append(
            {
                "chunk_id": "+".join(owners) if owners else "unmapped",
                "section": "; ".join(
                    chunk.get("section", "") for chunk in chunks if chunk["chunk_id"] in owners
                ),
                "snippet": " ".join(text[window_start:window_end].split()),
                "crosses_boundary": len(owners) > 1,
            }
        )
        start = position + 1
    return found


def _section_drift(locator: str, section: str) -> bool:
    match = SECTION.search(locator or "")
    if not match or not section:
        return False
    return not section.lstrip().startswith(match.group(1))


def audit(project: Path) -> dict:
    internal = project / "internal"
    review = json.loads((internal / "qa" / "structured_evidence_review.json").read_text("utf-8"))
    source_map = json.loads((internal / "source_map.json").read_text("utf-8"))
    registry = json.loads((internal / "source_registry.json").read_text("utf-8"))
    status_by_source = {
        item["source_id"]: item.get("access_status", "") for item in registry.get("sources", [])
    }

    documents = {}
    for document in source_map.get("documents", []):
        source_id = document["source_id"]
        text_path = internal / "sources" / f"{source_id}.txt"
        raw = text_path.read_bytes() if text_path.is_file() else b""
        # The source map offsets are computed on normalised newlines; the file
        # itself may be stored with CRLF. Hash the bytes, slice the text view.
        text = normalize_newlines(raw) if raw else ""
        documents[source_id] = {
            "document": document,
            "text": text,
            "text_present": bool(text),
            "hash_ok": bool(
                document.get("extracted_txt_sha256")
                and sha256_bytes(raw) == document.get("extracted_txt_sha256")
            ),
            "chunks": {chunk["chunk_id"]: chunk for chunk in document.get("chunks", [])},
            "texts": {
                chunk["chunk_id"]: text[chunk["char_start"] : chunk["char_end"]]
                for chunk in document.get("chunks", [])
            },
        }

    items = []
    for item in review.get("items", []):
        source_id = item.get("source_id", "")
        document = documents.get(source_id)
        chunk_id = item.get("chunk_id", "")
        chunk = document["chunks"].get(chunk_id) if document else None
        chunk_text = document["texts"].get(chunk_id, "") if document else ""
        numbers = extract_numbers(item.get("claim", ""))
        present = [value for value in numbers if value in chunk_text]
        missing = [value for value in numbers if value not in chunk_text]
        alternatives = {
            value: text_occurrences(value, document["text"], list(document["chunks"].values()))
            if document
            else []
            for value in missing
        }
        verification = item.get("research_verification") or []
        if isinstance(verification, dict):
            verification = [verification]
        substantive = item.get("substantive_review") or []
        if isinstance(substantive, dict):
            substantive = [substantive]

        problems: list[str] = []
        notes: list[str] = []
        if document is None:
            problems.append("source not in source_map")
        elif not document["text_present"]:
            problems.append("source text missing")
        elif not document["hash_ok"]:
            problems.append("extracted text hash mismatch")
        if chunk is None:
            problems.append("chunk not found")
        if document and chunk and not item.get("locator", "").strip():
            problems.append("locator empty")
        section_drift = bool(
            document and chunk and _section_drift(item.get("locator", ""), chunk.get("section", ""))
        )
        if section_drift:
            notes.append("chunk section label differs from locator (known drift)")
        if missing:
            problems.append("claim values missing from named chunk")
        if item.get("conflict_status") not in (None, "", "none") and not verification:
            problems.append("conflict without research verification")
        if not verification:
            problems.append("no research verification recorded")

        items.append(
            {
                "review_id": item.get("review_id", ""),
                "claim": item.get("claim", ""),
                "source_id": source_id,
                "source_access": status_by_source.get(source_id, "unknown"),
                "chunk_id": chunk_id,
                "chunk_section": (chunk or {}).get("section", ""),
                "locator": item.get("locator", ""),
                "numbers": numbers,
                "numbers_present": present,
                "numbers_missing": missing,
                "alternatives": alternatives,
                "conflict_status": item.get("conflict_status", "none"),
                "section_drift": section_drift,
                "notes": notes,
                "research_findings": [entry.get("research_finding", "") for entry in verification],
                "ai_review": len(substantive),
                "human_conclusion": item.get("conclusion", "pending"),
                "problems": problems,
            }
        )

    conflicts = {}
    for value in ("41.0", "41.8"):
        occurrences = []
        for source_id, document in documents.items():
            occurrences.extend(
                {
                    "source_id": source_id,
                    **occurrence,
                }
                for occurrence in text_occurrences(
                    value, document["text"], list(document["chunks"].values())
                )
            )
        conflicts[value] = occurrences

    return {
        "project_id": review.get("project_id", ""),
        "note": "Read-only source check. Not a signature and not a support judgment.",
        "sources": {
            source_id: {
                "access": status_by_source.get(source_id, "unknown"),
                "text_present": document["text_present"],
                "extracted_hash_ok": document["hash_ok"],
                "chunks": len(document["chunks"]),
                "text_chars": len(document["text"]),
            }
            for source_id, document in documents.items()
        },
        "summary": {
            "items": len(items),
            "pending": sum(1 for item in items if item["human_conclusion"] == "pending"),
            "values_checked": sum(len(item["numbers"]) for item in items),
            "values_missing": sum(len(item["numbers_missing"]) for item in items),
            "items_with_missing_values": sum(1 for item in items if item["numbers_missing"]),
            "items_with_problems": sum(1 for item in items if item["problems"]),
            "conflicts": sum(1 for item in items if item["conflict_status"] not in ("", "none")),
        },
        "items": items,
        "conflict_occurrences": conflicts,
    }


def render(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# 证据来源核查报告（P9-D，只读）",
        "",
        f"**项目：** `{report.get('project_id', '')}`  ",
        "**状态：** `NOT_SIGNED` — 本报告只做来源/定位/数值一致性检查，不判断主张是否成立，",
        "不改变任何复核结论。  ",
        "**生成方式：** `scripts/audit-evidence-sources.py`（只读）。",
        "",
        "## 1. 汇总",
        "",
        f"- 复核项：{summary['items']}；仍为 pending：{summary['pending']}",
        f"- 检查数值：{summary['values_checked']}；未出现在指定区块：{summary['values_missing']}",
        f"- 含缺失数值的条目：{summary['items_with_missing_values']}；"
        f"有问题标记的条目：{summary['items_with_problems']}",
        f"- 来源冲突条目：{summary['conflicts']}",
        "",
        "### 来源完整性",
        "",
        "| 来源 | 可访问状态 | 文本存在 | 抽取哈希匹配 | 区块数 | 字符数 |",
        "|---|---|---|---|---|---|",
    ]
    for source_id, info in report["sources"].items():
        lines.append(
            f"| {source_id} | {info['access']} | {info['text_present']} | "
            f"{info['extracted_hash_ok']} | {info['chunks']} | {info['text_chars']} |"
        )
    lines.extend(
        [
            "",
            "> 哈希匹配只证明文本与 source map 一致；外部 URL 的可访问性未联网核验。",
            "",
            "## 2. 逐项核查",
            "",
            "| review_id | 区块 | 数值（缺失） | 区块标签/定位 | 冲突 | 人工结论 | 问题与建议 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for item in report["items"]:
        missing = ", ".join(item["numbers_missing"]) or "—"
        values = f"{len(item['numbers'])}（{missing}）"
        drift = "标签漂移（提示）" if item.get("section_drift") else "—"
        advice = "；".join([*item["problems"], *item.get("notes", [])]) or (
            "数值在指定区块内；语义仍需人工判断"
        )
        lines.append(
            f"| `{item['review_id']}` | {item['chunk_id']} | {values} | {drift} | "
            f"{item['conflict_status']} | {item['human_conclusion']} | {advice} |"
        )

    missing_items = [item for item in report["items"] if item["numbers_missing"]]
    if missing_items:
        lines.extend(["", "## 3. 缺失数值的实际位置", ""])
        for item in missing_items:
            lines.append(f"### `{item['review_id']}`")
            lines.append("")
            lines.append(
                f"- 指定区块：`{item['chunk_id']}`（section 标签 `{item['chunk_section']}`）"
            )
            for value in item["numbers_missing"]:
                found = item["alternatives"].get(value) or []
                if not found:
                    lines.append(f"- `{value}`：在全文未找到")
                    continue
                places = ", ".join(str(entry["chunk_id"]) for entry in found[:4])
                boundary = "（跨区块边界）" if found[0].get("crosses_boundary") else ""
                lines.append(f"- `{value}`：出现在 {places}{boundary}")
                snippet = found[0]["snippet"]
                lines.append(f"  - 片段：{snippet}")
            lines.append("")

    lines.extend(["", "## 4. 41.0 / 41.8 的原文位置", ""])
    for value, occurrences in report["conflict_occurrences"].items():
        lines.append(f"### {value}")
        lines.append("")
        if not occurrences:
            lines.append("- 未在抽取文本中找到")
        for entry in occurrences[:8]:
            lines.append(
                f"- `{entry['source_id']}` / `{entry['chunk_id']}`"
                f"（section `{entry['section']}`）：{entry['snippet']}"
            )
        lines.append("")

    lines.extend(
        [
            "## 5. 建议的人工动作",
            "",
            "1. 对每个缺失数值条目：确认应改锚到实际区块，还是记录跨区块引用；"
            "不得为了通过审计而删改数值。",
            "2. 对区块标签与 locator 不一致的条目：注明已知标签漂移，并保留真实定位依据。",
            "3. 41.0/41.8：按原文位置分别记录版本、上下文与口径，"
            "保留冲突或写明裁决依据；不得由本报告代替裁决。",
            "4. 所有结论、姓名、日期仍由复核人填写；本报告不改变 `pending`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Output prefix (no suffix)")
    args = parser.parse_args()
    report = audit(args.project.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    md_path = args.out.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render(report), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(
        f"items={report['summary']['items']} missing_values={report['summary']['values_missing']} "
        f"conflicts={report['summary']['conflicts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
