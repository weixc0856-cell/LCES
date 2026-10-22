import json
import re

import pytest
from pydantic import ValidationError

from content_studio.errors import ConfigurationError, RenderError, UnsupportedVisualType
from content_studio.models import (
    ChartBlock,
    FigureBlock,
    ParagraphBlock,
    PublicContent,
    PublicSlide,
    TableBlock,
    VisualSpec,
)
from content_studio.paths import template_dir
from content_studio.renderers import (
    FigureRenderer,
    RenderContext,
    Renderer,
    RendererRegistry,
    ResourceEstimate,
    TableRenderer,
    default_registry,
)
from content_studio.rendering import build_public_html
from content_studio.visuals import render_content_visuals, specs_for_slide


def _table_spec(**overrides) -> VisualSpec:
    values = {
        "visual_id": "slide-001-block-01",
        "visual_type": "table",
        "data": {
            "caption": "复杂度",
            "columns": ["操作", "复杂度"],
            "rows": [["自注意力", "O(n²·d)"]],
        },
    }
    values.update(overrides)
    return VisualSpec(**values)


def _content() -> PublicContent:
    return PublicContent(
        project_id="render-test",
        title="渲染测试",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=[
                    ParagraphBlock(text="正文"),
                    TableBlock(
                        caption="对比",
                        columns=["指标", "数值"],
                        rows=[["延迟", "1.2 ms"]],
                    ),
                ],
            )
        ],
    )


def test_table_renderer_escapes_and_renders():
    spec = _table_spec(
        data={
            "caption": "<caption>",
            "columns": ["<th>"],
            "rows": [["<td>"]],
        }
    )
    output = default_registry().render(spec, RenderContext())

    assert output.renderer == "html.table"
    assert output.renderer_version == TableRenderer.version
    assert "&lt;caption&gt;" in output.html
    assert '<th scope="col">&lt;th&gt;</th>' in output.html
    assert "<td>&lt;td&gt;</td>" in output.html
    assert len(output.sha256) == 64


def test_unknown_visual_type_is_rejected():
    spec = _table_spec(visual_type="architecture_diagram")
    with pytest.raises(UnsupportedVisualType) as excinfo:
        default_registry().render(spec)
    assert "architecture_diagram" in str(excinfo.value)
    assert "table" in str(excinfo.value)


def test_explicit_renderer_mismatch_is_rejected():
    spec = _table_spec(renderer="mermaid")
    with pytest.raises(UnsupportedVisualType):
        default_registry().render(spec)


def test_duplicate_registration_is_rejected():
    registry = RendererRegistry()
    registry.register(TableRenderer())
    with pytest.raises(ConfigurationError, match="already registered"):
        registry.register(TableRenderer())


def test_invalid_table_data_fails_instead_of_rendering():
    spec = _table_spec(data={"columns": ["a", "b"], "rows": [["only-one"]]})
    with pytest.raises(RenderError, match="wrong number of cells"):
        default_registry().render(spec)


def test_figure_requires_existing_asset(tmp_path):
    (tmp_path / "content" / "charts").mkdir(parents=True)
    (tmp_path / "content" / "charts" / "figure.svg").write_text("<svg/>", encoding="utf-8")

    good = VisualSpec(
        visual_id="slide-001-block-01",
        visual_type="figure_image",
        data={"path": "charts/figure.svg", "alt": "示意图", "caption": "说明"},
    )
    output = default_registry().render(good, RenderContext(project_dir=tmp_path))
    assert "<figure>" in output.html
    assert FigureRenderer.version == output.renderer_version

    missing = good.model_copy(update={"data": {"path": "charts/none.svg", "alt": "x"}})
    with pytest.raises(RenderError, match="missing asset"):
        default_registry().render(missing, RenderContext(project_dir=tmp_path))


def test_unsupported_schema_major_is_rejected():
    with pytest.raises(ValidationError, match="unsupported visual schema_version"):
        _table_spec(schema_version="2.0")


def test_specs_are_derived_for_table_and_figure_blocks():
    content = PublicContent(
        project_id="render-test",
        title="渲染测试",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=[
                    ParagraphBlock(text="正文"),
                    TableBlock(columns=["a"], rows=[["1"]]),
                    FigureBlock(path="charts/x.svg", alt="图"),
                ],
            )
        ],
    )
    specs = specs_for_slide(content.slides[0])
    assert [spec.visual_type for spec in specs] == ["table", "figure_image"]
    assert [spec.visual_id for spec in specs] == [
        "slide-001-block-01",
        "slide-001-block-02",
    ]


def _normalize(html: str) -> str:
    return re.sub(r">\s+<", "><", html.strip())


