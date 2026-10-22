"""Controlled Motion Canvas scene templates (P2.2).

Only validated data reaches this module. Every template is a fixed piece of
TypeScript in this file; scene data is embedded as JSON literals, so a label
can never become code. `title` keeps the P1/P2.1 output; `flow` and `compare`
are P2's new templates.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from string import Template
from typing import Any

from content_studio.models import SceneContract
from content_studio.timeline import TimelinePlan

SUPPORTED_SCENE_TYPES = frozenset({"title", "flow", "compare"})
FLOW_NODE_KINDS = frozenset({"start", "step", "decision", "end"})
COMMON_KEYS = frozenset({"title", "subtitle", "accent_color", "background_color"})
FLOW_KEYS = COMMON_KEYS | {"direction", "nodes", "edges"}
COMPARE_KEYS = COMMON_KEYS | {"left", "right"}
ELEMENT_ID = r"^[a-z0-9][a-z0-9-]{0,31}$"
HEX_COLOUR = r"^#[0-9a-fA-F]{6}$"

MAX_TITLE = {"title": 200, "flow": 120, "compare": 120}
MAX_FLOW_NODES = 6
MAX_FLOW_EDGES = 10
MAX_COMPARE_ITEMS = 6


@dataclass(frozen=True)
class FlowNode:
    id: str
    label: str
    kind: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class FlowEdge:
    source: str
    target: str
    label: str
    x1: float
    y1: float
    x2: float
    y2: float
    lx: float
    ly: float


@dataclass(frozen=True)
class FlowGeometry:
    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...]
    title_size: float
    label_size: float
    title_y: float
    subtitle_y: float


@dataclass(frozen=True)
class CompareItem:
    text: str
    y: float


@dataclass(frozen=True)
class ComparePanel:
    title: str
    x: float
    y: float
    width: float
    height: float
    items: tuple[CompareItem, ...]


@dataclass(frozen=True)
class CompareGeometry:
    panels: tuple[ComparePanel, ...]
    title_size: float
    subtitle_size: float
    panel_title_size: float
    item_size: float
    title_y: float
    subtitle_y: float


# -- validation -----------------------------------------------------------


def data_problems(scene_type: str, data: dict[str, Any], width: int, height: int) -> list[str]:
    """Problems with one template's data; empty means renderable."""

    allowed = {"title": COMMON_KEYS, "flow": FLOW_KEYS, "compare": COMPARE_KEYS}.get(scene_type)
    if allowed is None:
        return [f"unsupported scene_type '{scene_type}'"]
    problems: list[str] = []
    unknown = sorted(set(data) - allowed)
    if unknown:
        problems.append(f"unknown data field(s): {', '.join(unknown)}")

    title = data.get("title")
    limit = MAX_TITLE[scene_type]
    if not isinstance(title, str) or not title.strip():
        problems.append("data.title must be a non-empty string")
    elif len(title) > limit:
        problems.append(f"data.title exceeds {limit} characters")
    subtitle = data.get("subtitle", "")
    if not isinstance(subtitle, str) or len(subtitle) > 200:
        problems.append("data.subtitle must be a string <= 200 characters")
    for key in ("accent_color", "background_color"):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or not _is_hex(value)):
            problems.append(f"data.{key} must be #rrggbb")

    if scene_type == "flow":
        problems.extend(_flow_problems(data, width, height))
    elif scene_type == "compare":
        problems.extend(_compare_problems(data, width, height))
    return problems


def _is_hex(value: str) -> bool:
    return (
        len(value) == 7
        and value[0] == "#"
        and all(c in "0123456789abcdefABCDEF" for c in value[1:])
    )


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(ELEMENT_ID, value) is not None


