# Motion Canvas P0 spike (not production)

This directory reproduces the Motion Canvas feasibility experiment in CI.
It is **not** wired into `renderers/` and must not be imported by LCES.

- Node 24.22.1, Motion Canvas 3.17.2, Vite 4.5.14, TypeScript 5.9.3
- 10 s / 30 fps / 1920×1080 → 300 frames, range pinned to frame 299
  (`src/project.meta`, `shared.range` is stored in **seconds**)
- `driver.mjs` drives the editor with Playwright; Modes:
  - `render` (default): require exactly `EXPECTED_FRAMES`
  - `cancel`: abort mid-render, require partial output
  - `timeout`: detect a still-running render and stop it
- Offline proof runs with `docker run --network none`; negative control
  (`fetch` / `npm install left-pad`) must fail.

## Run locally (requires network at build time)

```powershell
docker build -t lces-mc-p0 spike/motion-canvas
docker run --rm --network none -e MODE=render -e EXPECTED_FRAMES=300 `
  -v "$PWD/out-p0:/app/output" lces-mc-p0
```

Evidence is written to `/app/output/report.json` plus the PNG frames.

## CI

`.github/workflows/motion-canvas-p0.yml` (manual `workflow_dispatch`) builds
the image, runs the offline render, negative control, cancellation and
timeout modes, validates frames with FFmpeg, and uploads the evidence.

## Boundaries

- P0 only; no production integration, no release path.
- Memory/disk quotas are not fully exercised; only wall-clock timeout and a
  512 MB memory ceiling are applied in CI.
- The editor's render signals are DOM/text based, not an official API.