def test_registry_output_matches_legacy_template(tmp_path):
    content = _content()
    modern = build_public_html(content, template_dir(), tmp_path / "new" / "index.html")
    legacy = build_public_html(
        content, template_dir(), tmp_path / "old" / "index.html", use_registry=False
    )
    assert _normalize(modern.read_text(encoding="utf-8")) == _normalize(
        legacy.read_text(encoding="utf-8")
    )


def test_build_writes_render_manifest(tmp_path):
    project = tmp_path / "project"
    (project / "internal" / "qa").mkdir(parents=True)
    content = _content()

    build_public_html(
        content,
        template_dir(),
        project / "build" / "slides" / "index.html",
        project_dir=project,
    )

    manifest = json.loads(
        (project / "internal" / "qa" / "render_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == [
        {
            "visual_id": "slide-001-block-01",
            "visual_type": "table",
            "schema_version": "1.0",
            "slide_id": "slide-001",
            "block_index": 1,
            "renderer": "html.table",
            "renderer_version": "1.0.0",
            "output_sha256": manifest[0]["output_sha256"],
        }
    ]
    assert len(manifest[0]["output_sha256"]) == 64

    specs = json.loads(
        (project / "internal" / "qa" / "visual_specs.json").read_text(encoding="utf-8")
    )
    assert specs[0]["visual_type"] == "table"
    assert specs[0]["data"]["columns"] == ["指标", "数值"]

    assets = json.loads(
        (project / "internal" / "qa" / "visual_assets.json").read_text(encoding="utf-8")
    )
    assert len(assets) == 1
    asset = assets[0]
    assert asset["asset_id"] == "slide-001-block-01"
    assert asset["asset_type"] == "table"
    assert asset["renderer"] == "html.table"
    assert asset["status"] == "rendered"
    assert asset["output_paths"] == ["build/slides/index.html"]
    assert len(asset["output_hashes"]["build/slides/index.html"]) == 64
    assert asset["parameters"]["spec_sha256"]
    assert asset["qa_results"][0]["status"] == "pass"


def test_chart_asset_records_its_svg_artifact(tmp_path):
    pytest.importorskip("vl_convert")
    project = tmp_path / "project"
    (project / "internal" / "qa").mkdir(parents=True)
    content = PublicContent(
        project_id="render-test",
        title="渲染测试",
        slides=[
            PublicSlide(slide_id="slide-001", title="第一节", body=[_chart_block()]),
        ],
    )

    build_public_html(
        content,
        template_dir(),
        project / "build" / "slides" / "index.html",
        project_dir=project,
    )

    assets = json.loads(
        (project / "internal" / "qa" / "visual_assets.json").read_text(encoding="utf-8")
    )
    assert assets[0]["asset_type"] == "chart"
    assert assets[0]["renderer"] == "vega_lite.chart"
    assert assets[0]["output_paths"] == ["build/slides/visuals/slide-001-block-00.svg"]
    assert len(assets[0]["output_hashes"]["build/slides/visuals/slide-001-block-00.svg"]) == 64


def test_render_content_visuals_returns_positions():
    rendered = render_content_visuals(_content())
    assert len(rendered) == 1
    assert (rendered[0].slide_id, rendered[0].block_index) == ("slide-001", 1)


VEGA_SPEC = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "data": {"values": [{"x": "A", "y": 1}, {"x": "B", "y": 3}]},
    "mark": "bar",
    "encoding": {
        "x": {"field": "x", "type": "nominal"},
        "y": {"field": "y", "type": "quantitative"},
    },
}


def _chart_block(spec: dict | None = None) -> ChartBlock:
    return ChartBlock(caption="示例图表", alt="柱状图", spec=spec or VEGA_SPEC)


def test_chart_block_maps_to_data_chart_spec():
    content = PublicContent(
        project_id="render-test",
        title="渲染测试",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=[ParagraphBlock(text="正文"), _chart_block()],
            )
        ],
    )
    specs = specs_for_slide(content.slides[0])
    assert [spec.visual_type for spec in specs] == ["data_chart"]
    assert specs[0].data["vega_lite"]["mark"] == "bar"


def test_custom_svg_requires_alt_and_blocks_unsafe_markup(tmp_path):
    charts = tmp_path / "content" / "charts"
    charts.mkdir(parents=True)
    (charts / "ok.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    (charts / "script.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )
    (charts / "remote.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil/x.png"/></svg>',
        encoding="utf-8",
    )

    def spec(path: str) -> VisualSpec:
        return VisualSpec(
            visual_id="slide-001-block-01",
            visual_type="custom_svg",
            data={"path": path, "alt": "示意"},
        )

    output = default_registry().render(spec("charts/ok.svg"), RenderContext(project_dir=tmp_path))
    assert "<svg" in output.html
    assert 'role="img"' in output.html
    assert output.renderer == "svg.custom"

    with pytest.raises(RenderError, match="script"):
        default_registry().render(spec("charts/script.svg"), RenderContext(project_dir=tmp_path))
    with pytest.raises(RenderError, match="external reference"):
        default_registry().render(spec("charts/remote.svg"), RenderContext(project_dir=tmp_path))
    with pytest.raises(RenderError, match="must live under content"):
        default_registry().render(spec("../outside.svg"), RenderContext(project_dir=tmp_path))