def _flow_problems(data: dict[str, Any], width: int, height: int) -> list[str]:
    problems: list[str] = []
    direction = data.get("direction", "lr")
    if direction not in {"lr", "tb"}:
        problems.append("data.direction must be 'lr' or 'tb'")

    nodes = data.get("nodes")
    node_ids: set[str] = set()
    if not isinstance(nodes, list):
        problems.append("data.nodes must be a list")
    elif not 2 <= len(nodes) <= MAX_FLOW_NODES:
        problems.append(f"data.nodes must contain 2-{MAX_FLOW_NODES} items")
    else:
        for index, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                problems.append(f"node {index} must be an object")
                continue
            extra = set(node) - {"id", "label", "kind"}
            if extra:
                problems.append(f"node {index} has unknown field(s): {', '.join(sorted(extra))}")
            identifier = node.get("id")
            if not isinstance(identifier, str) or not _valid_id(identifier):
                problems.append(f"node {index}: id must match {ELEMENT_ID}")
            elif identifier in node_ids:
                problems.append(f"node {index}: duplicate id '{identifier}'")
            else:
                node_ids.add(identifier)
            label = node.get("label")
            if not isinstance(label, str) or not 1 <= len(label) <= 40:
                problems.append(f"node {index}: label must be 1-40 characters")
            kind = node.get("kind", "step")
            if kind not in FLOW_NODE_KINDS:
                problems.append(f"node {index}: kind must be one of {sorted(FLOW_NODE_KINDS)}")

    edges = data.get("edges")
    if not isinstance(edges, list):
        problems.append("data.edges must be a list")
    elif not 1 <= len(edges) <= MAX_FLOW_EDGES:
        problems.append(f"data.edges must contain 1-{MAX_FLOW_EDGES} items")
    elif isinstance(nodes, list) and node_ids:
        seen: set[tuple[str, str]] = set()
        for index, edge in enumerate(edges, start=1):
            if not isinstance(edge, dict):
                problems.append(f"edge {index} must be an object")
                continue
            extra = set(edge) - {"from", "to", "label"}
            if extra:
                problems.append(f"edge {index} has unknown field(s): {', '.join(sorted(extra))}")
            source = edge.get("from")
            target = edge.get("to")
            if not isinstance(source, str) or source not in node_ids:
                problems.append(f"edge {index}: 'from' must reference a node")
            if not isinstance(target, str) or target not in node_ids:
                problems.append(f"edge {index}: 'to' must reference a node")
            if isinstance(source, str) and source == target:
                problems.append(f"edge {index}: self-loops are not supported")
            pair = (str(source), str(target))
            if pair in seen:
                problems.append(f"edge {index}: duplicate edge {pair[0]} -> {pair[1]}")
            seen.add(pair)
            label = edge.get("label", "")
            if not isinstance(label, str) or len(label) > 24:
                problems.append(f"edge {index}: label must be a string <= 24 characters")

    if not problems:
        _geometry, error = _flow_geometry(data, width, height)
        if error:
            problems.append(error)
    return problems


def _compare_problems(data: dict[str, Any], width: int, height: int) -> list[str]:
    problems: list[str] = []
    for side in ("left", "right"):
        panel = data.get(side)
        if not isinstance(panel, dict):
            problems.append(f"data.{side} must be an object")
            continue
        extra = set(panel) - {"title", "items"}
        if extra:
            problems.append(f"data.{side} has unknown field(s): {', '.join(sorted(extra))}")
        title = panel.get("title")
        if not isinstance(title, str) or not 1 <= len(title) <= 60:
            problems.append(f"data.{side}.title must be 1-60 characters")
        items = panel.get("items")
        if not isinstance(items, list):
            problems.append(f"data.{side}.items must be a list")
        elif not 1 <= len(items) <= MAX_COMPARE_ITEMS:
            problems.append(f"data.{side}.items must contain 1-{MAX_COMPARE_ITEMS} items")
        else:
            for index, item in enumerate(items, start=1):
                if not isinstance(item, str) or not 1 <= len(item) <= 120:
                    problems.append(
                        f"data.{side}.items[{index}] must be a string of 1-120 characters"
                    )
    if not problems:
        _geometry, error = _compare_geometry(data, width, height)
        if error:
            problems.append(error)
    return problems


