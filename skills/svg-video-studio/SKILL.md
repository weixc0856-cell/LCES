---
name: svg-video-studio
description: Defines visual scenes and renders SVG/Canvas/video reproducibly.
---
Each scene should declare scene_id, duration, fps, canvas size, scale mode, data references, font requirements and relevant source IDs. Explicitly select GLOBAL_ABSOLUTE_SCALE or ROW_INTERNAL_NORMALIZED. Prefer same-browser frame capture; if using dual renderers, document that pixel equivalence is not guaranteed. Never claim a video exists unless it exists and can be decoded.