def test_vega_lite_chart_renders_static_svg(tmp_path):
    pytest.importorskip("vl_convert")
    spec = VisualSpec(
        visual_id="slide-001-block-01",
        visual_type="data_chart",
        data={"vega_lite": VEGA_SPEC, "alt": "柱状图", "caption": "示例"},
    )
    output = default_registry().render(spec, RenderContext(output_dir=tmp_path))

    assert output.renderer == "vega_lite.chart"
    assert "<svg" in output.html
    assert 'role="img"' in output.html
    assert "max-width:100%" in output.html
    assert "<script" not in output.html.lower()
    artifact = tmp_path / "visuals" / "slide-001-block-01.svg"
    assert artifact.is_file()
    assert artifact.read_text(encoding="utf-8").startswith("<svg")
    assert output.artifacts == (artifact,)


def test_invalid_vega_spec_fails_with_a_clear_message(tmp_path):
    pytest.importorskip("vl_convert")
    spec = VisualSpec(
        visual_id="slide-001-block-01",
        visual_type="data_chart",
        data={"vega_lite": {"mark": "nonsense"}, "alt": "坏图"},
    )
    with pytest.raises(RenderError, match="Vega-Lite rendering failed"):
        default_registry().render(spec, RenderContext(output_dir=tmp_path))


def test_legacy_path_rejects_chart_blocks(tmp_path):
    content = PublicContent(
        project_id="render-test",
        title="渲染测试",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=[_chart_block()],
            )
        ],
    )
    with pytest.raises(RenderError, match="chart blocks require the renderer registry"):
        build_public_html(content, template_dir(), tmp_path / "index.html", use_registry=False)


class _FakeRenderer(Renderer):
    name = "fake.renderer"
    version = "9.9.9"
    visual_types = frozenset({"fake"})

    def __init__(self, environment=None, input_problems=None) -> None:
        self.calls: list[str] = []
        self._environment = environment or []
        self._input_problems = input_problems or []

    def check_environment(self) -> list[str]:
        return self._environment

    def validate_input(self, spec: VisualSpec) -> list[str]:
        return self._input_problems

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        return ResourceEstimate(cpu_seconds=1.5, memory_mb=128, notes="fake")

    def render(self, spec: VisualSpec, context: RenderContext) -> str:
        self.calls.append("render")
        return "<div>ok</div>"

    def validate(self, spec: VisualSpec, html: str) -> list[str]:
        return []


def _fake_spec() -> VisualSpec:
    return VisualSpec(visual_id="fake-001", visual_type="fake")


def test_registry_refuses_when_environment_is_not_ready():
    registry = RendererRegistry()
    renderer = _FakeRenderer(environment=["missing dot binary"])
    registry.register(renderer)

    with pytest.raises(RenderError, match="not ready"):
        registry.render(_fake_spec())

    assert renderer.calls == [], "environment check must run before rendering"
    assert any("environment" in item for item in registry.diagnostics())


def test_registry_rejects_invalid_input_before_rendering():
    registry = RendererRegistry()
    renderer = _FakeRenderer(input_problems=["bad parameters"])
    registry.register(renderer)

    with pytest.raises(RenderError, match="bad parameters"):
        registry.render(_fake_spec())

    assert renderer.calls == []
    assert any("input" in item for item in registry.diagnostics())


def test_registry_reports_success_and_resets_diagnostics():
    registry = RendererRegistry()
    renderer = _FakeRenderer(environment=["broken"])
    registry.register(renderer)
    with pytest.raises(RenderError):
        registry.render(_fake_spec())
    assert registry.diagnostics()

    renderer._environment = []
    output = registry.render(_fake_spec())

    assert output.renderer == "fake.renderer"
    assert output.renderer_version == "9.9.9"
    assert renderer.calls == ["render"]
    assert registry.diagnostics() == []


def test_registry_estimates_resources_through_the_renderer():
    registry = RendererRegistry()
    registry.register(_FakeRenderer())
    estimate = registry.estimate(_fake_spec())
    assert estimate.cpu_seconds == pytest.approx(1.5)
    assert estimate.memory_mb == 128
