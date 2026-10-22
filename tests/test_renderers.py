import json
import re

import pytest
from pydantic import ValidationError

from content_studio.errors import ConfigurationError, RenderError, UnsupportedVisualType
from content_studio.models import (
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
    RendererRegistry,
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


def test_render_content_visuals_returns_positions():
    rendered = render_content_visuals(_content())
    assert len(rendered) == 1
    assert (rendered[0].slide_id, rendered[0].block_index) == ("slide-001", 1)