# -- geometry -------------------------------------------------------------


def _flow_geometry(
    data: dict[str, Any], width: int, height: int
) -> tuple[FlowGeometry | None, str]:
    nodes = data["nodes"]
    edges = data["edges"]
    direction = data.get("direction", "lr")
    margin_x = max(80.0, width * 0.06)
    margin_y = max(80.0, height * 0.06)
    content_w = width - 2 * margin_x
    content_h = height - 2 * margin_y
    if content_w < 240 or content_h < 140:
        return None, "canvas is too small for a flow scene"
    title_size = max(18.0, min(56.0, width * 0.029))
    label_size = max(14.0, min(28.0, width * 0.0146))
    top = -height / 2 + margin_y
    title_y = top + title_size / 2
    subtitle_y = title_y + title_size * 0.9

    positions: dict[str, tuple[float, float, float, float]] = {}
    if direction == "lr":
        gap = 32.0
        if len(nodes) * 120 + (len(nodes) - 1) * gap > content_w:
            return None, "too many flow nodes for the canvas width"
        node_w = min(280.0, (content_w - (len(nodes) - 1) * gap) / len(nodes))
        node_h = min(96.0, max(64.0, content_h * 0.45))
        flow_y = top + title_size + 48 + node_h / 2
        start_x = -content_w / 2 + node_w / 2
        step = (content_w - node_w) / (len(nodes) - 1)
        for index, node in enumerate(nodes):
            positions[node["id"]] = (start_x + index * step, flow_y, node_w, node_h)
    else:
        available = content_h - title_size - 64
        gap = 28.0
        if len(nodes) * 72 + (len(nodes) - 1) * gap > available:
            return None, "too many flow nodes for the canvas height"
        node_h = min(140.0, (available - (len(nodes) - 1) * gap) / len(nodes))
        node_w = min(360.0, content_w)
        start_y = top + title_size + 64 + node_h / 2
        step = node_h + gap
        for index, node in enumerate(nodes):
            positions[node["id"]] = (0.0, start_y + index * step, node_w, node_h)

    node_models = tuple(
        FlowNode(
            id=node["id"],
            label=node["label"],
            kind=node.get("kind", "step"),
            x=positions[node["id"]][0],
            y=positions[node["id"]][1],
            width=positions[node["id"]][2],
            height=positions[node["id"]][3],
        )
        for node in nodes
    )
    by_id = {node.id: node for node in node_models}
    edge_models: list[FlowEdge] = []
    for edge in edges:
        source = by_id[edge["from"]]
        target = by_id[edge["to"]]
        if direction == "lr":
            forward = target.x >= source.x
            x1 = source.x + (source.width / 2 if forward else -source.width / 2)
            x2 = target.x + (-target.width / 2 if forward else target.width / 2)
            y1 = source.y
            y2 = target.y
            lx = (x1 + x2) / 2
            ly = min(y1, y2) - 14
        else:
            forward = target.y >= source.y
            y1 = source.y + (source.height / 2 if forward else -source.height / 2)
            y2 = target.y + (-target.height / 2 if forward else target.height / 2)
            x1 = source.x
            x2 = target.x
            lx = (x1 + x2) / 2 + 18
            ly = (y1 + y2) / 2
        edge_models.append(
            FlowEdge(
                source=source.id,
                target=target.id,
                label=edge.get("label", ""),
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                lx=lx,
                ly=ly,
            )
        )
    return (
        FlowGeometry(
            nodes=node_models,
            edges=tuple(edge_models),
            title_size=title_size,
            label_size=label_size,
            title_y=title_y,
            subtitle_y=subtitle_y,
        ),
        "",
    )


