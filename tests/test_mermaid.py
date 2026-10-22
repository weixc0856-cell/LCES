import pytest

from content_studio import renderers
from content_studio.errors import RenderError
from content_studio.models import VisualSpec
from content_studio.renderers import (
    MermaidRenderer,
    RenderContext,
    _mermaid_runtime_problem,
    default_registry,
    mermaid_runtime_path,
)

FLOWCHART = "flowchart TD\n  A[开始] --> B{判断}\n  B -->|是| C[结束]"
SEQUENCE = "sequenceDiagram\n  Alice->>Bob: Hello\n  Bob-->>Alice: Hi"


def _spec(code: str = FLOWCHART, alt: str = "流程图") -> VisualSpec:
    return VisualSpec(
        visual_id="diagram-001",
        visual_type="diagram",
        data={"mermaid": code, "alt": alt},
    )


def _require_environment() -> None:
    problems = MermaidRenderer().check_environment()
    if problems:
        pytest.skip("; ".join(problems))


def test_vendored_runtime_is_present_and_matches_manifest():
    runtime = mermaid_runtime_path()
    assert runtime.is_file()
    assert (runtime.parent / "manifest.json").is_file()
    assert _mermaid_runtime_problem() == ""


def test_missing_runtime_is_an_environment_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(renderers, "mermaid_runtime_path", lambda: tmp_path / "missing.js")
    problems = MermaidRenderer().check_environment()
    assert any("运行时缺失" in item for item in problems)


def test_runtime_hash_mismatch_is_rejected(tmp_path, monkeypatch):
    runtime = tmp_path / "mermaid.min.js"
    runtime.write_text("console.log('tampered')", encoding="utf-8")
    (tmp_path / "manifest.json").write_text('{"sha256": "deadbeef"}', encoding="utf-8")
    monkeypatch.setattr(renderers, "mermaid_runtime_path", lambda: runtime)

    problems = MermaidRenderer().check_environment()
    assert any("校验失败" in item for item in problems)


@pytest.mark.parametrize(
    "data",
    [
        {"mermaid": "", "alt": "x"},
        {"mermaid": FLOWCHART, "alt": ""},
        {"mermaid": "%%{init: {'securityLevel':'loose'}}%%\nflowchart TD\n A-->B", "alt": "x"},
        {"mermaid": 'flowchart TD\n A-->B\n click A "javascript:alert(1)"', "alt": "x"},
    ],
)
def test_invalid_diagram_inputs_are_rejected_before_rendering(data):
    spec = VisualSpec(visual_id="diagram-001", visual_type="diagram", data=data)
    assert MermaidRenderer().validate_input(spec)


def test_oversized_source_is_rejected():
    problems = MermaidRenderer().validate_input(_spec("flowchart TD\n" + "A" * 20_001))
    assert any("exceeds" in item for item in problems)


def test_renders_a_flowchart_offline(tmp_path):
    _require_environment()
    output = default_registry().render(_spec(), RenderContext(output_dir=tmp_path))

    assert output.renderer == "mermaid.diagram"
    assert "<svg" in output.html
    assert 'aria-label="流程图"' in output.html
    assert "role=" in output.html
    assert "foreignObject" not in output.html
    assert "<script" not in output.html.lower()
    artifact = tmp_path / "visuals" / "diagram-001.svg"
    assert artifact.is_file()
    assert output.artifacts == (artifact,)


def test_renders_a_sequence_diagram(tmp_path):
    _require_environment()
    output = default_registry().render(_spec(SEQUENCE), RenderContext(output_dir=tmp_path))
    assert "<svg" in output.html
    assert "foreignObject" not in output.html


def test_invalid_mermaid_syntax_fails_loudly(tmp_path):
    _require_environment()
    with pytest.raises(RenderError, match="Mermaid 渲染失败"):
        default_registry().render(
            _spec("flowchart TD\n  A[ --> B"), RenderContext(output_dir=tmp_path)
        )


def test_malicious_label_is_sanitised_by_mermaid_and_the_output_check(tmp_path):
    _require_environment()
    code = 'flowchart TD\n  A["<img src=x onerror=alert(1)>"] --> B'
    output = default_registry().render(_spec(code), RenderContext(output_dir=tmp_path))

    assert "<script" not in output.html.lower()
    assert "onerror" not in output.html.lower()
    assert "javascript:" not in output.html.lower()
    assert "foreignObject" not in output.html


def test_svg_sanitizer_rejects_active_content():
    problems = renderers.svg_problems(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://x/y.png"/>'
        '<rect onload="alert(1)"/></svg>',
        "test",
    )
    assert any("external reference" in item for item in problems)
    assert any("event handler" in item for item in problems)


def test_timeout_is_reported_as_a_failure(tmp_path, monkeypatch):
    _require_environment()
    monkeypatch.setattr(MermaidRenderer, "timeout_ms", 1)
    with pytest.raises(RenderError, match="超时"):
        default_registry().render(_spec(), RenderContext(output_dir=tmp_path))


def test_init_directive_is_blocked_by_the_registry(tmp_path):
    _require_environment()
    spec = _spec("%%{init: {'securityLevel':'loose'}}%%\nflowchart TD\n A-->B")
    registry = default_registry()
    with pytest.raises(RenderError, match="init directives"):
        registry.render(spec, RenderContext(output_dir=tmp_path))
    assert any("input" in item for item in registry.diagnostics())
