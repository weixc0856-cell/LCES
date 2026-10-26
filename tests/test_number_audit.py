from __future__ import annotations

from content_studio.number_audit import extract_quantities, normalize_quantity


def _values(text: str) -> list[str]:
    return [item.value for item in extract_quantities(text)]


def test_decimals_are_always_audited():
    assert _values("27.3 BLEU") == ["27.3"]
    assert _values("beta2 等于 0.98") == ["0.98"]


def test_scientific_notation_normalises_to_one_value():
    assert _values("1e-9") == ["1e-09"]
    assert _values("10^{-9}") == ["1e-09"]
    assert _values("3.3×10^18") == ["3.3e+18"]
    assert _values("7.7 · 10^19") == ["7.7e+19"]


def test_units_and_equalities_mark_integers():
    assert "6" in _values("N=6 层")
    assert "4000" in _values("warmup 4000 步")
    assert "8" in _values("8 块 P100")


def test_plain_counts_and_references_are_not_quantities():
    assert _values("第 3 节") == []
    assert _values("Table 2 与 Figure 1") == []
    assert _values("WMT 2014 newstest2014") == []
    assert _values("arXiv:1706.03762v7") == []


def test_integer_inside_identifier_is_ignored():
    assert _values("P100 GPU") == []
    assert _values("32K vocabulary") == []


def test_normalize_quantity_handles_unicode_minus_and_braces():
    assert normalize_quantity("10^{−9}") == "1e-09"
    assert normalize_quantity("41.0") == "41"
    assert normalize_quantity("0.0") == "0"
