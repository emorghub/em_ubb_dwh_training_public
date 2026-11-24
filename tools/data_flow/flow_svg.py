#!/usr/bin/env python3
"""Render and check ETL data-flow diagrams as standalone SVG (no database).

    python tools/data_flow/flow_svg.py render <spec.json> <out.svg>
    python tools/data_flow/flow_svg.py check  <diagram.svg> [--package SCHEMA.PKG]

``render`` sizes every box from its measured text, derives every connector
anchor from the box edges, writes the SVG and then runs ``check`` on it.
``check`` reads the geometry back from the SVG and reports every defect the
/do-data-flow skill forbids; it exits 1 when it finds any.

Spec (JSON)
-----------
title    the full package name as declared, e.g. "UBB_CORE2.PKG_ETL_X"
columns  [{"id": "S", "gap": 150}, ...] left to right; gap = space after it
flows    {"key": {"label": "...", "color": "#rrggbb", "style": "control"?}}
         one per independent source branch, one neutral "derived" flow for
         rows after a join, one "style": "control" flow (dotted arrows)
nodes    {"id", "kind", "flow"?, "title", "lines": [..], "col" | "x", "y",
          "w"?: number | "full"}   kind: source | step | target | control | note
         a line starting with "# " is a bold sub-heading
edges    {"from": [node, side, offset], "to": [node, side, offset|"match"],
          "label", "evidence", "flow", "id"?, "via"?: [[x, y], ..], "lane"?}
         side: L R T B; offset: distance from the top (L/R) or left (T/B),
         "mid", or "match" (reuse the other end's coordinate: a straight line)
         lane: distance of the vertical/horizontal jog from the target box
         evidence: where the package establishes it, e.g. "L152-L163 MERGE"
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

FONT = "Arial, Helvetica, sans-serif"
TITLE_SIZE, TEXT_SIZE, LABEL_SIZE = 18, 14, 12
PAD_X = 18
MARGIN = 40
CHIP_H = 20
ARROW = 16            # length of an arrowhead, kept clear of labels and corners
MIN_GAP = 60          # connected boxes
MIN_STACK_GAP = 35    # boxes that are not connected
NODE_BORDER_CLEAR = 12
TEXT_MARGIN_X, TEXT_MARGIN_Y = 10, 6
ANCHOR_SPACING = 20
LANE_SPACING = 12
BG = "#F8FAFC"
DARK_BG = "#0F172A"
TEXT = "#1E293B"

_FONT_FILES = {
    False: ["C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
    True: ["C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf",
           "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
}
_fonts: dict = {}


class SpecError(ValueError):
    pass


def _pil_font(size, bold):
    key = (size, bold)
    if key not in _fonts:
        font = None
        try:
            from PIL import ImageFont
            for path in _FONT_FILES[bold]:
                try:
                    font = ImageFont.truetype(path, size)
                    break
                except OSError:
                    continue
        except ImportError:
            pass
        _fonts[key] = font
    return _fonts[key]


def text_width(text, size, bold=False):
    """Rendered width in SVG units; a pessimistic estimate without Pillow."""
    font = _pil_font(size, bold)
    if font is not None:
        return font.getlength(text)
    return len(text) * size * (0.66 if bold else 0.62)


def _plain(line):
    return line[2:] if line.startswith("# ") else line


# ---------------------------------------------------------------- colours

def _rgb(hexs):
    h = hexs.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexs):
    r, g, b = (_lin(v) for v in _rgb(hexs))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


_CVD = {
    "protanopia": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216],
                   [-0.003882, -0.048116, 1.051998]],
    "deuteranopia": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413],
                     [-0.011820, 0.042940, 0.968881]],
    "tritanopia": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602],
                   [0.004733, 0.691367, 0.303900]],
}


def _lab(lin):
    r, g, b = lin
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def color_distance(a, b, vision=None):
    """CIE76 distance between two colours, optionally as seen with a colour-vision deficiency."""
    pair = []
    for hexs in (a, b):
        lin = [_lin(v) for v in _rgb(hexs)]
        if vision:
            m = _CVD[vision]
            lin = [min(1.0, max(0.0, sum(m[i][j] * lin[j] for j in range(3)))) for i in range(3)]
        pair.append(_lab(lin))
    return math.dist(pair[0], pair[1])


def _mix(hexs, amount):
    """Tint a colour towards white (amount 0..1)."""
    return "#%02X%02X%02X" % tuple(round(v + (255 - v) * amount) for v in _rgb(hexs))


def _darken(hexs, amount):
    return "#%02X%02X%02X" % tuple(round(v * (1 - amount)) for v in _rgb(hexs))


# ---------------------------------------------------------------- render

def _node_size(node):
    title_w = text_width(node["title"], TITLE_SIZE, True)
    lines = node.get("lines", [])
    widths = [title_w] + [text_width(_plain(l), TEXT_SIZE, l.startswith("# ")) for l in lines]
    w = math.ceil(max(widths) * 1.03 + 2 * PAD_X)
    h = 22 * len(lines) + 50 if lines else 46
    return w, h


def _layout(spec):
    nodes = {}
    for raw in spec["nodes"]:
        n = dict(raw)
        if n["id"] in nodes:
            raise SpecError(f"duplicate node {n['id']}")
        n["full"] = raw.get("w") == "full"
        n["w"], n["h"] = _node_size(n)
        if isinstance(raw.get("w"), (int, float)):
            n["w"] = max(n["w"], raw["w"])
        nodes[n["id"]] = n
    col_w = {}
    for n in nodes.values():
        if "col" in n:
            col_w[n["col"]] = max(col_w.get(n["col"], 0), n["w"])
    col_x, x = {}, MARGIN
    for c in spec["columns"]:
        col_x[c["id"]] = x
        x += col_w.get(c["id"], 0) + c.get("gap", 150)
    for n in nodes.values():
        if "col" in n:
            if n["col"] not in col_x:
                raise SpecError(f"node {n['id']}: unknown column {n['col']}")
            n["x"] = col_x[n["col"]]
    right = max(n["x"] + n["w"] for n in nodes.values() if not n["full"])
    for n in nodes.values():
        if n["full"]:
            n["w"] = max(n["w"], right - n["x"])
    return nodes


def _anchor(node, side, off, other=None):
    x, y, w, h = node["x"], node["y"], node["w"], node["h"]
    horizontal = side in "LR"
    span = h if horizontal else w
    if off == "mid":
        off = span / 2
    elif off == "match":
        if other is None:
            raise SpecError("both ends of an edge cannot be 'match'")
        off = (other[1] - y) if horizontal else (other[0] - x)
        if not 14 <= off <= span - 14:
            raise SpecError(
                f"edge into {node['id']}: the other end is not level with it "
                f"(offset {off:.0f} outside 14..{span - 14:.0f}); move a node or give an offset")
    if side == "L":
        return (x, y + off)
    if side == "R":
        return (x + w, y + off)
    if side == "T":
        return (x + off, y)
    return (x + off, y + h)


def _clean(points):
    out = []
    for p in points:
        if out and abs(out[-1][0] - p[0]) < 0.01 and abs(out[-1][1] - p[1]) < 0.01:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or \
           (abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01):
            del out[i]
        else:
            i += 1
    return out


def _route(p0, s0, p1, s1, via, lane):
    if via:
        pts = [p0] + [tuple(v) for v in via] + [p1]
    elif s0 in "LR" and s1 in "LR":
        if abs(p0[1] - p1[1]) < 0.5:
            pts = [p0, p1]
        else:
            d = 1 if p1[0] >= p0[0] else -1
            mx = p1[0] - d * lane if lane is not None else (p0[0] + p1[0]) / 2
            pts = [p0, (mx, p0[1]), (mx, p1[1]), p1]
    elif s0 in "TB" and s1 in "TB":
        if abs(p0[0] - p1[0]) < 0.5:
            pts = [p0, p1]
        else:
            d = 1 if p1[1] >= p0[1] else -1
            my = p1[1] - d * lane if lane is not None else (p0[1] + p1[1]) / 2
            pts = [p0, (p0[0], my), (p1[0], my), p1]
    elif s0 in "LR":
        pts = [p0, (p1[0], p0[1]), p1]
    else:
        pts = [p0, (p0[0], p1[1]), p1]
    return _clean(pts)


_OUT = {"R": (1, 0), "L": (-1, 0), "B": (0, 1), "T": (0, -1)}


def _direction_ok(pts, s0, s1):
    def unit(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        return (0 if abs(dx) < 0.01 else int(math.copysign(1, dx)),
                0 if abs(dy) < 0.01 else int(math.copysign(1, dy)))
    first = unit(pts[0], pts[1])
    last = unit(pts[-2], pts[-1])
    into = _OUT[s1]
    return first == _OUT[s0] and last == (-into[0], -into[1])


def _segments(pts):
    return [(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            for a, b in zip(pts, pts[1:])]


def _seg_len(s):
    return (s[2] - s[0]) + (s[3] - s[1])


def _place_label(pts, text):
    """Centre a chip on the segment with the most spare room, clear of corners and the arrowhead."""
    cw = text_width(text, LABEL_SIZE) + 16
    segs = _segments(pts)
    best = None
    for i, s in enumerate(segs):
        horizontal = abs(s[1] - s[3]) < 0.01
        need = (cw if horizontal else CHIP_H) + 8
        usable = _seg_len(s) - need - (ARROW if i == len(segs) - 1 else 0)
        if best is None or usable > best[0]:
            best = (usable, i, horizontal)
    usable, i, horizontal = best
    if usable < 0:
        return None
    s = segs[i]
    half = (cw if horizontal else CHIP_H) / 2 + 4
    lo = (s[0] if horizontal else s[1]) + half
    hi = (s[2] if horizontal else s[3]) - half - (ARROW if i == len(segs) - 1 else 0)
    centre = (lo + hi) / 2
    cx, cy = (centre, s[1]) if horizontal else (s[0], centre)
    return cx - cw / 2, cy - CHIP_H / 2, cw, CHIP_H


def render(spec):
    flows = spec["flows"]
    nodes = _layout(spec)
    edges = []
    for raw in spec["edges"]:
        a, b = raw["from"], raw["to"]
        for ref in (a[0], b[0]):
            if ref not in nodes:
                raise SpecError(f"edge refers to unknown node {ref}")
        if raw.get("flow") not in flows:
            raise SpecError(f"edge {a[0]}>{b[0]}: unknown flow {raw.get('flow')!r}")
        if not str(raw.get("evidence", "")).strip():
            raise SpecError(f"edge {a[0]}>{b[0]}: no evidence; cite the package lines that establish it")
        if not str(raw.get("label", "")).strip():
            raise SpecError(f"edge {a[0]}>{b[0]}: every connector needs a label")
        na, nb = nodes[a[0]], nodes[b[0]]
        if a[2] == "match":
            p1 = _anchor(nb, b[1], b[2])
            p0 = _anchor(na, a[1], a[2], p1)
        else:
            p0 = _anchor(na, a[1], a[2])
            p1 = _anchor(nb, b[1], b[2], p0)
        pts = _route(p0, a[1], p1, b[1], raw.get("via"), raw.get("lane"))
        if len(pts) < 2 or not _direction_ok(pts, a[1], b[1]):
            raise SpecError(f"edge {a[0]}>{b[0]}: route does not leave side {a[1]} / enter side {b[1]} "
                            "straight; give 'via' points")
        chip = _place_label(pts, raw["label"])
        if chip is None:
            raise SpecError(f"edge {a[0]}>{b[0]}: no segment is long enough for the label "
                            f"{raw['label']!r}; widen the gap or shorten the label")
        edges.append({"id": raw.get("id") or f"{a[0]}>{b[0]}", "from": a[0], "to": b[0],
                      "s0": a[1], "s1": b[1], "pts": pts, "chip": chip, "flow": raw["flow"],
                      "label": raw["label"], "evidence": raw["evidence"]})
    ids = [e["id"] for e in edges]
    if len(set(ids)) != len(ids):
        raise SpecError("duplicate edge ids; give 'id' to parallel edges")

    used = [k for k in flows if any(e["flow"] == k for e in edges)]
    legend_w = 24 + sum(54 + 10 + text_width(flows[k]["label"], TEXT_SIZE) + 34 for k in used)
    width = math.ceil(max(max(n["x"] + n["w"] for n in nodes.values()), MARGIN + legend_w) + MARGIN)
    height = math.ceil(max(n["y"] + n["h"] for n in nodes.values()) + MARGIN)
    title = spec["title"]

    def colour(key):
        return flows[key]["color"]

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="t d">',
           f'<title id="t">{escape(title)}</title>',
           '<desc id="d">' + escape("Data lineage. " + " ".join(
               f"{e['from']} to {e['to']} ({e['label']}; {e['evidence']})." for e in edges)) + '</desc>',
           '<defs>']
    for c in sorted({colour(e["flow"]) for e in edges}):
        out.append(f'<marker id="m-{c[1:]}" markerWidth="10" markerHeight="8" refX="10" refY="4" '
                   f'orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,4 L0,8 z" fill="{c}"/></marker>')
    out.append('</defs>')
    out.append(f'<rect width="{width}" height="{height}" fill="{BG}"/>')
    out.append(f'<text data-role="title" x="{width / 2:.0f}" y="40" text-anchor="middle" font-family="{FONT}" '
               f'font-size="26" font-weight="700" fill="#0F172A">{escape(title)}</text>')

    # legend with arrow samples in each flow's colour and line style
    out.append(f'<g class="legend"><rect x="{MARGIN}" y="62" width="{width - 2 * MARGIN}" height="52" rx="10" '
               'fill="#FFFFFF" stroke="#CBD5E1"/>')
    x = MARGIN + 24
    for k in used:
        c, dotted = colour(k), flows[k].get("style") == "control"
        dash = ' stroke-dasharray="1 6" stroke-linecap="round"' if dotted else ""
        out.append(f'<g data-legend-flow={quoteattr(k)} data-legend-color="{c}" '
                   f'data-legend-style="{"control" if dotted else "data"}">'
                   f'<path d="M{x:g} 88 L{x + 54:g} 88" stroke="{c}" stroke-width="2.4" fill="none"{dash} '
                   f'marker-end="url(#m-{c[1:]})"/>'
                   f'<text x="{x + 64:g}" y="93" font-family="{FONT}" font-size="{TEXT_SIZE}" fill="{TEXT}">'
                   f'{escape(flows[k]["label"])}</text></g>')
        x += 54 + 10 + text_width(flows[k]["label"], TEXT_SIZE) + 34
    out.append('</g>')

    for n in nodes.values():
        kind = n.get("kind", "step")
        key = n.get("flow")
        base = colour(key) if key else "#94A3B8"
        fill = "#FFFFFF" if kind == "note" else _mix(base, 0.90)
        sw = 3 if kind in ("source", "target") else 2
        out.append(f'<g class="node" data-node={quoteattr(n["id"])} data-kind="{kind}">'
                   f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" rx="12" '
                   f'fill="{fill}" stroke="{base}" stroke-width="{sw}"/>'
                   f'<text x="{n["x"] + PAD_X}" y="{n["y"] + 28}" font-family="{FONT}" font-size="{TITLE_SIZE}" '
                   f'font-weight="700" fill="{_darken(base, 0.45)}">{escape(n["title"])}</text>')
        for i, line in enumerate(n.get("lines", [])):
            weight = ' font-weight="700"' if line.startswith("# ") else ""
            out.append(f'<text x="{n["x"] + PAD_X}" y="{n["y"] + 54 + 22 * i}" font-family="{FONT}" '
                       f'font-size="{TEXT_SIZE}"{weight} fill="{TEXT}">{escape(_plain(line))}</text>')
        out.append('</g>')

    for e in edges:
        c = colour(e["flow"])
        dotted = flows[e["flow"]].get("style") == "control"
        d = "M" + " L".join(f"{x:g} {y:g}" for x, y in e["pts"])
        dash = ' stroke-dasharray="1 6" stroke-linecap="round"' if dotted else ""
        out.append(f'<g class="edge" data-edge={quoteattr(e["id"])} data-from={quoteattr(e["from"])} '
                   f'data-to={quoteattr(e["to"])} data-from-side="{e["s0"]}" data-to-side="{e["s1"]}" '
                   f'data-color="{c}" data-style="{"control" if dotted else "data"}" '
                   f'data-evidence={quoteattr(e["evidence"])}>'
                   f'<path d="{d}" fill="none" stroke="{c}" stroke-width="2.4" stroke-linejoin="round"{dash} '
                   f'marker-end="url(#m-{c[1:]})"/></g>')
    for e in edges:
        c = colour(e["flow"])
        x, y, w, h = e["chip"]
        out.append(f'<g class="label" data-label-for={quoteattr(e["id"])}>'
                   f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h}" rx="5" fill="#FFFFFF" stroke="{c}"/>'
                   f'<text x="{x + w / 2:g}" y="{y + 14:g}" text-anchor="middle" font-family="{FONT}" '
                   f'font-size="{LABEL_SIZE}" fill="{_darken(c, 0.35)}">{escape(e["label"])}</text></g>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- check

def _tag(el):
    return el.tag.rsplit("}", 1)[-1]


def _kids(el, name):
    return [k for k in el.iter() if _tag(k) == name]


def _num(el, attr, default=0.0):
    return float(el.get(attr, default))


def _text_box(t):
    size = _num(t, "font-size", TEXT_SIZE)
    bold = t.get("font-weight") in ("700", "bold")
    w = text_width("".join(t.itertext()), size, bold)
    x, y = _num(t, "x"), _num(t, "y")
    if t.get("text-anchor") == "middle":
        x -= w / 2
    return (x, y - 0.78 * size, x + w, y + 0.22 * size)


def _overlap(a, b, m=0.0):
    return a[0] < b[2] + m and a[2] > b[0] - m and a[1] < b[3] + m and a[3] > b[1] - m


def _inside(inner, outer, mx, my):
    return (inner[0] >= outer[0] + mx and inner[2] <= outer[2] - mx and
            inner[1] >= outer[1] + my and inner[3] <= outer[3] - my)


def _rect_box(r):
    return (_num(r, "x"), _num(r, "y"), _num(r, "x") + _num(r, "width"), _num(r, "y") + _num(r, "height"))


def _parse_path(d):
    nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+", d)]
    return list(zip(nums[0::2], nums[1::2]))


def check_svg(path, package=None):
    """Return (findings, warnings) for the diagram in *path*."""
    root = ET.parse(path).getroot()
    findings, warnings = [], []
    vb = [float(v) for v in root.get("viewBox", "0 0 0 0").split()]
    canvas = (vb[0], vb[1], vb[0] + vb[2], vb[1] + vb[3])

    nodes, edges, chips, legend = {}, {}, {}, set()
    title_el = None
    for g in _kids(root, "g"):
        cls = g.get("class")
        if cls == "node":
            nodes[g.get("data-node")] = {"box": _rect_box(_kids(g, "rect")[0]), "kind": g.get("data-kind"),
                                         "texts": _kids(g, "text")}
        elif cls == "edge":
            edges[g.get("data-edge")] = {
                "pts": _parse_path(_kids(g, "path")[0].get("d")), "from": g.get("data-from"),
                "to": g.get("data-to"), "s0": g.get("data-from-side"), "s1": g.get("data-to-side"),
                "color": g.get("data-color"), "style": g.get("data-style"), "evidence": g.get("data-evidence", "")}
        elif cls == "label":
            chips[g.get("data-label-for")] = {"box": _rect_box(_kids(g, "rect")[0]), "text": _kids(g, "text")[0]}
        elif g.get("data-legend-color"):
            legend.add((g.get("data-legend-color"), g.get("data-legend-style")))
    for t in _kids(root, "text"):
        if t.get("data-role") == "title":
            title_el = t
    if package:
        if not any("".join(k.itertext()) == package for k in _kids(root, "title")):
            findings.append(f"title element is not {package}")
        if title_el is None or "".join(title_el.itertext()) != package:
            findings.append(f"visible title is not the full package name {package}")

    for nid, n in nodes.items():
        for t in n["texts"]:
            if not _inside(_text_box(t), n["box"], TEXT_MARGIN_X, TEXT_MARGIN_Y):
                findings.append(f"node {nid}: text {''.join(t.itertext())!r} is not fully inside the box "
                                f"with a {TEXT_MARGIN_X} unit margin")
        title = "".join(n["texts"][0].itertext())
        if n["kind"] != "note" and re.match(r"^[A-Z][A-Z0-9_$#]*\.[A-Z]", title):
            findings.append(f"node {nid}: title {title!r} carries a schema qualifier")
        if not _inside(n["box"], canvas, 0, 0):
            findings.append(f"node {nid} lies outside the canvas")

    connected = {frozenset((e["from"], e["to"])) for e in edges.values()}
    names = list(nodes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ba, bb = nodes[a]["box"], nodes[b]["box"]
            dx = max(0, ba[0] - bb[2], bb[0] - ba[2])
            dy = max(0, ba[1] - bb[3], bb[1] - ba[3])
            if dx == 0 and dy == 0:
                findings.append(f"nodes {a} and {b} overlap")
            elif frozenset((a, b)) in connected:
                if max(dx, dy) < MIN_GAP:
                    findings.append(f"connected nodes {a} and {b} are {max(dx, dy):.0f} apart; need {MIN_GAP}")
            elif (dx == 0 and dy < MIN_STACK_GAP) or (dy == 0 and dx < MIN_STACK_GAP):
                findings.append(f"nodes {a} and {b} are {max(dx, dy):.0f} apart; need {MIN_STACK_GAP}")

    seg = {}
    for eid, e in edges.items():
        pts = e["pts"]
        if len(pts) < 2 or e["from"] not in nodes or e["to"] not in nodes:
            findings.append(f"edge {eid} has no route or an unknown endpoint")
            continue
        for a, b in zip(pts, pts[1:]):
            if abs(a[0] - b[0]) > 0.01 and abs(a[1] - b[1]) > 0.01:
                findings.append(f"edge {eid} has a diagonal segment")
        seg[eid] = _segments(pts)
        if not re.search(r"L\d+", e["evidence"]):
            findings.append(f"edge {eid} cites no package line (evidence {e['evidence']!r})")
        if not _direction_ok(pts, e["s0"], e["s1"]):
            findings.append(f"edge {eid} does not leave/enter its box sides straight")
        if _seg_len(seg[eid][-1]) < ARROW + 14:
            findings.append(f"edge {eid}: final segment too short for an arrowhead")
        if eid not in chips:
            findings.append(f"edge {eid} has no label")
        last = len(seg[eid]) - 1
        for nid, n in nodes.items():
            endpoint = nid in (e["from"], e["to"])
            for k, s in enumerate(seg[eid]):
                if endpoint and k in (0, last):
                    inner = (n["box"][0] + 1, n["box"][1] + 1, n["box"][2] - 1, n["box"][3] - 1)
                    if _overlap(s, inner):
                        findings.append(f"edge {eid} runs inside its own endpoint {nid}")
                elif _overlap(s, n["box"], NODE_BORDER_CLEAR):
                    findings.append(f"edge {eid} passes through or within {NODE_BORDER_CLEAR} units of node {nid}")
                    break
            for t in n["texts"]:
                if any(_overlap(s, _text_box(t), 2) for s in seg[eid]):
                    findings.append(f"edge {eid} touches text {''.join(t.itertext())!r} of node {nid}")

    eids = list(seg)
    for i, ea in enumerate(eids):
        for eb in eids[i + 1:]:
            for sa in seg[ea]:
                for sb in seg[eb]:
                    ha, hb = abs(sa[1] - sa[3]) < 0.01, abs(sb[1] - sb[3]) < 0.01
                    if ha == hb:
                        lo, hi, fixed = (0, 2, 1) if ha else (1, 3, 0)
                        near = abs(sa[fixed] - sb[fixed])
                        extent = min(sa[hi], sb[hi]) - max(sa[lo], sb[lo])
                        if extent > 0 and near < LANE_SPACING:
                            findings.append(f"edges {ea} and {eb} overlap or run closer than "
                                            f"{LANE_SPACING} units ({near:.0f})")
                        continue
                    h, v = (sa, sb) if ha else (sb, sa)
                    x, y = v[0], h[1]
                    if h[0] <= x <= h[2] and v[1] <= y <= v[3]:
                        interior = h[0] + 1 < x < h[2] - 1 and v[1] + 1 < y < v[3] - 1
                        ends = [edges[ea]["pts"][-1], edges[eb]["pts"][-1]]
                        if not interior:
                            findings.append(f"edges {ea} and {eb} meet at ({x:.0f}, {y:.0f}) without a clear crossing")
                        elif any(math.dist((x, y), p) < ARROW + 10 for p in ends):
                            findings.append(f"edges {ea} and {eb} cross next to an arrowhead")
                        else:
                            warnings.append(f"edges {ea} and {eb} cross at ({x:.0f}, {y:.0f})")

    anchors = {}
    for eid, e in edges.items():
        if len(e["pts"]) < 2:
            continue
        anchors.setdefault((e["from"], e["s0"]), []).append((eid, e["pts"][0]))
        anchors.setdefault((e["to"], e["s1"]), []).append((eid, e["pts"][-1]))
    for (node, side), items in anchors.items():
        for i, (ea, pa) in enumerate(items):
            for eb, pb in items[i + 1:]:
                if math.dist(pa, pb) < ANCHOR_SPACING:
                    findings.append(f"edges {ea} and {eb} attach to {node} side {side} only "
                                    f"{math.dist(pa, pb):.0f} apart; need {ANCHOR_SPACING}")

    for eid, c in chips.items():
        if eid not in edges:
            findings.append(f"label for unknown edge {eid}")
            continue
        box = c["box"]
        if not _inside(_text_box(c["text"]), box, 5, 2):
            findings.append(f"label of {eid}: text does not fit its chip")
        for nid, n in nodes.items():
            if _overlap(box, n["box"], 4):
                findings.append(f"label of {eid} touches node {nid}")
        for other, s in seg.items():
            if other != eid and any(_overlap(box, x, 3) for x in s):
                findings.append(f"label of {eid} touches connector {other}")
        own = seg.get(eid, [])
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if own and not any(s[0] - 1 <= cx <= s[2] + 1 and s[1] - 1 <= cy <= s[3] + 1 for s in own):
            findings.append(f"label of {eid} is not on its connector")
        if own:
            tip = edges[eid]["pts"][-1]
            if _overlap(box, (tip[0] - ARROW, tip[1] - ARROW, tip[0] + ARROW, tip[1] + ARROW)):
                findings.append(f"label of {eid} covers its arrowhead")
        if not _inside(box, canvas, 0, 0):
            findings.append(f"label of {eid} lies outside the canvas")
        for other, o in chips.items():
            if other < eid and _overlap(box, o["box"], 2):
                findings.append(f"labels of {eid} and {other} overlap")

    for nid, n in nodes.items():
        ins = [e for e in edges.values() if e["to"] == nid and e["style"] == "data"]
        outs = [e for e in edges.values() if e["from"] == nid and e["style"] == "data"]
        ctl = [e for e in edges.values() if nid in (e["from"], e["to"]) and e["style"] == "control"]
        kind = n["kind"]
        if kind == "source" and not outs:
            findings.append(f"source {nid} has no outgoing data connector")
        elif kind == "step" and (not ins or not outs):
            findings.append(f"step {nid} is a dead end: it needs an incoming and an outgoing data connector "
                            "(a guard that only raises errors is a note, not a step)")
        elif kind == "target" and not ins:
            findings.append(f"target {nid} has no incoming data connector")
        elif kind == "control" and not ctl:
            findings.append(f"control node {nid} has no control connector")
        elif kind == "note" and (ins or outs or ctl):
            findings.append(f"note {nid} must not carry connectors")

    for item in {(e["color"], e["style"]) for e in edges.values()} - legend:
        findings.append(f"colour {item[0]} ({item[1]}) is not named in the legend")
    colours = sorted({e["color"] for e in edges.values()})
    for c in colours:
        for bg in ("#FFFFFF", DARK_BG):
            if contrast(c, bg) < 3.0:
                findings.append(f"colour {c} has contrast {contrast(c, bg):.1f} on {bg}; need 3.0")
    for i, a in enumerate(colours):
        for b in colours[i + 1:]:
            if color_distance(a, b) < 30:
                findings.append(f"colours {a} and {b} are too close ({color_distance(a, b):.0f}; need 30)")
            for vision in _CVD:
                if color_distance(a, b, vision) < 14:
                    findings.append(f"colours {a} and {b} are hard to tell apart with {vision} "
                                    f"({color_distance(a, b, vision):.0f}; need 14)")
    return findings, warnings


def _report(findings, warnings):
    for w in warnings:
        print("warning:", w)
    for f in findings:
        print("DEFECT:", f)
    print(f"{len(findings)} defect(s), {len(warnings)} warning(s)")
    return 1 if findings else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("spec")
    r.add_argument("svg")
    c = sub.add_parser("check")
    c.add_argument("svg")
    for p in (r, c):
        p.add_argument("--package", help="the full package name the title must show")
    args = ap.parse_args(argv)
    if args.cmd == "render":
        with open(args.spec, encoding="utf-8") as f:
            spec = json.load(f)
        try:
            svg = render(spec)
        except SpecError as exc:
            print("SPEC ERROR:", exc)
            return 2
        with open(args.svg, "w", encoding="utf-8", newline="\n") as f:
            f.write(svg)
        print("wrote", args.svg)
        return _report(*check_svg(args.svg, args.package or spec["title"]))
    return _report(*check_svg(args.svg, args.package))


if __name__ == "__main__":
    sys.exit(main())
