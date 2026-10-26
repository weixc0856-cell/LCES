"""Browser runtime for the HTML deck: steps, reset, deep links, record mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from content_studio.models import (
    CheckBlock,
    ContentOutline,
    OutlineSection,
    ParagraphBlock,
    PublicContent,
    PublicSlide,
    ScriptSection,
    SpeakerScript,
)
from content_studio.paths import ensure_project_layout
from content_studio.rendering import build_public_html
from content_studio.utils import write_json

TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "public_html"


def _content() -> PublicContent:
    return PublicContent(
        project_id="runtime-demo",
        title="运行时测试课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一幕",
                body=[
                    ParagraphBlock(text="第一幕第一段。"),
                    ParagraphBlock(text="第一幕第二段。"),
                    CheckBlock(question="第一幕问题？", answer="第一幕答案。"),
                ],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-002",
                title="第二幕",
                body=[
                    ParagraphBlock(text="第二幕第一段。"),
                    ParagraphBlock(text="第二幕第二段。"),
                    CheckBlock(question="第二幕问题？", answer="第二幕答案。"),
                ],
                source_ids=["source-001"],
            ),
        ],
    )


def _outline() -> ContentOutline:
    return ContentOutline(
        project_id="runtime-demo",
        title="运行时测试课程",
        sections=[
            OutlineSection(
                slide_id=f"slide-{index:03d}",
                title=f"第 {index} 幕",
                learning_objectives=[f"目标 {index}"],
                estimated_minutes=1.0,
            )
            for index in (1, 2)
        ],
        total_minutes=2.0,
    )


def _script() -> SpeakerScript:
    return SpeakerScript(
        project_id="runtime-demo",
        sections=[
            # One second per scene => three 800 ms steps (MIN_STEP_MS).
            ScriptSection(slide_id=f"slide-{index:03d}", narration="短讲稿。", estimated_seconds=1)
            for index in (1, 2)
        ],
        total_estimated_seconds=2,
    )


@pytest.fixture(scope="module")
def deck_uri(tmp_path_factory) -> str:
    root = ensure_project_layout(tmp_path_factory.mktemp("runtime") / "project")
    content = _content()
    write_json(root / "content" / "public_content.json", content)
    write_json(root / "content" / "outline.json", _outline())
    write_json(root / "internal" / "speaker_script.json", _script())
    build_public_html(
        content, TEMPLATES, root / "build" / "slides" / "index.html", project_dir=root
    )
    return (root / "build" / "slides" / "index.html").resolve().as_uri()


@pytest.fixture(scope="module")
def chromium():
    playwright = pytest.importorskip("playwright.sync_api")
    manager = playwright.sync_playwright().start()
    try:
        browser = manager.chromium.launch()
    except Exception as exc:  # pragma: no cover - environment failure
        manager.stop()
        pytest.skip(f"Chromium 无法启动: {exc.__class__.__name__}")
    yield browser
    browser.close()
    manager.stop()


def _open(browser, uri: str, *, width: int = 1920, height: int = 1080):
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    errors: list[str] = []
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(uri, wait_until="load")
    page.wait_for_function("window.__lces && window.__lces.ready === true")
    return context, page, errors


def test_scene_opens_in_static_state(chromium, deck_uri):
    context, page, errors = _open(chromium, f"{deck_uri}#slide-002")
    try:
        assert page.evaluate("__lces.sceneId") == "slide-002"
        assert page.evaluate("__lces.total") == 3
        assert page.evaluate("__lces.step") == 3
        assert page.evaluate("__lces.state") == "static"
        assert page.evaluate(
            "Array.from(document.querySelectorAll('.slide.is-active .block'))"
            ".every(block => block.classList.contains('is-revealed'))"
        )
        assert errors == []
    finally:
        context.close()


def test_replay_advance_pause_and_reset(chromium, deck_uri):
    context, page, errors = _open(chromium, f"{deck_uri}#slide-002")
    try:
        assert page.evaluate("__lces.replay()") is True
        assert page.evaluate("[__lces.step, __lces.playing, __lces.state]") == [0, True, "playing"]
        page.evaluate("__lces.pause()")
        durations = page.evaluate("__lces.durations")
        assert page.evaluate(f"__lces.advance({durations[0]})") == 1
        assert page.evaluate(f"__lces.advance({durations[1]})") == 2
        assert page.evaluate(
            "Array.from(document.querySelectorAll('.slide.is-active .block'))"
            ".map(block => block.classList.contains('is-revealed'))"
        ) == [True, True, False]

        page.evaluate("__lces.pause()")
        paused_at = page.evaluate("__lces.step")
        page.wait_for_timeout(400)
        assert page.evaluate("__lces.step") == paused_at
        assert page.evaluate("__lces.playing") is False

        page.evaluate("__lces.reset()")
        assert page.evaluate("[__lces.step, __lces.state, __lces.playing]") == [3, "static", False]
        assert (
            page.evaluate(
                "Array.from(document.querySelectorAll('.slide.is-active .block'))"
                ".filter(block => block.classList.contains('is-pending'))"
                ".length"
            )
            == 0
        )
        assert (
            page.evaluate(
                "document.querySelectorAll('.slide.is-active .block.is-focus,"
                ".slide.is-active .block.effect-draw,.slide.is-active .block.effect-lab').length"
            )
            == 0
        )
        assert errors == []
    finally:
        context.close()


def test_same_step_gives_the_same_visual_state(chromium, deck_uri):
    context, page, _errors = _open(chromium, f"{deck_uri}#slide-002")
    try:

        def snapshot():
            return page.evaluate(
                "Array.from(document.querySelectorAll('.slide.is-active .block'))"
                ".map(block => block.className)"
            )

        page.evaluate("__lces.seekStep(2)")
        first = snapshot()
        page.evaluate("__lces.seekStep(0)")
        page.evaluate("__lces.seekStep(2)")
        assert snapshot() == first
    finally:
        context.close()


def test_deep_link_opens_scene_at_step(chromium, deck_uri):
    context, page, _errors = _open(chromium, f"{deck_uri}#slide-002/1")
    try:
        assert page.evaluate("[__lces.sceneId, __lces.step, __lces.state]") == [
            "slide-002",
            1,
            "paused",
        ]
        assert page.evaluate(
            "Array.from(document.querySelectorAll('.slide.is-active .block'))"
            ".map(block => block.classList.contains('is-revealed'))"
        ) == [True, False, False]
    finally:
        context.close()


def test_hash_change_switches_scene_and_step(chromium, deck_uri):
    context, page, errors = _open(chromium, f"{deck_uri}#slide-001")
    try:
        page.evaluate("location.hash = 'slide-002'")
        page.wait_for_function("window.__lces.sceneId === 'slide-002'")
        assert page.evaluate("[__lces.step, __lces.total, __lces.state]") == [3, 3, "static"]

        page.evaluate("location.hash = 'slide-002/1'")
        page.wait_for_function("window.__lces.step === 1")
        assert page.evaluate("__lces.sceneId") == "slide-002"
        assert errors == []
    finally:
        context.close()


def test_scene_switch_clears_animation_state(chromium, deck_uri):
    context, page, _errors = _open(chromium, f"{deck_uri}#slide-002")
    try:
        page.evaluate("__lces.replay()")
        page.evaluate("__lces.advance(800)")
        assert page.evaluate("__lces.gotoScene('slide-001')") is True
        assert page.evaluate("[__lces.sceneId, __lces.step, __lces.total, __lces.state]") == [
            "slide-001",
            3,
            3,
            "static",
        ]
        assert (
            page.evaluate(
                "document.querySelectorAll('.slide.is-active .block.is-pending,"
                ".slide.is-active .block.is-focus').length"
            )
            == 0
        )
        assert page.evaluate("__lces.gotoScene('slide-002')") is True
        assert page.evaluate("__lces.step") == 3
    finally:
        context.close()


def test_record_mode_fills_a_16_9_viewport(chromium, deck_uri):
    context, page, errors = _open(chromium, f"{deck_uri}?record=1#slide-002")
    try:
        assert page.evaluate("__lces.record") is True
        assert (
            page.evaluate("getComputedStyle(document.querySelector('.deck-bar')).display") == "none"
        )
        assert (
            page.evaluate("getComputedStyle(document.querySelector('.page-foot')).display")
            == "none"
        )
        box = page.evaluate(
            "(() => { const r = document.getElementById('stage').getBoundingClientRect();"
            " return [r.x, r.y, r.width, r.height]; })()"
        )
        assert box == [0, 0, 1920, 1080]
        assert page.evaluate(
            "[document.documentElement.scrollWidth, document.documentElement.clientWidth,"
            " document.documentElement.scrollHeight, document.documentElement.clientHeight]"
        ) == [1920, 1920, 1080, 1080]
        assert errors == []
    finally:
        context.close()


def test_record_mode_keeps_16_9_without_overflow_in_a_16_10_window(chromium, deck_uri):
    context, page, errors = _open(
        chromium, f"{deck_uri}?record=1#slide-002", width=1280, height=800
    )
    try:
        size = page.evaluate(
            "(() => { const r = document.getElementById('stage').getBoundingClientRect();"
            " return {w: r.width, h: r.height,"
            " overflow: document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth}; })()"
        )
        assert size["w"] == pytest.approx(1280, abs=1)
        assert size["w"] / size["h"] == pytest.approx(16 / 9, rel=1e-3)
        assert size["overflow"] == 0
        assert errors == []
    finally:
        context.close()