def _compare_geometry(
    data: dict[str, Any], width: int, height: int
) -> tuple[CompareGeometry | None, str]:
    if width < 320 or height < 180:
        return None, "canvas is too small for a compare scene"
    margin_x = max(24.0, width * 0.06)
    margin_y = max(24.0, height * 0.06)
    content_w = width - 2 * margin_x
    content_h = height - 2 * margin_y
    gap = width * 0.04
    panel_w = (content_w - gap) / 2
    if panel_w < 120 or content_h < 140:
        return None, "canvas is too narrow for two compare panels"

    title_size = max(18.0, min(64.0, width * 0.075))
    subtitle_size = max(12.0, min(32.0, width * 0.035))
    panel_title_size = max(12.0, min(36.0, width * 0.04))
    item_size = max(12.0, min(26.0, width * 0.022))
    top = -height / 2 + margin_y
    title_y = top + title_size / 2
    subtitle_y = title_y + title_size * 0.8
    panel_top = top + title_size + (subtitle_size * 1.6 if data.get("subtitle") else 16) + 18
    panel_h = height / 2 - margin_y - panel_top
    if panel_h < 120:
        return None, "canvas is too short for compare panels"
    panel_y = panel_top + panel_h / 2
    inner_w = panel_w - 40
    chars_per_line = max(1, int(inner_w / (item_size * 0.62)))
    line_height = item_size * 1.45
    item_gap = item_size * 0.55

    panels: list[ComparePanel] = []
    for side_index, side in enumerate(("left", "right")):
        panel_data = data[side]
        items: list[CompareItem] = []
        cursor = -panel_h / 2 + panel_title_size + 34
        for text in panel_data["items"]:
            lines = max(1, math.ceil(len(text) / chars_per_line))
            height_used = lines * line_height
            if cursor + height_used > panel_h / 2 - 16:
                return None, f"compare {side} items do not fit the panel"
            items.append(CompareItem(text=text, y=cursor + height_used / 2))
            cursor += height_used + item_gap
        x = (-1 if side_index == 0 else 1) * (gap / 2 + panel_w / 2)
        panels.append(
            ComparePanel(
                title=panel_data["title"],
                x=x,
                y=panel_y,
                width=panel_w,
                height=panel_h,
                items=tuple(items),
            )
        )
    return (
        CompareGeometry(
            panels=tuple(panels),
            title_size=title_size,
            subtitle_size=subtitle_size,
            panel_title_size=panel_title_size,
            item_size=item_size,
            title_y=title_y,
            subtitle_y=subtitle_y,
        ),
        "",
    )


# -- source generation ----------------------------------------------------


def scene_source(scene: SceneContract, plan: TimelinePlan, *, width: int, height: int) -> str:
    if scene.scene_type == "flow":
        return _flow_source(scene, plan, width=width, height=height)
    if scene.scene_type == "compare":
        return _compare_source(scene, plan, width=width, height=height)
    return _title_source(scene, plan, width=width, height=height)


def _duration(plan: TimelinePlan) -> float:
    return float(Fraction(plan.total_frames * plan.fps_den, plan.fps_num))


def _header(scene: SceneContract, plan: TimelinePlan) -> str:
    return (
        "// Generated by content_studio.motion_canvas from SceneContract.data.\n"
        f"// Scene: {scene.scene_id} | {plan.total_frames} frames @ "
        f"{plan.fps_num}/{plan.fps_den} fps\n"
        "// Do not edit by hand.\n"
    )


