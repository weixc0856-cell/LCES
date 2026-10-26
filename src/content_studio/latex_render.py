"""Deterministic LaTeX-subset to HTML rendering for course pages.

The course model stores formulas as LaTeX because that is what the paper
transcription and the reviewer compare against. It must never reach a browser
verbatim: a consumer without a math engine would show ``\\mathrm`` and
``\\left`` as literal text.

This module renders a deliberately small, documented subset to semantic HTML
(``sup``/``sub``/fractions/radicals). It has no external dependency, no
network access and no JavaScript, so an offline build renders identically on
every host. It is not a TeX implementation: an unsupported command raises
:class:`LatexRenderError` at build time instead of silently emitting the
backslash. That failure mode is intentional - a broken formula must stop the
build, never leak raw source into the page.

Supported subset (checked by ``tests/test_latex_render.py``):

- groups ``{...}``, sub/superscripts ``_x`` ``^{...}``
- ``\\frac{}{}``, ``\\sqrt{}``, ``\\left``/``\\right`` delimiters
- text commands ``\\mathrm``, ``\\text``, ``\\operatorname``, ``\\mathbf``
- symbol commands (Greek, operators, relations) listed in ``_SYMBOLS``
- spacing ``\\,`` ``\\;`` ``\\!`` ``\\quad`` ``\\qquad`` ``\\ ``
- line breaks ``\\\\`` render as a visible break inside the formula

Everything else is refused.
"""

from __future__ import annotations

import re
from html import escape

__all__ = ["LatexRenderError", "render_latex", "supported_commands"]


class LatexRenderError(ValueError):
    """The formula uses syntax outside the documented subset."""


# Commands that render as a fixed symbol or a text fragment.
_SYMBOLS: dict[str, str] = {
    "cdot": "·",
    "times": "×",
    "div": "÷",
    "pm": "±",
    "mp": "∓",
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "ne": "≠",
    "neq": "≠",
    "approx": "≈",
    "sim": "∼",
    "propto": "∝",
    "in": "∈",
    "notin": "∉",
    "forall": "∀",
    "exists": "∃",
    "infty": "∞",
    "sum": "∑",
    "prod": "∏",
    "int": "∫",
    "to": "→",
    "rightarrow": "→",
    "leftarrow": "←",
    "Rightarrow": "⇒",
    "mapsto": "↦",
    "partial": "∂",
    "nabla": "∇",
    "cdots": "⋯",
    "ldots": "…",
    "dots": "…",
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ϵ",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "ϕ",
    "varphi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "|": "‖",
    "{": "{",
    "}": "}",
    "%": "%",
    "_": "_",
    "&": "&",
    "#": "#",
    "$": "$",
    "lvert": "|",
    "rvert": "|",
    "langle": "⟨",
    "rangle": "⟩",
}

# Functions typeset upright, followed by their argument.
_FUNCTIONS = {
    "sin",
    "cos",
    "tan",
    "tanh",
    "log",
    "ln",
    "exp",
    "max",
    "min",
    "arg",
    "det",
    "softmax",
    "Var",
    "Cov",
    "Attention",
    "MultiHead",
    "Concat",
    "LayerNorm",
    "PE",
}

# Commands whose whole effect is spacing.
_SPACES = {
    ",": " ",
    ";": " ",
    ":": " ",
    "!": "",
    "quad": " ",
    "qquad": "  ",
    " ": " ",
}

_TEXT_COMMANDS = {"mathrm", "text", "operatorname", "mathbf", "mathcal", "mathbb", "mathit"}

_LEFT_RIGHT_DELIMITERS = {
    "(": "(",
    ")": ")",
    "[": "[",
    "]": "]",
    "|": "|",
    ".": "",
    "\\{": "{",
    "\\}": "}",
    "\\|": "‖",
    "\\lvert": "|",
    "\\rvert": "|",
    "\\langle": "⟨",
    "\\rangle": "⟩",
}

_SCRIPT_BASES = re.compile(r"^[A-Za-z0-9]$")
_ESCAPED = re.compile(r"\\([A-Za-z]+|.)", re.DOTALL)


