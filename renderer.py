"""
renderer.py — Build an interactive ER diagram using vis.js with SVG image nodes.

Node positions are pre-computed in Python using a topological layout so cards
never overlap on first render. Physics is disabled entirely; users can freely
drag nodes without spring-back.

Layout direction: left → right following FK edges.
  • Models with FK columns (consumers / fact tables) sit on the left.
  • Referenced models (dimensions / staging) sit on the right.
  • Arrows point left → right, i.e. outward from the most "dependent" nodes.
"""
from __future__ import annotations

import base64
import html as html_mod
import json
import textwrap
from collections import defaultdict, deque
from typing import Optional

from parser import Model

# ── Card dimensions ────────────────────────────────────────────────────────────
_W = 340          # card width px
_HEADER_H = 36    # header row height
_DESC_H = 22      # description row height
_ROW_H = 26       # column row height

# ── Layout spacing ─────────────────────────────────────────────────────────────
_H_GAP = 120      # horizontal gap between columns of cards
_V_GAP = 60       # vertical gap between cards in the same column


def _e(text: str) -> str:
    """XML-escape a string for safe SVG embedding."""
    return html_mod.escape(str(text), quote=True)


def _model_svg(model: Model) -> tuple[str, int]:
    """Return (svg_string, height_px) for one model card."""
    desc = textwrap.shorten(model.description, 52, placeholder="…") if model.description else ""
    d_h = _DESC_H if desc else 0
    n_rows = max(len(model.columns), 1)
    total_h = _HEADER_H + d_h + n_rows * _ROW_H + 2

    p: list[str] = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{total_h}">')
    p.append('<defs><style>text{font-family:Arial,Helvetica,sans-serif}</style></defs>')

    # ── Card background + border ──────────────────────────────────────────────
    p.append(f'<rect width="{_W}" height="{total_h}" fill="white" rx="6" ry="6" '
             f'stroke="#bdc3c7" stroke-width="1.5"/>')

    # ── Header ────────────────────────────────────────────────────────────────
    p.append(f'<rect width="{_W}" height="{_HEADER_H}" fill="#2c3e50" rx="6" ry="6"/>')
    p.append(f'<rect y="{_HEADER_H - 6}" width="{_W}" height="6" fill="#2c3e50"/>')
    p.append(f'<text x="10" y="24" fill="#ecf0f1" font-size="13" font-weight="bold">'
             f'{_e(model.name)}</text>')

    y = _HEADER_H

    # ── Description row ───────────────────────────────────────────────────────
    if desc:
        p.append(f'<rect x="0" y="{y}" width="{_W}" height="{_DESC_H}" fill="#f8f9fa"/>')
        p.append(f'<line x1="0" y1="{y + _DESC_H}" x2="{_W}" y2="{y + _DESC_H}" '
                 f'stroke="#ecf0f1" stroke-width="1"/>')
        p.append(f'<text x="10" y="{y + 15}" fill="#7f8c8d" font-size="10" font-style="italic">'
                 f'{_e(desc)}</text>')
        y += _DESC_H

    # ── Column rows ───────────────────────────────────────────────────────────
    cols = model.columns or []
    for i, col in enumerate(cols):
        if col.is_primary_key:
            row_bg = "#fff8e1"
        elif col.foreign_key:
            row_bg = "#f0f4ff"
        elif i % 2 == 0:
            row_bg = "#ffffff"
        else:
            row_bg = "#f4f6f8"

        p.append(f'<rect x="0" y="{y}" width="{_W}" height="{_ROW_H}" fill="{row_bg}"/>')

        # PK / FK badge
        if col.is_primary_key:
            p.append(f'<rect x="6" y="{y+5}" width="22" height="15" fill="#f39c12" rx="3"/>')
            p.append(f'<text x="9" y="{y+16}" fill="white" font-size="9" font-weight="bold">PK</text>')
        elif col.foreign_key:
            p.append(f'<rect x="6" y="{y+5}" width="22" height="15" fill="#3498db" rx="3"/>')
            p.append(f'<text x="9" y="{y+16}" fill="white" font-size="9" font-weight="bold">FK</text>')

        # Column name
        fw = "bold" if col.is_primary_key else "normal"
        p.append(f'<text x="34" y="{y+18}" fill="#2d3436" font-size="12" font-weight="{fw}">'
                 f'{_e(col.name[:32])}</text>')

        # Data-type chip
        if col.data_type:
            dt = col.data_type[:14]
            dt_w = int(len(dt) * 6.5 + 10)
            p.append(f'<rect x="195" y="{y+6}" width="{dt_w}" height="14" fill="#dfe6e9" rx="3"/>')
            p.append(f'<text x="200" y="{y+17}" fill="#2d3436" font-size="9"'
                     f' font-family="monospace">{_e(dt)}</text>')

        # Row divider
        p.append(f'<line x1="0" y1="{y+_ROW_H}" x2="{_W}" y2="{y+_ROW_H}" '
                 f'stroke="#ecf0f1" stroke-width="1"/>')

        y += _ROW_H

    if not cols:
        p.append(f'<text x="10" y="{y+17}" fill="#aaaaaa" font-size="11">No columns defined</text>')

    p.append('</svg>')
    return "\n".join(p), total_h


def _svg_to_data_uri(svg: str) -> str:
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _infer_relation_label(fk_col_tests: list[str]) -> str:
    return "1 : 1" if "unique" in fk_col_tests else "many : 1"