def _title_source(scene: SceneContract, plan: TimelinePlan, *, width: int, height: int) -> str:
    data = scene.data
    title = _ts_string(str(data.get("title", "")))
    subtitle = _ts_string(str(data.get("subtitle", "")))
    accent = _ts_string(str(data.get("accent_color", "#4cc9f0")))
    background = _ts_string(str(data.get("background_color", "#0b1220")))
    duration = _duration(plan)
    return (
        _header(scene, plan)
        + f"""import {{Layout, Rect, Txt, makeScene2D}} from '@motion-canvas/2d';
import {{all, createRef, easeOutCubic, waitFor}} from '@motion-canvas/core';

const TITLE = {title};
const SUBTITLE = {subtitle};
const ACCENT = {accent};
const BACKGROUND = {background};
const DURATION = {duration!r};

export default makeScene2D(function* (view) {{
  const title = createRef<Txt>();
  const subtitle = createRef<Txt>();
  view.fill(BACKGROUND);
  view.add(
    <Layout>
      <Rect width={{{width}}} height={{{height}}} fill={{BACKGROUND}} />
      <Rect y={{-170}} width={{560}} height={{8}} fill={{ACCENT}} />
      <Txt ref={{title}} y={{-20}} opacity={{0}} fontSize={{96}}
        fill={{'#f7fbff'}} text={{TITLE}} />
      <Txt ref={{subtitle}} y={{110}} opacity={{0}} fontSize={{42}}
        fill={{'#9fb3c8'}} text={{SUBTITLE}} />
    </Layout>,
  );
  yield* all(title().opacity(1, 0.8, easeOutCubic), title().y(-70, 0.8, easeOutCubic));
  yield* subtitle().opacity(1, 0.6, easeOutCubic);
  yield* waitFor(Math.max(0, DURATION - 1.4));
}});
"""
    )


def _flow_source(scene: SceneContract, plan: TimelinePlan, *, width: int, height: int) -> str:
    geometry, error = _flow_geometry(scene.data, width, height)
    if geometry is None:
        raise ValueError(f"flow scene is not renderable: {error}")
    data = scene.data
    nodes = [
        {
            "id": node.id,
            "label": node.label,
            "kind": node.kind,
            "x": round(node.x, 2),
            "y": round(node.y, 2),
            "width": round(node.width, 2),
            "height": round(node.height, 2),
        }
        for node in geometry.nodes
    ]
    edges = [
        {
            "x1": round(edge.x1, 2),
            "y1": round(edge.y1, 2),
            "x2": round(edge.x2, 2),
            "y2": round(edge.y2, 2),
            "label": edge.label,
            "lx": round(edge.lx, 2),
            "ly": round(edge.ly, 2),
        }
        for edge in geometry.edges
    ]
    values = {
        "TITLE": _ts_string(str(data.get("title", ""))),
        "SUBTITLE": _ts_string(str(data.get("subtitle", ""))),
        "ACCENT": _ts_string(str(data.get("accent_color", "#4cc9f0"))),
        "BACKGROUND": _ts_string(str(data.get("background_color", "#0b1220"))),
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "DURATION": repr(_duration(plan)),
        "TITLE_SIZE": repr(round(geometry.title_size, 2)),
        "LABEL_SIZE": repr(round(geometry.label_size, 2)),
        "TITLE_Y": repr(round(geometry.title_y, 2)),
        "SUBTITLE_Y": repr(round(geometry.subtitle_y, 2)),
        "LINE_WIDTH": repr(round(max(2.0, min(4.0, width * 0.0015)), 2)),
        "NODES": _ts_json(nodes),
        "EDGES": _ts_json(edges),
    }
    template = Template(
        _header(scene, plan)
        + """import {Layout, Line, Rect, Txt, makeScene2D} from '@motion-canvas/2d';
import {all, createRef, easeOutCubic, waitFor} from '@motion-canvas/core';

const TITLE = $TITLE;
const SUBTITLE = $SUBTITLE;
const ACCENT = $ACCENT;
const BACKGROUND = $BACKGROUND;
const WIDTH = $WIDTH;
const HEIGHT = $HEIGHT;
const DURATION = $DURATION;
const TITLE_SIZE = $TITLE_SIZE;
const LABEL_SIZE = $LABEL_SIZE;
const TITLE_Y = $TITLE_Y;
const SUBTITLE_Y = $SUBTITLE_Y;
const NODES = $NODES;
const EDGES = $EDGES;

export default makeScene2D(function* (view) {
  const nodes = NODES.map(() => createRef<Rect>());
  const lines = EDGES.map(() => createRef<Line>());
  const labels = EDGES.map(() => createRef<Txt>());
  view.fill(BACKGROUND);
  view.add(
    <Layout>
      <Rect width={WIDTH} height={HEIGHT} fill={BACKGROUND} />
      <Txt y={TITLE_Y} fontSize={TITLE_SIZE} fill={'#f7fbff'} text={TITLE} />
      {SUBTITLE ? <Txt y={SUBTITLE_Y} fontSize={TITLE_SIZE * 0.55}
        fill={'#9fb3c8'} text={SUBTITLE} /> : null}
      {EDGES.map((edge, i) => (
        <Line ref={lines[i]} points={[[edge.x1, edge.y1], [edge.x2, edge.y2]]}
          stroke={ACCENT} lineWidth={$LINE_WIDTH} endArrow opacity={0} />
      ))}
      {EDGES.map((edge, i) => (
        <Txt ref={labels[i]} x={edge.lx} y={edge.ly} fontSize={LABEL_SIZE * 0.8}
          fill={'#9fb3c8'} text={edge.label} opacity={0} />
      ))}
      {NODES.map((node, i) => (
        <Rect ref={nodes[i]} x={node.x} y={node.y + 24} width={node.width}
          height={node.height} radius={14}
          fill={node.kind === 'start' || node.kind === 'end' ? '#123b4a' : '#101a2b'}
          stroke={node.kind === 'decision' ? '#f2b84b' : ACCENT}
          lineWidth={2} opacity={0}>
          <Txt text={node.label} fontSize={LABEL_SIZE} fill={'#f7fbff'}
            textWrap width={node.width - 16} />
        </Rect>
      ))}
    </Layout>,
  );
  const per = Math.min(0.35, (DURATION * 0.7) / Math.max(1, NODES.length + EDGES.length));
  for (let i = 0; i < nodes.length; i++) {
    yield* all(nodes[i]().opacity(1, per, easeOutCubic),
      nodes[i]().y(NODES[i].y, per, easeOutCubic));
  }
  for (let i = 0; i < lines.length; i++) {
    yield* all(lines[i]().opacity(1, per, easeOutCubic),
      labels[i]().opacity(1, per, easeOutCubic));
  }
  yield* waitFor(Math.max(0, DURATION - per * (NODES.length + EDGES.length)));
});
"""
    )
    return template.substitute(values)