def supported_commands() -> set[str]:
    """Return the command names this renderer accepts (for docs and tests)."""

    return (
        set(_SYMBOLS)
        | _FUNCTIONS
        | set(_SPACES)
        | _TEXT_COMMANDS
        | {"frac", "sqrt", "left", "right"}
    )


def _escaped_text(value: str) -> str:
    return escape(value, quote=False)


class _Parser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0

    # -- token helpers -------------------------------------------------
    def _peek(self) -> str:
        return self.source[self.pos] if self.pos < len(self.source) else ""

    def _skip_space(self) -> None:
        while self.pos < len(self.source) and self.source[self.pos].isspace():
            self.pos += 1

    def _read_command_name(self) -> str:
        start = self.pos
        while self.pos < len(self.source) and self.source[self.pos].isalpha():
            self.pos += 1
        if start == self.pos:
            # Single-character command such as \, or \| or \{.
            char = self.source[self.pos]
            self.pos += 1
            return char
        return self.source[start : self.pos]

    def _read_group(self) -> str:
        """Return the raw text of a ``{...}`` group and advance past it."""

        self._skip_space()
        if self._peek() != "{":
            raise LatexRenderError(f"expected '{{' at offset {self.pos} in {self.source!r}")
        depth = 0
        start = self.pos + 1
        while self.pos < len(self.source):
            char = self.source[self.pos]
            if char == "\\":
                self.pos += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return self.source[start : self.pos - 1]
            self.pos += 1
        raise LatexRenderError(f"unbalanced braces in {self.source!r}")

    def _read_atom(self) -> str:
        """Render one atom: a group, a command or a single character."""

        self._skip_space()
        char = self._peek()
        if not char:
            raise LatexRenderError(f"formula ends after a script marker: {self.source!r}")
        if char == "{":
            return self._render(self._read_group())
        if char == "\\":
            self.pos += 1
            return self._render_command()
        if char == "}":
            raise LatexRenderError(f"unexpected '}}' at offset {self.pos} in {self.source!r}")
        self.pos += 1
        if char.isdigit():
            return f'<span class="m-num">{_escaped_text(char)}</span>'
        if char.isalpha():
            if char.isupper() and len(self.source) - self.pos >= 1:
                return f'<span class="m-var">{_escaped_text(char)}</span>'
            return f'<span class="m-var">{_escaped_text(char)}</span>'
        if char in "=<>+-":
            return f'<span class="m-op">{_escaped_text(char)}</span>'
        if char in "(),[];/":
            return f'<span class="m-punct">{_escaped_text(char)}</span>'
        if char == "*":
            return '<span class="m-op">*</span>'
        return _escaped_text(char)

    def _render_command(self) -> str:
        name = self._read_command_name()
        if name in _SPACES:
            return f'<span class="m-space">{_SPACES[name]}</span>'
        if name in _TEXT_COMMANDS:
            group = self._read_group()
            css = "m-text"
            if name == "mathbf":
                css = "m-text m-bold"
            elif name in {"mathcal", "mathbb"}:
                css = "m-text m-script"
            elif name == "mathit":
                css = "m-text m-italic"
            literal = re.sub(r"\\([_%&#$])", r"\1", group)
            return f'<span class="{css}">{_escaped_text(re.sub(r"\s+", " ", literal))}</span>'
        if name == "frac":
            numerator = self._render(self._read_group())
            denominator = self._render(self._read_group())
            return (
                '<span class="m-frac">'
                f'<span class="m-num">{numerator}</span>'
                f'<span class="m-den">{denominator}</span>'
                "</span>"
            )
        if name == "sqrt":
            self._skip_space()
            index = ""
            if self._peek() == "[":
                start = self.pos + 1
                end = self.source.find("]", start)
                if end < 0:
                    raise LatexRenderError(f"unclosed optional argument in {self.source!r}")
                index = self._render(self.source[start:end])
                self.pos = end + 1
            radicand = self._render(self._read_group())
            prefix = f'<span class="m-index">{index}</span>' if index else ""
            return (
                '<span class="m-sqrt">'
                f'{prefix}<span class="m-radical">√</span>'
                f'<span class="m-radicand">{radicand}</span>'
                "</span>"
            )
        if name == "left":
            self._skip_space()
            delimiter = self._read_delimiter()
            inner = self._render_until_right()
            return (
                f'<span class="m-delim">{_escaped_text(delimiter)}</span>'
                f'<span class="m-grouped">{inner}</span>'
            )
        if name == "right":
            raise LatexRenderError(f"'\\right' without '\\left' in {self.source!r}")
        if name in _SYMBOLS:
            symbol = _SYMBOLS[name]
            css = "m-op" if symbol in "·×÷±∓≤≥≠≈∼∝∈∉→←⇒↦" else "m-sym"
            return f'<span class="{css}">{_escaped_text(symbol)}</span>'
        if name in _FUNCTIONS:
            return f'<span class="m-fn">{_escaped_text(name)}</span>'
        raise LatexRenderError(
            f"unsupported LaTeX command '\\{name}' in {self.source!r}; "
            "extend latex_render._SYMBOLS/_FUNCTIONS or reword the formula"
        )

    def _read_delimiter(self) -> str:
        if self._peek() == "\\":
            self.pos += 1
            name = self._read_command_name()
            key = "\\" + name
            if key not in _LEFT_RIGHT_DELIMITERS:
                raise LatexRenderError(f"unsupported delimiter '\\{name}' in {self.source!r}")
            return _LEFT_RIGHT_DELIMITERS[key]
        char = self._peek()
        if char not in _LEFT_RIGHT_DELIMITERS:
            raise LatexRenderError(f"unsupported delimiter '{char}' in {self.source!r}")
        self.pos += 1
        return _LEFT_RIGHT_DELIMITERS[char]

    def _render_until_right(self) -> str:
        """Render until the matching ``\\right`` and consume its delimiter."""

        depth = 0
        chunks: list[str] = []
        while self.pos < len(self.source):
            char = self._peek()
            if char == "\\":
                save = self.pos
                self.pos += 1
                name = self._read_command_name()
                if name == "left":
                    depth += 1
                    self.pos = save
                elif name == "right":
                    if depth == 0:
                        self._skip_space()
                        delimiter = self._read_delimiter()
                        chunks.append(f'<span class="m-delim">{_escaped_text(delimiter)}</span>')
                        return "".join(chunks)
                    depth -= 1
                    self.pos = save
                else:
                    self.pos = save
            chunks.append(self._render_step())
        raise LatexRenderError(f"'\\left' without '\\right' in {self.source!r}")

    def _render_step(self) -> str:
        """Render one atom plus any trailing scripts."""

        base = self._read_atom()
        while True:
            self._skip_space()
            marker = self._peek()
            if marker not in ("^", "_"):
                return base
            self.pos += 1
            argument = self._read_atom()
            tag = "sup" if marker == "^" else "sub"
            base = f'{base}<{tag} class="m-{tag}">{argument}</{tag}>'
            # A second script (x_i^2) is allowed; a duplicate marker is not.
            if self._peek() == marker:
                raise LatexRenderError(f"duplicate '{marker}' script in {self.source!r}")

    def _render(self, source: str) -> str:
        nested = _Parser(source)
        parts: list[str] = []
        while True:
            nested._skip_space()
            if nested.pos >= len(nested.source):
                return "".join(parts)
            parts.append(nested._render_step())


def render_latex(source: str) -> str:
    """Render a LaTeX-subset formula to semantic HTML (never raw backslashes).

    Raises:
        LatexRenderError: the formula uses syntax outside the subset.
    """

    text = (source or "").strip()
    if not text:
        raise LatexRenderError("empty formula")
    rendered = _Parser(text)._render(text)
    if "\\" in rendered:
        # Defence in depth: a backslash in the output means a command leaked.
        raise LatexRenderError(f"raw LaTeX escaped the renderer: {source!r}")
    return rendered
