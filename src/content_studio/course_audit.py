"""Read-only course-content consistency audit.

The evidence review proves that a record links to a real source. This module
proves something different: that the numbers, formulas and claims a course
actually shows are the ones the reviewed evidence supports.

It is deliberately deterministic. A string match cannot prove semantics, so
the audit only reports what it can check:

- BLEU values stated in the course must be supported by a review record;
- a value that is part of a source conflict must be disclosed with the other
  value and a conflict marker in the same teaching unit;
- Table 3 values must keep their development-set condition;
- a displayed formula must match a transcribed, reviewed formula after a
  documented LaTeX/Unicode normalisation (matching only, never semantics);
- a reviewed formula the course never shows is reported, not ignored.

The audit never edits content, never signs a review and never turns "no
finding" into "verified". Its report is bound to the SHA-256 of every file it
read, so editing the course invalidates the report instead of silently
inheriting an old pass.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import Field

from content_studio.errors import ValidationFailure
from content_studio.models import StrictModel
from content_studio.number_audit import extract_quantities, normalize_quantity
from content_studio.structured_review import (
    ReviewDocument,
    ReviewItem,
    default_review_path,
    load_review,
    validate_review_links,
)
from content_studio.utils import utc_now, write_json_atomic

AUDIT_SCHEMA_VERSION = "1.0"
AUDIT_RELATIVE_PATH = Path("internal") / "qa" / "course_content_audit.json"
CONTENT_FILES = (
    Path("content") / "public_content.json",
    Path("content") / "reading_edition.json",
)
BUILD_FILES = (
    Path("build") / "slides" / "index.html",
    Path("build") / "reading_edition.html",
)
# Only a decimal value near the word BLEU is treated as a reported BLEU score.
# "improves by 2 BLEU" (an integer delta) is not a result and is not audited.
# ``\b`` does not fire between a Latin letter and a CJK character (both are
# word characters), so the lookahead is spelled out.
_BLEU_BEFORE = re.compile(r"(\d+\.\d+)\s*(?:的\s*)?(?:BLEU|bleu)(?![A-Za-z])")
_BLEU_AFTER = re.compile(r"(?:BLEU|bleu)\s*(?:得分|分数|score)?\s*(?:为|of|=|:)?\s*(\d+\.\d+)")
_DECIMAL = re.compile(r"\d+\.\d+")
_SOURCE_ID = re.compile(r"source-\d{3,}")
_CONFLICT_MARKERS = ("冲突", "table 2", "表格 2", "表格2", "摘要", "abstract", "arxiv")
_DEV_MARKERS = ("dev", "newstest2013", "开发集", "验证集", "bleu (dev)", "bleu(dev)")
_TEST_MARKERS = ("测试集", "test set", "newstest2014", "测试数据")

Severity = Literal["blocker", "major", "advisory"]
Decision = Literal["blocked", "needs_correction", "passed", "not_run"]
CheckType = Literal[
    "bleu_value_supported",
    "source_conflict_disclosed",
    "bleu_metric_condition",
    "bleu_variant_qualifier",
    "citation_present",
    "formula_matches_review",
    "reviewed_formula_present",
    "evidence_item_source_available",
    "evidence_item_locator_present",
    "review_links_valid",
    "evidence_review_present",
    "course_content_readable",
    "number_coverage",
    "raw_latex_leak",
    "external_asset_dependency",
    "protected_condition_present",
]


class AuditFile(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AuditFinding(StrictModel):
    finding_id: str
    check_type: CheckType
    severity: Severity
    location: str
    expected: str
    actual: str
    evidence_refs: list[str] = Field(default_factory=list)
    status: Literal["needs_correction"] = "needs_correction"


class CourseAuditReport(StrictModel):
    schema_version: str = AUDIT_SCHEMA_VERSION
    audit_id: str
    project_id: str
    course_version: str
    generated_at: datetime
    files: list[AuditFile] = Field(default_factory=list)
    items_checked: int = 0
    findings: list[AuditFinding] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    decision: Decision = "not_run"
    notes: str = ""

    @property
    def blockers(self) -> list[AuditFinding]:
        return [finding for finding in self.findings if finding.severity == "blocker"]

    @property
    def majors(self) -> list[AuditFinding]:
        return [finding for finding in self.findings if finding.severity == "major"]


class _TextUnit(StrictModel):
    """One inspectable piece of course text, tied to its teaching unit."""

    path: str
    group: str
    location: str
    text: str
    source_ids: list[str] = Field(default_factory=list)
    kind: Literal["text", "formula"] = "text"


class _ReviewedFact(StrictModel):
    review_id: str
    kind: Literal["table", "formula"]
    source_id: str
    values: list[str] = Field(default_factory=list)
    variants: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    conflict: bool = False
    formula_forms: list[str] = Field(default_factory=list)


def finding_id(check_type: str, location: str, expected: str, actual: str) -> str:
    payload = f"{check_type}|{location}|{expected}|{actual}".encode()
    return "finding-" + hashlib.sha256(payload).hexdigest()[:12]


def _read_group(value: str, start: int) -> tuple[str | None, int]:
    while start < len(value) and value[start].isspace():
        start += 1
    if start >= len(value) or value[start] != "{":
        return None, start
    depth = 0
    for index in range(start, len(value)):
        if value[index] == "{":
            depth += 1
        elif value[index] == "}":
            depth -= 1
            if depth == 0:
                return value[start + 1 : index], index + 1
    return None, start


def _expand_fracs(value: str) -> str:
    """Rewrite ``\\frac{a}{b}`` as ``(a)/(b)`` with balanced-brace reading."""

    marker = "\\frac"
    while True:
        start = value.find(marker)
        if start < 0:
            return value
        numerator, after = _read_group(value, start + len(marker))
        if numerator is None:
            return value
        denominator, end = _read_group(value, after)
        if denominator is None:
            return value
        value = f"{value[:start]}({numerator})/({denominator}){value[end:]}"


def canonical_latex(text: str) -> str:
    """Canonical form for *comparison only* (``latex-tokens/v1``).

    This is not a math parser. It removes presentation choices that cannot
    change the formula (LaTeX commands, braces, parentheses, commas and
    whitespace), rewrites ``\\frac{a}{b}`` as ``a/b`` and ``√`` as ``sqrt``,
    then keeps the remaining token sequence. A different denominator or a
    dropped transpose changes the sequence; a re-typeset identical formula
    does not.
    """

    value = (text or "").strip().replace("$", "").replace("…", "...")
    value = _expand_fracs(value)
    value = value.replace("√", "sqrt")
    value = re.sub(
        r"\\(sqrt|text|mathrm|operatorname|left|right|displaystyle)\b",
        lambda match: "sqrt" if match.group(1) == "sqrt" else "",
        value,
    )
    value = re.sub(r"\\(cdot|times)\b", "*", value)
    value = value.replace("\\", "")
    value = value.replace("^{", "^").replace("_{", "_")
    for char in "{}()[],;":
        value = value.replace(char, "")
    value = re.sub(r"\s+", "", value)
    return value.lower()


def _merge_findings(findings: list[AuditFinding]) -> list[AuditFinding]:
    seen: set[str] = set()
    merged: list[AuditFinding] = []
    for finding in findings:
        if finding.finding_id in seen:
            continue
        seen.add(finding.finding_id)
        merged.append(finding)
    return merged


def _add(
    findings: list[AuditFinding],
    check_type: CheckType,
    severity: Severity,
    location: str,
    expected: str,
    actual: str,
    evidence_refs: list[str] | None = None,
) -> None:
    findings.append(
        AuditFinding(
            finding_id=finding_id(check_type, location, expected, actual),
            check_type=check_type,
            severity=severity,
            location=location,
            expected=expected,
            actual=actual,
            evidence_refs=evidence_refs or [],
        )
    )


def _fact_from_item(item: ReviewItem) -> _ReviewedFact:
    claim = item.claim
    values = sorted(set(_DECIMAL.findall(claim)))
    variants = [
        name for name in ("base", "big") if re.search(rf"\b{name}\b", claim, flags=re.IGNORECASE)
    ]
    conditions: list[str] = []
    lowered = claim.lower()
    for marker, label in (
        ("dev", "dev"),
        ("newstest2013", "dev"),
        ("开发集", "dev"),
        ("newstest2014", "test"),
        ("测试集", "test"),
        ("en-de", "en-de"),
        ("英德", "en-de"),
        ("en-fr", "en-fr"),
        ("英法", "en-fr"),
    ):
        if marker in lowered and label not in conditions:
            conditions.append(label)
    forms = [
        verification.transcribed_expression
        for verification in item.research_verification
        if verification.transcribed_expression.strip()
    ]
    if item.evidence_kind == "formula" and not forms:
        forms = [claim]
    return _ReviewedFact(
        review_id=item.review_id,
        kind=item.evidence_kind,
        source_id=item.source_id,
        values=values,
        variants=variants,
        conditions=conditions,
        conflict=item.conflict_status != "none",
        formula_forms=forms,
    )


def _block_texts(block: dict, base: str) -> list[tuple[str, str, str]]:
    """Flatten one content block into ``(kind, text, location)`` triples."""

    block_type = block.get("type", "")
    texts: list[tuple[str, str, str]] = []
    if block_type == "paragraph":
        texts.append(("text", str(block.get("text", "")), base))
    elif block_type == "bullets":
        for item_index, item in enumerate(block.get("items", [])):
            texts.append(("text", str(item), f"{base}.item[{item_index}]"))
    elif block_type == "formula":
        texts.append(("formula", str(block.get("latex", "")), base))
        if block.get("explanation"):
            texts.append(("text", str(block["explanation"]), f"{base}.explanation"))
    elif block_type == "callout":
        texts.append(("text", str(block.get("text", "")), base))
    elif block_type == "check":
        texts.append(("text", str(block.get("question", "")), f"{base}.question"))
        texts.append(("text", str(block.get("answer", "")), f"{base}.answer"))
        if block.get("rationale"):
            texts.append(("text", str(block["rationale"]), f"{base}.rationale"))
    elif block_type == "quote":
        texts.append(("text", str(block.get("text", "")), base))
    elif block_type in {"code", "figure"}:
        texts.append(("text", str(block.get("caption", "")), base))
    elif block_type == "svg":
        texts.append(("text", str(block.get("alt", "")), f"{base}.alt"))
        texts.append(("text", str(block.get("caption", "")), base))
    elif block_type == "interactive":
        texts.append(("text", str(block.get("title", "")), f"{base}.title"))
        texts.append(("text", str(block.get("description", "")), base))
        if block.get("caption"):
            texts.append(("text", str(block["caption"]), f"{base}.caption"))
    elif block_type == "table":
        for row_index, row in enumerate(block.get("rows", [])):
            texts.append(
                ("text", " | ".join(str(cell) for cell in row), f"{base}.row[{row_index}]")
            )
    return texts


def _content_units(project_dir: Path) -> list[_TextUnit]:
    units: list[_TextUnit] = []
    slide_sources: dict[str, list[str]] = {}
    public = project_dir / "content" / "public_content.json"
    if public.is_file():
        payload = json.loads(public.read_text(encoding="utf-8"))
        for slide in payload.get("slides", []):
            slide_id = str(slide.get("slide_id", "slide"))
            sources = [str(item) for item in slide.get("source_ids", [])]
            slide_sources[slide_id] = sources
            for index, block in enumerate(slide.get("body", [])):
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                base = f"content/public_content.json#{slide_id}:{block_type}[{index}]"
                texts: list[tuple[str, str, str]] = _block_texts(block, base)
                for kind, text, location in texts:
                    if not text.strip():
                        continue
                    units.append(
                        _TextUnit(
                            path="content/public_content.json",
                            group=slide_id,
                            location=location,
                            text=text,
                            source_ids=sources,
                            kind="formula" if kind == "formula" else "text",
                        )
                    )
    reading = project_dir / "content" / "reading_edition.json"
    if reading.is_file():
        payload = json.loads(reading.read_text(encoding="utf-8"))
        for section in payload.get("sections", []):
            slide_id = str(section.get("slide_id", "section"))
            sources = [str(item) for item in section.get("source_ids", [])]
            for index, paragraph in enumerate(section.get("paragraphs", [])):
                text = str(paragraph).strip()
                if not text:
                    continue
                units.append(
                    _TextUnit(
                        path="content/reading_edition.json",
                        group=slide_id,
                        location=f"content/reading_edition.json#{slide_id}:paragraph[{index}]",
                        text=text,
                        source_ids=sources,
                    )
                )
            for index, block in enumerate(section.get("body", [])):
                if not isinstance(block, dict):
                    continue
                base = f"content/reading_edition.json#{slide_id}:{block.get('type', '')}[{index}]"
                for kind, text, location in _block_texts(block, base):
                    if not text.strip():
                        continue
                    units.append(
                        _TextUnit(
                            path="content/reading_edition.json",
                            group=slide_id,
                            location=location,
                            text=text,
                            source_ids=sources,
                            kind="formula" if kind == "formula" else "text",
                        )
                    )
    script = project_dir / "internal" / "speaker_script.json"
    if script.is_file():
        payload = json.loads(script.read_text(encoding="utf-8"))
        for index, section in enumerate(payload.get("sections", [])):
            slide_id = str(section.get("slide_id", "section"))
            narration = str(section.get("narration", "")).strip()
            if not narration:
                continue
            units.append(
                _TextUnit(
                    path="internal/speaker_script.json",
                    group=slide_id,
                    location=f"internal/speaker_script.json#{slide_id}:narration[{index}]",
                    text=narration,
                    source_ids=slide_sources.get(slide_id, []),
                )
            )
    return units


def _html_units(path: Path, relative: str) -> list[_TextUnit]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    articles = soup.select("article, section.slide, section.reading-section") or [soup]
    units: list[_TextUnit] = []
    for article_index, article in enumerate(articles):
        group = str(article.get("id") or f"article-{article_index}")
        article_text = article.get_text(" ", strip=True)
        sources = sorted(set(_SOURCE_ID.findall(article_text)))
        counters: dict[str, int] = {}
        for element in article.find_all(["p", "li", "td", "figcaption", "div"]):
            classes = list(element.get("class") or [])
            if element.name == "div" and not ({"formula", "callout"} & set(classes)):
                continue
            if element.name == "div" and element.find(["p", "li", "td"]):
                continue
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            is_formula = "formula" in classes
            if is_formula:
                # The visible text is typeset HTML; the audit compares the
                # LaTeX that produced it, which the build records as data.
                text = str(element.get("data-latex") or text)
            key = element.name
            counters[key] = counters.get(key, 0) + 1
            units.append(
                _TextUnit(
                    path=relative,
                    group=group,
                    location=f"{relative}#{group}:{key}[{counters[key]}]",
                    text=text,
                    source_ids=sources,
                    kind="formula" if "formula" in classes else "text",
                )
            )
    return units


def _bleu_values(text: str) -> list[str]:
    values = [match.group(1) for match in _BLEU_BEFORE.finditer(text)]
    values += [match.group(1) for match in _BLEU_AFTER.finditer(text)]
    return sorted(set(values))


def _group_text(units: list[_TextUnit]) -> dict[tuple[str, str], str]:
    groups: dict[tuple[str, str], str] = {}
    for unit in units:
        key = (unit.path, unit.group)
        groups[key] = f"{groups.get(key, '')} {unit.text}".strip()
    return groups


def _source_available(project_dir: Path, source_id: str) -> bool:
    path = project_dir / "internal" / "sources" / f"{source_id}.txt"
    return path.is_file() and bool(path.read_text(encoding="utf-8", errors="replace").strip())


def _course_files(project_dir: Path, extra: list[Path]) -> list[Path]:
    files = [project_dir / name for name in (*CONTENT_FILES, *BUILD_FILES)]
    files.extend(extra)
    return [path for path in files if path.is_file()]


def _relative(project_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _loaded_review(project_dir: Path, review_path: Path | None) -> ReviewDocument | None:
    path = review_path or default_review_path(project_dir)
    if not path.is_file():
        return None
    return load_review(path)


def _audit_numbers(
    units: list[_TextUnit],
    facts: list[_ReviewedFact],
    findings: list[AuditFinding],
) -> int:
    supported: dict[str, list[_ReviewedFact]] = {}
    for fact in facts:
        for value in fact.values:
            supported.setdefault(value, []).append(fact)
    groups = _group_text(units)
    checked = 0
    conflicts: set[str] = set()
    table3_values: dict[str, _ReviewedFact] = {}
    for fact in facts:
        if fact.conflict:
            conflicts.update(fact.values)
        if "dev" in fact.conditions:
            for value in fact.values:
                table3_values[value] = fact
    for unit in units:
        if unit.kind != "text":
            continue
        for value in _bleu_values(unit.text):
            checked += 1
            owners = supported.get(value, [])
            if not owners:
                _add(
                    findings,
                    "bleu_value_supported",
                    "blocker",
                    unit.location,
                    "BLEU 数值必须来自已复核证据（27.3 / 28.4 / 41.0 / 41.8 / 26.4 / 25.8）",
                    f"课程写了 {value} BLEU，但没有复核记录支持该数值",
                )
                continue
            fact = owners[0]
            if value in conflicts:
                scope = groups.get((unit.path, unit.group), unit.text)
                lowered = scope.lower()
                others = sorted(set(conflicts) - {value})
                missing = [other for other in others if other not in scope]
                marker = any(marker in lowered for marker in _CONFLICT_MARKERS)
                if missing or not marker:
                    _add(
                        findings,
                        "source_conflict_disclosed",
                        "blocker",
                        unit.location,
                        "同一教学单元内同时披露 41.0（Table 2/§6.1）与 41.8（摘要）并说明来源冲突",
                        f"只出现 {value} BLEU；缺少 {'/'.join(missing) or '冲突说明'}",
                        [fact.review_id],
                    )
            if value in table3_values:
                scope = groups.get((unit.path, unit.group), unit.text)
                lowered = scope.lower()
                has_dev = any(marker in lowered for marker in _DEV_MARKERS)
                has_test = any(marker in lowered for marker in _TEST_MARKERS)
                if has_test and not has_dev:
                    _add(
                        findings,
                        "bleu_metric_condition",
                        "blocker",
                        unit.location,
                        "Table 3 的 26.4/25.8 是 EN-DE 开发集（newstest2013）的 BLEU (dev)",
                        f"{value} 被放在测试集语境中，且未标注 dev/newstest2013",
                        [table3_values[value].review_id],
                    )
                elif not has_dev:
                    _add(
                        findings,
                        "bleu_metric_condition",
                        "major",
                        unit.location,
                        "标注 BLEU (dev)、newstest2013、EN-DE",
                        f"{value} 缺少开发集与语言对限定",
                        [table3_values[value].review_id],
                    )
            variant = fact.variants[0] if fact.variants else ""
            qualifier = "大模型" if variant == "big" else "基础模型"
            if variant and not re.search(
                rf"\b{variant}\b|\({variant}\)|{qualifier}",
                unit.text,
                flags=re.IGNORECASE,
            ):
                _add(
                    findings,
                    "bleu_variant_qualifier",
                    "advisory",
                    unit.location,
                    f"标注该结果属于 Transformer ({variant})",
                    f"{value} BLEU 未标明 {variant} 模型",
                    [fact.review_id],
                )
            if not unit.source_ids or fact.source_id not in unit.source_ids:
                _add(
                    findings,
                    "citation_present",
                    "blocker",
                    unit.location,
                    f"该段引用 {fact.source_id}",
                    f"来源引用为 {unit.source_ids or '空'}",
                    [fact.review_id],
                )
    return checked


def _audit_formulas(
    units: list[_TextUnit],
    facts: list[_ReviewedFact],
    findings: list[AuditFinding],
    *,
    review_present: bool,
) -> int:
    reviewed: dict[str, _ReviewedFact] = {}
    for fact in facts:
        if fact.kind != "formula":
            continue
        for form in fact.formula_forms:
            canonical = canonical_latex(form)
            if canonical:
                reviewed[canonical] = fact
    formula_units = [unit for unit in units if unit.kind == "formula"]
    checked = 0
    for unit in formula_units:
        checked += 1
        canonical = canonical_latex(unit.text)
        if canonical in reviewed:
            fact = reviewed[canonical]
            if not unit.source_ids or fact.source_id not in unit.source_ids:
                _add(
                    findings,
                    "citation_present",
                    "blocker",
                    unit.location,
                    f"公式所在单元引用 {fact.source_id}",
                    f"来源引用为 {unit.source_ids or '空'}",
                    [fact.review_id],
                )
            continue
        if not review_present:
            _add(
                findings,
                "evidence_review_present",
                "blocker",
                unit.location,
                "课程公式需要有已复核的结构化证据",
                "课程展示了公式，但没有结构化证据复核记录",
            )
            continue
        expected = "；".join(sorted(reviewed)[:3]) or "（没有已复核公式）"
        _add(
            findings,
            "formula_matches_review",
            "blocker",
            unit.location,
            f"与已复核公式一致（规范化后：{expected}）",
            f"规范化后为：{canonical}",
            [fact.review_id for fact in reviewed.values()],
        )
    used = {canonical_latex(unit.text) for unit in formula_units}
    for canonical, fact in reviewed.items():
        if canonical not in used:
            _add(
                findings,
                "reviewed_formula_present",
                "major",
                f"review:{fact.review_id}",
                "课程展示并解释已复核公式",
                "当前课程内容没有展示该公式",
                [fact.review_id],
            )
    return checked


def _load_json(path: Path) -> object | None:
    if not path.is_file():
        return None
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload


def _quantities_in(text: str) -> set[str]:
    return {quantity.value for quantity in extract_quantities(text) if quantity.value}


def _claim_quantities(project_dir: Path) -> dict[str, set[str]]:
    """Numbers stated by recorded claims (and by reviewed evidence items)."""

    numbers: dict[str, set[str]] = {}
    claims = _load_json(project_dir / "internal" / "claims.json")
    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            claim_id = str(claim.get("claim_id") or "")
            if claim_id:
                numbers.setdefault(claim_id, set()).update(
                    _quantities_in(str(claim.get("statement") or ""))
                )
    review = _load_json(project_dir / "internal" / "qa" / "structured_evidence_review.json")
    if isinstance(review, dict):
        for item in review.get("items", []):
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get("claim_id") or "")
            if claim_id:
                numbers.setdefault(claim_id, set()).update(
                    _quantities_in(str(item.get("claim") or ""))
                )
    return numbers


def _ledger_rows(project_dir: Path) -> dict[str, dict[str, str]]:
    path = project_dir / "internal" / "evidence_ledger.csv"
    if not path.is_file():
        return {}
    rows: dict[str, dict[str, str]] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                evidence_id = (row.get("evidence_id") or "").strip()
                if evidence_id:
                    rows[evidence_id] = {key: value or "" for key, value in row.items()}
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return rows


def _number_whitelist(project_dir: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Structural constants that are not evidence claims.

    Entries must state why; a whitelist entry without a reason is ignored, so
    a silent exception cannot become policy.
    """

    payload = _load_json(project_dir / "internal" / "plan" / "number_whitelist.json")
    global_values: set[str] = set()
    per_slide: dict[str, set[str]] = {}
    if not isinstance(payload, dict):
        return global_values, per_slide
    for entry in payload.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("reason") or "").strip():
            continue
        value = normalize_quantity(str(entry.get("value") or ""))
        if not value:
            continue
        slides = [str(item) for item in entry.get("slides", [])]
        if not slides:
            global_values.add(value)
        for slide in slides:
            per_slide.setdefault(slide, set()).add(value)
    return global_values, per_slide


