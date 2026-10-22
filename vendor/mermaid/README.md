# Vendored Mermaid runtime

LCES renders Mermaid diagrams offline. The runtime is delivered with the
repository; no CDN or network access is used at render time.

| Field | Value |
|---|---|
| Version | 12.2.0 |
| License | MIT (`LICENSE`) |
| Source | `https://registry.npmjs.org/mermaid/-/mermaid-12.2.0.tgz` |
| Tarball integrity | `sha512-w7nr/SFrLO7BaVTs3dQTvYSV6nYSBj0Yy9DjBhsIJtAcHqRzXSq4Pg32ujHZ/AdWsAMNEvvhbm5dt9E2tOiHzw==` |
| File | `mermaid.min.js` (5,494,801 bytes) |
| File sha256 | see `manifest.json` |

`manifest.json` is machine-read: `MermaidRenderer.check_environment()` verifies
`mermaid.min.js` against the recorded sha256 before any render and refuses to
run if it does not match.

## Upgrade procedure

1. Pick a version and fetch its metadata from the npm registry; record
   `dist.tarball` and `dist.integrity`.
2. Download the tarball into an empty temporary directory (outside the repo),
   verify the sha512 integrity, then extract only `package/dist/mermaid.min.js`
   and `package/LICENSE`.
3. Replace the files here, recompute `sha256` into `manifest.json`, and update
   the version/source/integrity fields.
4. Run `uv run pytest tests/test_mermaid.py` and `uv run lces doctor`; render a
   flowchart and a sequence diagram and confirm the SVG has no
   `<foreignObject>`, `<script>`, or external references.
5. Record the change in the commit message. Do not track "latest" — every
   upgrade is an explicit, reviewed version bump.

## Security posture

- Renderer config is fixed in code: `securityLevel: "strict"`,
  `htmlLabels: false`, `maxTextSize: 20000`, `maxEdges: 500`.
- Inputs containing `%%{ ... }%%` init directives or `click` directives are
  rejected before rendering.
- The browser context is created with `offline=True`; the harness loads only
  this local file.
- Output SVG is checked independently (well-formed XML, root `<svg>`, no
  scripts, no event handlers, no external references) before it is inlined.

Mermaid is MIT-licensed; see `LICENSE` in this directory.
