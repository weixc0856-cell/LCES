# Media Checks

Phase 5 adds media verification, driven by a concrete need: a release may
contain `media/course.mp4`, `course.srt`, or `course.vtt`, and until now Gate 4
reported those as `NOT_RUN`.

## What is checked

Gate 4 (`_media_checks` in `validation.py`) runs against the staged release
directory:

| Check | Blocks? | What it verifies |
|---|---|---|
| `media_decodable` | yes | `ffprobe` reads the file; a video stream, positive duration, and valid dimensions exist |
| `media_audio_present` | no (warn) | Reports the audio codec, or that there is no audio stream |
| `subtitle_timing` | yes | Every cue ends after it starts, cues stay in order, and none exceed the video duration |

When the release has no media, Gate 4 reports `NOT_RUN` rather than `PASS`.
When `ffmpeg`/`ffprobe` are not installed, it reports `NOT_RUN` with the
missing tool named. A file FFmpeg cannot decode is a `FAIL`, never a warning.

`lces media-check` runs the same probe by hand and samples frames:

```powershell
uv run lces media-check .\build\media\course.mp4 --frames 4 --out .\var\media-frames
```

Frames are written for human review only. Their existence is not evidence that
the content is correct.

## Boundaries

- LCES generates animation/video through the Motion Canvas adapter (frames, manifest,
  encode report, Gate 4 checks). Manim, Remotion and ParaView are not integrated;
  FFmpeg is used for encoding and inspection.
- Do not present a schematic animation as measured simulation output.
- Do not change a colour scale to hide differences in results.
- Record data source, units, parameters, and any interpolation or smoothing
  before publishing scientific visuals.
- A decodable file is not a correct file: audio/subtitle sync, frame content,
  and numerical results remain human review.
- Failed renders must not be recorded as successful; the check reports what
  FFmpeg actually returned.

## Traceability

The release manifest records file hashes for every delivered file, including
media, so a published video can be tied to the build that produced it. Media
files are copied into `release/` only from `build/media/`, never from arbitrary
paths.