def _allowed_numbers(project_dir: Path) -> tuple[dict[str, set[str]], set[str]]:
    """Map each slide to the numbers its registered evidence can support."""

    claims = _claim_quantities(project_dir)
    ledger = _ledger_rows(project_dir)
    whitelist_global, whitelist_slides = _number_whitelist(project_dir)

    evidence_numbers: dict[str, set[str]] = {}
    for evidence_id, row in ledger.items():
        values = set(claims.get((row.get("claim_id") or "").strip(), set()))
        values.update(_quantities_in(row.get("source_excerpt") or ""))
        evidence_numbers[evidence_id] = values

    global_allowed = set(whitelist_global)
    for values in claims.values():
        global_allowed.update(values)
    for values in evidence_numbers.values():
        global_allowed.update(values)

    per_slide: dict[str, set[str]] = {}
    outline = _load_json(project_dir / "content" / "outline.json")
    if isinstance(outline, dict):
        for section in outline.get("sections", []):
            if not isinstance(section, dict):
                continue
            slide_id = str(section.get("slide_id") or "")
            if not slide_id:
                continue
            allowed = set(whitelist_slides.get(slide_id, set()))
            for evidence_id in section.get("evidence_ids", []):
                allowed.update(evidence_numbers.get(str(evidence_id), set()))
            per_slide[slide_id] = allowed
    return per_slide, global_allowed


