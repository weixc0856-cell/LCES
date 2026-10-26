"""D2 structural preflight must fail on missing scenes and external assets."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _deck_checks():
    path = ROOT / "scripts" / "preflight-scene-recordings.py"
    spec = importlib.util.spec_from_file_location("scene_preflight", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.deck_checks


def _html() -> str:
    return """
    <html><body>
    <section id="slide-001" data-index="1">one</section>
    <section id="slide-002" data-index="2">two</section>
    <script>
    if (key === "ArrowRight") {}
    if (key === "ArrowLeft") {}
    if (key === "Home") {}
    if (key === "End") {}
    if (location.hash) {}
    history.replaceState(null, "", "#slide-001");
    </script>
    </body></html>
    """


def _status(checks, check_id):
    return next(item["status"] for item in checks if item["check_id"] == check_id)


def test_complete_deck_passes_structural_checks():
    checks = _deck_checks()(_html(), ["slide-001", "slide-002"])
    assert all(item["status"] == "pass" for item in checks)


def test_missing_scene_external_asset_and_raw_latex_fail():
    html = _html().replace('id="slide-002"', 'id="slide-999"')
    html = html.replace("<body>", '<body><img src="https://example.com/a.png">')
    html = html.replace("one", "one " + chr(92) + "frac{1}{2}")

    checks = _deck_checks()(html, ["slide-001", "slide-002"])

    assert _status(checks, "scene_sections") == "fail"
    assert _status(checks, "offline_assets") == "fail"
    assert _status(checks, "no_raw_latex") == "fail"