def _compare_source(scene: SceneContract, plan: TimelinePlan, *, width: int, height: int) -> str:
    geometry, error = _compare_geometry(scene.data, width, height)
    if geometry is None:
        raise ValueError(f"compare scene is not renderable: {error}")
    data = scene.data
    panels = [
        {
            "title": panel.title,
            "x": round(panel.x, 2),
            "y": round(panel.y, 2),
            "width": round(panel.width, 2),
            "height": round(panel.height, 2),
            "items": [{"text": item.text, "y": round(item.y, 2)} for item in panel.items],
        }
        for panel in geometry.panels
    ]
    total_items = sum(len(panel.items) for panel in geometry.panels)
    values = {
        "TITLE": _ts_string(str(data.get("title", ""))),
        "SUBTITLE": _ts_string(str(data.get("subtitle", ""))),
        "ACCENT": _ts_string(str(data.get("accent_color", "#4cc9f0"))),
        "BACKGROUND": _ts_string(str(data.get("background_color", "#0b1220"))),
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "DURATION": repr(_duration(plan)),
        "TITLE_SIZE": repr(round(geometry.title_size, 2)),
        "SUBTITLE_SIZE": repr(round(geometry.subtitle_size, 2)),
        "PANEL_TITLE_SIZE": repr(round(geometry.panel_title_size, 2)),
        "ITEM_SIZE": repr(round(geometry.item_size, 2)),
        "TITLE_Y": repr(round(geometry.title_y, 2)),
        "SUBTITLE_Y": repr(round(geometry.subtitle_y, 2)),
        "PANELS": _ts_json(panels),
        "TOTAL_ITEMS": str(total_items),
    }
    template = Template(
        _header(scene, plan)
        + """import {Layout, Rect, Txt, makeScene2D} from '@motion-canvas/2d';
import {all, createRef, easeOutCubic, waitFor} from '@motion-canvas/core';

const TITLE = $TITLE;
const SUBTITLE = $SUBTITLE;
const ACCENT = $ACCENT;
const BACKGROUND = $BACKGROUND;
const WIDTH = $WIDTH;
const HEIGHT = $HEIGHT;
const DURATION = $DURATION;
const TITLE_SIZE = $TITLE_SIZE;
const SUBTITLE_SIZE = $SUBTITLE_SIZE;
const PANEL_TITLE_SIZE = $PANEL_TITLE_SIZE;
const ITEM_SIZE = $ITEM_SIZE;
const TITLE_Y = $TITLE_Y;
const SUBTITLE_Y = $SUBTITLE_Y;
const PANELS = $PANELS;
const TOTAL_ITEMS = $TOTAL_ITEMS;

export default makeScene2D(function* (view) {
  const title = createRef<Txt>();
  const subtitle = createRef<Txt>();
  const panels = PANELS.map(() => createRef<Rect>());
  const items = PANELS.map(panel => panel.items.map(() => createRef<Txt>()));
  view.fill(BACKGROUND);
  view.add(
    <Layout>
      <Rect width={WIDTH} height={HEIGHT} fill={BACKGROUND} />
      <Txt ref={title} y={TITLE_Y} fontSize={TITLE_SIZE} fill={'#f7fbff'}
        text={TITLE} opacity={0} />
      <Txt ref={subtitle} y={SUBTITLE_Y} fontSize={SUBTITLE_SIZE}
        fill={'#9fb3c8'} text={SUBTITLE} opacity={0} />
      {PANELS.map((panel, i) => (
        <Rect ref={panels[i]} x={panel.x + (i === 0 ? -60 : 60)} y={panel.y}
          width={panel.width} height={panel.height} radius={20}
          fill={'#101a2b'} stroke={ACCENT} lineWidth={2} opacity={0}>
          <Txt y={-panel.height / 2 + 30} fontSize={PANEL_TITLE_SIZE}
            fill={ACCENT} text={panel.title} />
          {panel.items.map((item, j) => (
            <Txt ref={items[i][j]} y={item.y} width={panel.width - 40}
              textWrap textAlign={'left'} fontSize={ITEM_SIZE}
              fill={'#dbe7f3'} text={item.text} opacity={0} />
          ))}
        </Rect>
      ))}
    </Layout>,
  );
  const per = Math.min(0.3, (DURATION * 0.6) / Math.max(1, TOTAL_ITEMS + 4));
  yield* all(title().opacity(1, per, easeOutCubic),
    subtitle().opacity(1, per, easeOutCubic));
  for (let i = 0; i < panels.length; i++) {
    yield* all(panels[i]().opacity(1, per, easeOutCubic),
      panels[i]().x(PANELS[i].x, per, easeOutCubic));
  }
  for (let i = 0; i < items.length; i++) {
    for (let j = 0; j < items[i].length; j++) {
      yield* items[i][j]().opacity(1, per, easeOutCubic);
    }
  }
  yield* waitFor(Math.max(0, DURATION - per * (TOTAL_ITEMS + 4)));
});
"""
    )
    return template.substitute(values)


def _ts_string(value: str) -> str:
    # JSON string literals are valid TypeScript; ensure_ascii also escapes
    # U+2028/U+2029, which some JS parsers treat as line breaks.
    return json.dumps(value, ensure_ascii=True)


def _ts_json(value: Any) -> str:
    # JSON literals cannot express functions, imports, or statements.
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