def _audit_number_coverage(
    units: list[_TextUnit], project_dir: Path, findings: list[AuditFinding]
) -> int:
    """Every quantity the course states must be registered or whitelisted.

    This is the check that would have caught the P6 narration drift
    (``beta2 = 0.98``, ``eps = 1e-9``, ``warmup 4000``) before a reviewer had
    to find it by reading. It is a coverage check, not a correctness proof:
    registration means "the ledger records this number", not "the number is
    right".
    """

    per_slide, global_allowed = _allowed_numbers(project_dir)
    missing: dict[str, dict[str, str]] = {}
    checked = 0
    for unit in units:
        allowed = per_slide.get(unit.group, global_allowed)
        for quantity in extract_quantities(unit.text):
            if not quantity.value:
                continue
            # Sub/superscript indices such as \sum_{i=1} are structural, not
            # claims. Formula units still audit decimals and scientific
            # notation (the constants that carry meaning).
            if unit.kind == "formula" and quantity.raw.isdigit():
                continue
            checked += 1
            if quantity.value in allowed:
                continue
            bucket = missing.setdefault(unit.group or "project", {})
            bucket.setdefault(quantity.value, unit.location)
    for group, values in sorted(missing.items()):
        sample = "、".join(sorted(values)[:8])
        first = next(iter(values.values()))
        _add(
            findings,
            "number_coverage",
            "major",
            first,
            "每个定量数字都能追溯到该节绑定的 claims/evidence，"
            "或在 number_whitelist.json 中说明理由",
            f"{group} 出现未登记数字：{sample}"
            + ("…" if len(values) > 8 else "")
            + "（可能是口播或正文写入了台账之外的数值）",
        )
    return checked


