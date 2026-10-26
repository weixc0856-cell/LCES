from __future__ import annotations

import pytest

from content_studio.latex_render import LatexRenderError, render_latex, supported_commands


def test_attention_formula_renders_without_raw_latex():
    html = render_latex(
        r"\mathrm{Attention}(Q,K,V)=\mathrm{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V"
    )
    assert "\\" not in html
    assert "m-frac" in html
    assert "m-radical" in html
    assert "Attention" in html


def test_sub_and_superscript_use_semantic_tags():
    html = render_latex(r"d_{\mathrm{model}}^{-0.5}")
    assert "<sub" in html
    assert "<sup" in html
    assert "0" in html


def test_text_commands_unescape_literal_underscores():
    html = render_latex(r"\mathrm{step\_num}")
    assert "step_num" in html
    assert "\\" not in html


def test_unsupported_command_fails_loudly():
    with pytest.raises(LatexRenderError, match="unsupported LaTeX command"):
        render_latex(r"\begin{aligned} a \end{aligned}")


def test_empty_formula_is_rejected():
    with pytest.raises(LatexRenderError):
        render_latex("   ")


def test_second_script_on_one_base_is_allowed():
    html = render_latex(r"x_i^2")
    assert "<sub" in html
    assert "<sup" in html


def test_supported_commands_cover_the_course_subset():
    commands = supported_commands()
    for name in ("frac", "sqrt", "mathrm", "softmax", "cdot", "min", "max"):
        assert name in commands
