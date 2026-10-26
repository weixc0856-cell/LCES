"""Quantitative-token extraction for the course number-coverage audit.

The audit exists because a deterministic checker that only looks for a fixed
list of BLEU values misses exactly the drift humans care about: a narration
that says ``beta2 = 0.98`` while the evidence ledger never recorded it.

Extraction is deliberately conservative. Only tokens that read as a quantity
are returned:

- decimals (``27.3``), scientific notation (``1e-9``, ``3.3·10^18``, ``10^19``)
- integers that sit next to a comparison/equality operator or a unit word
  (``N=6``、``h=8``、``warmup 4000 步``、``8 块 P100``)

Ordinals, table/figure references, years embedded in names
(``newstest2013``) and digits inside identifiers (``arXiv:1706.03762v7``) are
not quantities and are not returned. Chinese numerals are not audited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Quantity", "extract_quantities", "normalize_quantity"]

_MINUS = "−–"
_SCI = re.compile(
    r"(?P<coef>\d+(?:\.\d+)?)\s*[·×xX*]\s*10\s*\^?\s*\{?\s*(?P<exp>[-" + _MINUS + r"+]?\d+)\s*\}?"
)
_POW10 = re.compile(r"(?<![\d.])10\s*\^\s*\{?\s*(?P<exp>[-" + _MINUS + r"+]?\d+)\s*\}?")
_E_NOTATION = re.compile(
    r"(?<![\w.])(?P<coef>\d+(?:\.\d+)?)\s*[eE]\s*(?P<exp>[-+" + _MINUS + r"]?\d+)(?![\w])"
)
_DECIMAL = re.compile(r"(?<![\w.])(?P<num>\d+\.\d+)(?![\w])")
_INTEGER = re.compile(r"(?<![\w.−-])(?P<num>\d+)(?![\w.])")

_UNIT_WORDS = (
    "层",
    "头",
    "维",
    "步",
    "块",
    "天",
    "分钟",
    "秒",
    "个",
    "条",
    "句",
    "例",
    "题",
    "倍",
    "次",
    "轮",
    "token",
    "tokens",
    "bleu",
    "f1",
    "flops",
    "tflops",
    "gpu",
    "gpus",
    "checkpoint",
    "checkpoints",
    "layer",
    "layers",
    "head",
    "heads",
    "dim",
    "dimension",
    "step",
    "steps",
    "warmup",
    "sample",
    "samples",
    "batch",
    "epoch",
    "epochs",
    "sentence",
    "sentences",
)
_CUE_BEFORE = ("=", "=", "×", "x", "*", "/", "%", "·")
_REFERENCE_BEFORE = (
    "第",
    "表",
    "表格",
    "table",
    "图",
    "figure",
    "fig",
    "§",
    "eq",
    "式",
    "公式",
    "section",
    "节",
    "附录",
    "appendix",
)


@dataclass(frozen=True)
class Quantity:
    raw: str
    value: str
    start: int
    end: int


def _normalize(value: float) -> str:
    if value != value or value in (float("inf"), float("-inf")):
        return ""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.12g}"


def normalize_quantity(raw: str) -> str:
    """Return the canonical form used on both sides of the comparison."""

    text = raw.replace("−", "-").replace("–", "-").strip()
    text = text.replace("{", "").replace("}", "").replace(" ", "")
    power = re.fullmatch(r"(?P<coef>\d+(?:\.\d+)?)\s*[·×xX*]\s*10\^(?P<exp>[-+]?\d+)", text)
    if power is None:
        power = re.fullmatch(r"10\^(?P<exp>[-+]?\d+)", text)
        coefficient = "1"
    else:
        coefficient = power.group("coef")
    if power is not None:
        try:
            return _normalize(float(coefficient) * (10 ** int(power.group("exp"))))
        except (TypeError, ValueError, OverflowError):
            return ""
    try:
        return _normalize(float(text))
    except ValueError:
        return ""


def _sort_key(item: Quantity) -> tuple[int, int]:
    return (item.start, item.end)


def _window(text: str, start: int, end: int, width: int = 6) -> tuple[str, str]:
    before = text[max(0, start - width) : start].lower()
    after = text[end : end + width].lower()
    return before, after


def _is_reference(before: str) -> bool:
    stripped = before.rstrip(" \t　:：")
    return any(stripped.endswith(marker) for marker in _REFERENCE_BEFORE)


def _has_quantity_cue(before: str, after: str) -> bool:
    if any(cue in before[-3:] for cue in _CUE_BEFORE):
        return True
    if any(cue in after[:4] for cue in _CUE_BEFORE):
        return True
    haystack = before + "|" + after
    return any(word in haystack for word in _UNIT_WORDS)


def extract_quantities(text: str) -> list[Quantity]:
    """Return the quantity tokens in *text*, in reading order."""

    if not text:
        return []
    found: list[Quantity] = []
    consumed: list[tuple[int, int]] = []

    def consume(start: int, end: int) -> bool:
        return any(start < stop and end > begin for begin, stop in consumed)

    for pattern in (_SCI, _E_NOTATION, _POW10):
        for match in pattern.finditer(text):
            if consume(match.start(), match.end()):
                continue
            exponent = match.group("exp")
            coefficient = match.groupdict().get("coef") or "1"
            try:
                value = float(coefficient) * (10 ** int(exponent.replace("−", "-")))
            except (TypeError, ValueError, OverflowError):
                continue
            normalized = _normalize(value)
            if not normalized:
                continue
            found.append(Quantity(match.group(0), normalized, match.start(), match.end()))
            consumed.append((match.start(), match.end()))

    for match in _DECIMAL.finditer(text):
        if consume(match.start(), match.end()):
            continue
        normalized = normalize_quantity(match.group("num"))
        if not normalized:
            continue
        before, after = _window(text, match.start(), match.end())
        if _is_reference(before):
            continue
        found.append(Quantity(match.group("num"), normalized, match.start(), match.end()))
        consumed.append((match.start(), match.end()))

    for match in _INTEGER.finditer(text):
        if consume(match.start(), match.end()):
            continue
        before, after = _window(text, match.start(), match.end())
        if _is_reference(before):
            continue
        if not _has_quantity_cue(before, after):
            continue
        found.append(
            Quantity(
                match.group("num"),
                normalize_quantity(match.group("num")),
                match.start(),
                match.end(),
            )
        )
        consumed.append((match.start(), match.end()))

    return sorted(found, key=_sort_key)