_EXTERNAL_ASSET = re.compile(r"^(?:https?:)?//", re.IGNORECASE)


def _audit_guards(project_dir: Path, units: list[_TextUnit], findings: list[AuditFinding]) -> int:
    """Check the reviewed conditions a course has locked as protected.

    A phrase lock is not semantic understanding: it can only notice that a
    condition the reviewer marked as required disappeared from the course.
    That is exactly the tamper it targets (removing "when n < d", replacing
    "the authors hypothesise" with "it proves", or flipping Post-LN wording).
    Each guard must state why it is protected.
    """

    payload = _load_json(project_dir / "internal" / "plan" / "course_guards.json")
    if not isinstance(payload, dict):
        return 0
    by_group: dict[str, str] = {}
    locations: dict[str, str] = {}
    for unit in units:
        by_group[unit.group] = f"{by_group.get(unit.group, '')} {unit.text}".strip()
        locations.setdefault(unit.group, unit.location)
    checked = 0
    for guard in payload.get("guards", []):
        if not isinstance(guard, dict):
            continue
        required = [str(item) for item in guard.get("required", []) if str(item).strip()]
        if not required or not str(guard.get("reason") or "").strip():
            continue
        slide_id = str(guard.get("slide_id") or "")
        guard_id = str(guard.get("guard_id") or "guard")
        text = by_group.get(slide_id, "").lower()
        checked += 1
        missing = [item for item in required if item.lower() not in text]
        if missing:
            _add(
                findings,
                "protected_condition_present",
                "blocker",
                locations.get(slide_id, f"guard:{guard_id}"),
                "受保护条件必须原样保留：" + "、".join(required),
                f"{guard_id}: 缺少 {'、'.join(missing)}（条件被删除或改写）",
            )
    return checked