def _compute_layout(
    node_names: list[str],
    fk_edges: list[tuple[str, str]],
    node_heights: dict[str, int],
) -> dict[str, tuple[float, float]]:
    """
    Compute non-overlapping (x, y) positions using a topological LR layout.

    Each FK edge goes  src ──→ dst  where src has the FK column and dst is
    the referenced model.  We assign:
      • column 0 (leftmost)  = nodes that are not referenced by anyone
                               (pure consumers: fact tables, etc.)
      • column 1, 2, …       = nodes reached by following FK edges
      • rightmost column     = nodes with no outgoing FK edges (pure dims)

    Arrows therefore point left → right, i.e. "outward" from the consumers
    toward the dimension/staging tables they depend on.

    Within each column nodes are stacked top-to-bottom, centred on y = 0,
    with their actual pixel heights taken into account so they never overlap.
    """
    node_set = set(node_names)
    out_nbrs: dict[str, set[str]] = defaultdict(set)
    in_nbrs:  dict[str, set[str]] = defaultdict(set)

    for src, dst in fk_edges:
        if src in node_set and dst in node_set:
            out_nbrs[src].add(dst)
            in_nbrs[dst].add(src)

    # ── Assign columns via longest-path from sources ──────────────────────────
    # "sources" = nodes with no incoming FK edges (nobody references them)
    col: dict[str, int] = {}
    queue: deque[str] = deque()

    for n in node_names:
        if not in_nbrs[n]:
            col[n] = 0
            queue.append(n)

    while queue:
        n = queue.popleft()
        for nb in out_nbrs[n]:
            candidate = col[n] + 1
            if candidate > col.get(nb, -1):
                col[nb] = candidate
                queue.append(nb)

    # Nodes unreachable from any source (isolated or in a cycle) → column 0
    for n in node_names:
        if n not in col:
            col[n] = 0

    # ── Group by column (sort alphabetically for determinism) ─────────────────
    by_col: dict[int, list[str]] = defaultdict(list)
    for n in sorted(node_names):
        by_col[col[n]].append(n)

    # ── Stack nodes within each column, centred on y = 0 ─────────────────────
    positions: dict[str, tuple[float, float]] = {}

    for c, nodes_in_col in by_col.items():
        x = c * (_W + _H_GAP)
        heights = [node_heights.get(n, _HEADER_H + _ROW_H) for n in nodes_in_col]
        total_h = sum(heights) + _V_GAP * (len(heights) - 1)
        y = -total_h / 2  # top of first card

        for name, h in zip(nodes_in_col, heights):
            positions[name] = (x, y + h / 2)  # vis.js anchors at centre
            y += h + _V_GAP

    return positions


def build_network(models: list[Model], visible_models: Optional[set[str]] = None) -> str:
    """
    Build a vis.js ER diagram from parsed models and return a standalone HTML string.
    visible_models: if provided, only those model names are rendered.
    """
    all_names = {m.name for m in models}
    visible_ms = [m for m in models if not visible_models or m.name in visible_models]

    # ── Build SVG nodes ───────────────────────────────────────────────────────
    node_heights: dict[str, int] = {}
    nodes: list[dict] = []

    for model in visible_ms:
        svg, h = _model_svg(model)
        node_heights[model.name] = h
        nodes.append({
            "id":     model.name,
            "label":  model.name,
            "shape":  "image",
            "image":  _svg_to_data_uri(svg),
            "width":  _W,
            "height": h,
            "title":  f"<b>{_e(model.name)}</b><br>{_e(model.description)}"
                      f"<br><small>{_e(model.source_file)}</small>",
        })

    # ── Collect FK edges ──────────────────────────────────────────────────────
    fk_pairs: list[tuple[str, str]] = []
    edges: list[dict] = []

    for model in visible_ms:
        for col in model.columns:
            if not col.foreign_key:
                continue
            target = col.foreign_key.to_model
            if target not in all_names:
                continue
            if visible_models and target not in visible_models:
                continue
            fk_pairs.append((model.name, target))
            rel = _infer_relation_label(col.tests)
            edges.append({
                "from":   model.name,
                "to":     target,
                "label":  rel,
                "title":  f"{model.name}.{col.name} → {target}.{col.foreign_key.to_column} ({rel})",
                "arrows": {"to": {"enabled": True, "scaleFactor": 0.9}},
                "color":  {"color": "#74b9ff", "highlight": "#0984e3"},
                "font":   {"size": 11, "background": "rgba(255,255,255,0.85)", "strokeWidth": 0},
                "smooth": {"type": "curvedCW", "roundness": 0.25},
            })

    # ── Pre-compute positions ─────────────────────────────────────────────────
    positions = _compute_layout(
        [m.name for m in visible_ms],
        fk_pairs,
        node_heights,
    )
    for nd in nodes:
        if nd["id"] in positions:
            nd["x"], nd["y"] = positions[nd["id"]]

    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <style>
    body {{ margin:0; padding:0; background:#f0f2f5; }}
    #network {{ width:100%; height:780px; }}
  </style>
</head>
<body>
<div id="network"></div>
<script>
var nodes = new vis.DataSet({nodes_json});
var edges = new vis.DataSet({edges_json});

var options = {{
  physics: {{ enabled: false }},
  interaction: {{
    hover: true,
    navigationButtons: true,
    keyboard: true,
    tooltipDelay: 80,
    zoomView: true,
    dragView: true
  }},
  nodes: {{
    borderWidth: 0,
    shapeProperties: {{ useImageSize: true, useBorderWithImage: false }},
    chosen: {{
      node: function(values) {{
        values.shadow = true;
        values.shadowSize = 10;
      }}
    }}
  }},
  edges: {{
    width: 2,
    selectionWidth: 3
  }}
}};

var network = new vis.Network(
  document.getElementById("network"),
  {{ nodes: nodes, edges: edges }},
  options
);

// Fit all nodes into view after render
network.once("afterDrawing", function() {{
  network.fit({{ animation: {{ duration: 600, easingFunction: "easeInOutQuad" }} }});
}});
</script>
</body>
</html>"""
