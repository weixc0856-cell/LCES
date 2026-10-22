# Third-party licenses

Before public distribution, record each bundled dependency or asset, version,
license, attribution requirements and intended use. This scaffold does not
bundle third-party fonts, images, music or icons.

## Optional tooling used by LCES

| Component | Version | License | Use in LCES |
|---|---|---|---|
| Playwright (Python) | 1.64.0 | Apache-2.0 | Gate 3 browser QA (optional `browser` extra) |
| Chromium headless shell | 156.0.8078.4 | BSD-3-Clause and others | Rendered by Playwright; downloaded at install time, not vendored |
| vl-convert-python | 1.9.0.post1 | Apache-2.0 | Static SVG rendering for `data_chart` specs (optional `charts` extra) |
| Vega-Lite / Vega | bundled by vl-convert | BSD-3-Clause / Apache-2.0 | Chart specification language; runs inside vl-convert |
| Mermaid | not used | MIT | Considered for flowcharts; no vendored build in this repo |
| Graphviz | not used | EPL-1.0 | Considered for graph layout; `dot` not required by LCES |

Chromium and Playwright are downloaded to the user's machine by
`playwright install`; they are not committed to this repository. Charts are
rendered offline by vl-convert, so no CDN or network access is needed at
build time.

## Runtime Python dependencies

The direct dependencies declared in `pyproject.toml` (Typer, Pydantic,
pydantic-settings, PyYAML, httpx, Jinja2, beautifulsoup4, pypdf, python-docx)
carry permissive licenses (MIT / BSD / Apache-2.0). Re-check the installed
metadata before redistribution:

```powershell
uv tree --depth 1
```

Generated course content may quote or summarise third-party sources. Quoting
a source does not by itself make redistribution lawful; record the source
license in the project's evidence ledger before release.