def _audit_build_rendering(
    project_dir: Path, files: list[Path], findings: list[AuditFinding]
) -> int:
    """The build must be offline-safe and must not show raw LaTeX."""

    checked = 0
    for path in files:
        if path.suffix.lower() not in {".html", ".htm"}:
            continue
        checked += 1
        relative = _relative(project_dir, path)
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for tag in soup(["script", "style", "pre", "code"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        leaks = sorted({match.group(0) for match in _LATEX_COMMAND.finditer(text)})
        if leaks:
            _add(
                findings,
                "raw_latex_leak",
                "blocker",
                relative,
                "公式在构建时已排版；页面可见文本不得出现 LaTeX 命令",
                "发现未渲染的 LaTeX：" + " ".join(leaks[:6]),
            )
        external: list[str] = []
        for tag in BeautifulSoup(
            path.read_text(encoding="utf-8", errors="replace"), "html.parser"
        ).find_all(["script", "link", "img", "video", "source"]):
            reference = str(tag.get("src") or tag.get("href") or "")
            if reference and _EXTERNAL_ASSET.match(reference):
                external.append(reference[:120])
        if external:
            _add(
                findings,
                "external_asset_dependency",
                "blocker",
                relative,
                "课件离线可用：不引用外部脚本、样式或媒体",
                "发现外部资源：" + "、".join(sorted(set(external))[:4]),
            )
    return checked


_LATEX_COMMAND = re.compile(r"\\[A-Za-z]{2,}")


def run_course_audit(
    project_dir: Path,
    *,
    review_path: Path | None = None,
    extra_paths: list[Path] | None = None,
) -> CourseAuditReport:
    """Audit one course version and return its report (writing it is the caller's job)."""

    project_dir = project_dir.resolve()
    files = _course_files(project_dir, list(extra_paths or []))
    if not files:
        return CourseAuditReport(
            audit_id="course-audit-not-run",
            project_id=project_dir.name,
            course_version="",
            generated_at=utc_now(),
            decision="not_run",
            notes="没有可审计的课程内容文件",
        )

    findings: list[AuditFinding] = []
    review = _loaded_review(project_dir, review_path)
    facts: list[_ReviewedFact] = []
    if review is not None:
        try:
            validate_review_links(project_dir, review)
        except ValidationFailure as exc:
            _add(
                findings,
                "review_links_valid",
                "blocker",
                _relative(project_dir, review_path or default_review_path(project_dir)),
                "复核记录引用真实的来源、区块、主张和论文要素",
                str(exc),
            )
        for item in review.items:
            facts.append(_fact_from_item(item))
            if not item.locator.strip():
                _add(
                    findings,
                    "evidence_item_locator_present",
                    "blocker",
                    f"review:{item.review_id}",
                    "复核记录带章节/表格/公式定位",
                    "locator 为空，数值无法追溯到原文位置",
                    [item.review_id],
                )
            if not _source_available(project_dir, item.source_id):
                _add(
                    findings,
                    "evidence_item_source_available",
                    "major",
                    f"review:{item.review_id}",
                    f"{item.source_id} 的来源文本可读取",
                    "来源文本缺失，无法核对；未发现问题不等于验证正确",
                    [item.review_id],
                )

    units: list[_TextUnit] = []
    for path in files:
        if path.suffix.lower() in {".html", ".htm"}:
            try:
                units.extend(_html_units(path, _relative(project_dir, path)))
            except (OSError, UnicodeDecodeError) as exc:
                _add(
                    findings,
                    "course_content_readable",
                    "blocker",
                    _relative(project_dir, path),
                    "课程文件可读取且为 UTF-8",
                    f"无法读取：{exc}",
                )
    try:
        units.extend(_content_units(project_dir))
    except (OSError, ValueError, TypeError) as exc:
        _add(
            findings,
            "course_content_readable",
            "blocker",
            "content/public_content.json",
            "课程内容 JSON 可解析",
            f"无法解析：{exc}",
        )

    items_checked = len(facts)
    checked_numbers = _audit_numbers(units, facts, findings)
    checked_formulas = _audit_formulas(units, facts, findings, review_present=review is not None)
    checked_quantities = _audit_number_coverage(units, project_dir, findings)
    checked_builds = _audit_build_rendering(project_dir, files, findings)
    checked_guards = _audit_guards(project_dir, units, findings)

    findings = _merge_findings(findings)
    summary = {
        "blocker": sum(1 for finding in findings if finding.severity == "blocker"),
        "major": sum(1 for finding in findings if finding.severity == "major"),
        "advisory": sum(1 for finding in findings if finding.severity == "advisory"),
    }
    if summary["blocker"]:
        decision: Decision = "blocked"
    elif summary["major"]:
        decision = "needs_correction"
    else:
        decision = "passed"

    audit_files = [
        AuditFile(path=_relative(project_dir, path), sha256=_sha256(path)) for path in files
    ]
    course_version = _course_version(audit_files)
    audit_id = (
        "course-audit-"
        + hashlib.sha256(f"{project_dir.name}|{course_version}".encode()).hexdigest()[:12]
    )
    notes = (
        f"检查 {len(units)} 个文本/公式单元、{checked_numbers} 处 BLEU 数值、"
        f"{checked_formulas} 个公式、{items_checked} 条复核记录、"
        f"{checked_quantities} 个定量数字、{checked_builds} 个构建页面、"
        f"{checked_guards} 条受保护条件。"
        "审计只证明列出的检查项；未列出的语义问题仍需人工判断。"
    )
    return CourseAuditReport(
        audit_id=audit_id,
        project_id=review.project_id if review is not None else project_dir.name,
        course_version=course_version,
        generated_at=utc_now(),
        files=audit_files,
        items_checked=items_checked,
        findings=findings,
        summary=summary,
        decision=decision,
        notes=notes,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _course_version(files: list[AuditFile]) -> str:
    payload = "\n".join(
        f"{item.path}:{item.sha256}" for item in sorted(files, key=lambda item: item.path)
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def audit_path(project_dir: Path) -> Path:
    return project_dir / AUDIT_RELATIVE_PATH


def write_audit(project_dir: Path, report: CourseAuditReport, *, path: Path | None = None) -> Path:
    destination = path or audit_path(project_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(destination, report)
    return destination


def load_audit(project_dir: Path, *, path: Path | None = None) -> CourseAuditReport | None:
    source = path or audit_path(project_dir)
    if not source.is_file():
        return None
    return CourseAuditReport.model_validate_json(source.read_text(encoding="utf-8"))


def audit_is_current(project_dir: Path, report: CourseAuditReport) -> list[str]:
    """Return the project-relative files whose hash no longer matches the report."""

    stale: list[str] = []
    for item in report.files:
        candidate = project_dir / item.path
        if not candidate.is_file():
            stale.append(item.path)
            continue
        if _sha256(candidate) != item.sha256:
            stale.append(item.path)
    return stale


__all__ = [
    "AUDIT_RELATIVE_PATH",
    "AuditFinding",
    "CourseAuditReport",
    "audit_is_current",
    "audit_path",
    "canonical_latex",
    "finding_id",
    "load_audit",
    "run_course_audit",
    "write_audit",
]
