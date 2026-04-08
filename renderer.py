"""
renderer.py — Build an interactive ER diagram using vis.js with SVG image nodes.

Each model is rendered as an SVG table card (encoded as a base64 data URI) so that
vis.js can display rich, styled nodes. Physics is disabled after stabilization so
nodes stay where they are after the initial layout settles.
"""
from __future__ import annotations

import base64
import html as html_mod
import json
import textwrap
from typing import Optional

from parser import Model

# ── Card dimensions ────────────────────────────────────────────────────────────
_W = 340          # card width px
_HEADER_H = 36    # header row height
_DESC_H = 22      # description row height
_ROW_H = 26       # column row height


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
    # Cover lower rounded corners of header so body looks flush
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


def build_network(models: list[Model], visible_models: Optional[set[str]] = None) -> str:
    """
    Build a vis.js ER diagram from parsed models and return a standalone HTML string.
    visible_models: if provided, only those model names are rendered.
    """
    all_names = {m.name for m in models}

    nodes: list[dict] = []
    edges: list[dict] = []

    for model in models:
        if visible_models and model.name not in visible_models:
            continue
        svg, h = _model_svg(model)
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

    for model in models:
        if visible_models and model.name not in visible_models:
            continue
        for col in model.columns:
            if not col.foreign_key:
                continue
            target = col.foreign_key.to_model
            if target not in all_names:
                continue
            if visible_models and target not in visible_models:
                continue
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
  physics: {{
    enabled: true,
    solver: "forceAtlas2Based",
    forceAtlas2Based: {{
      gravitationalConstant: -150,
      centralGravity: 0.005,
      springLength: 350,
      springConstant: 0.04,
      damping: 0.95
    }},
    stabilization: {{ iterations: 400, updateInterval: 25 }}
  }},
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

// Freeze layout once the graph settles so nodes don't drift
network.on("stabilizationIterationsDone", function() {{
  network.setOptions({{ physics: {{ enabled: false }} }});
}});
</script>
</body>
</html>"""
