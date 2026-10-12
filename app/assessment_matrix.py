"""Assessment Matrix document → HTML (§78, owner request).

`corrections/Assessment_Matrix.docx` — "NEW PATTERN DISCOVERY: IMPACT ON
SUSTAINABLE SOCIETY / ASSESSMENT MATRIX" — is the scoring law behind the New
Patterns workspace (impact dimensions, level bands, the coupled bell curve).
Owner directive: containerise it — render the document's full content
(headings, paragraphs, all tables, and the embedded figure) as HTML inside
the New Patterns workspace instead of leaving it as a raw docx.

Design:
- Pure-stdlib docx parsing: a .docx is a zip of XML (word/document.xml),
  so we walk headings, paragraphs, tables and the embedded image without
  adding python-docx as a new dependency.
- Cached render keyed on the source file's mtime + size, so repeated page
  loads are instant; the render is regenerated only when the document
  changes on disk.
"""

from __future__ import annotations

import base64
import html
import io
import re
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from xml.etree import ElementTree as ET

ASSESSMENT_DOCX_RELATIVE = Path("corrections") / "Assessment_Matrix.docx"

_WORDML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_W = f"{{{_WORDML_NS}}}"
_R = f"{{{_REL_NS}}}"

_IMAGE_MEDIA_TYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".emf": "image/emf",
    ".wmf": "image/wmf",
}

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"key": None, "html": None, "stats": {}}


def assessment_docx_path(project_root: Path) -> Path:
    return Path(project_root) / ASSESSMENT_DOCX_RELATIVE


# ---------------------------------------------------------------------------
# Low-level docx XML helpers (stdlib only)
# ---------------------------------------------------------------------------


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _paragraph_heading_level(paragraph: ET.Element) -> int:
    """1-6 for real heading styles; 0 when the paragraph is body text."""
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    if style is None:
        return 0
    value = (style.get(f"{_W}val") or "").strip()
    match = re.fullmatch(r"[Hh]eading([1-9])", value)
    if match:
        return int(match.group(1))
    if value.lower() in {"title"}:
        return 1
    if value.lower() in {"subtitle"}:
        return 2
    return 0


_CODE_LANG_RE = re.compile(r"^#{1,4}\\s*(javascript|js|python|py|jsx|vue|html|css|json|bash|shell)\\s*$", re.IGNORECASE)
_CODE_HINT_RE = re.compile(r"^(export |const |import |def |class |function |from |return |</?[a-z]|<template|<script|npm |pip |vue |Use Chart|Save the following)")


def _paragraph_is_bold(paragraph: ET.Element) -> bool:
    """True when every run carrying text is bold (this docx styles its
    headings with direct formatting, no Heading styles)."""
    runs = paragraph.findall(f"{_W}r")
    text_runs = 0
    for run in runs:
        has_text = any((t.text or "").strip() for t in run.findall(f"{_W}t"))
        if not has_text:
            continue
        text_runs += 1
        if run.find(f"{_W}rPr/{_W}b") is None:
            return False
    return text_runs > 0


def _classify_paragraph(paragraph: ET.Element, text: str) -> str:
    """Return the block kind: 'h1', 'h2', 'code', 'li' or 'p'.

    The Assessment Matrix docx uses direct bold formatting instead of Word
    heading styles, so headings are detected as: bold-only paragraphs that
    are short and are not code lines. Code lines (the embedded JS/Python
    samples) render in a monospace block to keep the document readable.
    """
    style_level = _paragraph_heading_level(paragraph)
    if style_level:
        return f"h{min(style_level, 6)}"
    if _CODE_LANG_RE.match(text):
        return "code"
    if _CODE_HINT_RE.match(text) or (text.startswith(('"', "'", '{', '}', '<', '[', ']')) and len(text) < 200):
        return "code"
    if _paragraph_is_bold(paragraph):
        stripped = text.strip().rstrip(':')
        if len(stripped) <= 90 and not stripped.endswith('.'):
            # The document title deserves h1; everything else is a section heading.
            if stripped.upper() == "ASSESSMENT MATRIX":
                return "h1"
            return "h2"
        return "p"
    return "p"


def _paragraph_is_list_item(paragraph: ET.Element) -> str | None:
    """'ul' / 'ol' when the paragraph carries numbering, else None."""
    num_pr = paragraph.find(f"{_W}pPr/{_W}numPr")
    if num_pr is None:
        return None
    ilvl = num_pr.find(f"{_W}ilvl")
    level = int(ilvl.get(f"{_W}val") or "0") if ilvl is not None else 0
    # Word bullet lists at level 0 are unordered; numbered styles are handled
    # per-style below. Keep it simple: level 0 → ul, deeper → nested ul.
    return "ul"


def _cell_paragraphs(cell: ET.Element) -> list[str]:
    out: list[str] = []
    for paragraph in cell.findall(f"{_W}p"):
        text = _paragraph_text(paragraph)
        if text:
            out.append(text)
    return out or [""]


def _table_rows(table: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.findall(f"{_W}tr"):
        cells = [_cell_paragraphs(tc) for tc in tr.findall(f"{_W}tc")]
        if cells:
            rows.append(cells)
    return rows


def _iter_block_items(body: ET.Element):
    """Yield (kind, element) in document order: 'p' paragraphs and 'tbl' tables."""
    for child in body:
        if child.tag == f"{_W}p":
            yield "p", child
        elif child.tag == f"{_W}tbl":
            yield "tbl", child


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------


def _load_relationships(zip_handle: zipfile.ZipFile) -> dict[str, str]:
    """rId → media path (e.g. 'rId7' → 'word/media/image1.png')."""
    mapping: dict[str, str] = {}
    try:
        rels_xml = zip_handle.read("word/_rels/document.xml.rels")
    except KeyError:
        return mapping
    root = ET.fromstring(rels_xml)
    for rel in root.findall(f"{{{_PKG_REL_NS}}}Relationship"):
        rid = rel.get("Id") or ""
        target = rel.get("Target") or ""
        if rid and "media/" in target:
            mapping[rid] = target if target.startswith("word/") else f"word/{target.lstrip('/')}"
    return mapping


def _image_data_uri(zip_handle: zipfile.ZipFile, media_path: str) -> str:
    suffix = Path(media_path).suffix.lower()
    media_type = _IMAGE_MEDIA_TYPE.get(suffix, "application/octet-stream")
    data = zip_handle.read(media_path)
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


# ---------------------------------------------------------------------------
# Document + Interactive Simulator → HTML
# ---------------------------------------------------------------------------

_DOC_CSS = """
  body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #f1f5f9; color: #1e293b; }
  .doc-shell { max-width: 1080px; margin: 0 auto; padding: 26px 30px 60px; background: #fff; min-height: 100vh; box-shadow: 0 0 24px rgba(15,23,42,0.08); }
  h1 { font-size: 24px; margin: 18px 0 8px; color: #0f172a; }
  h2 { font-size: 19px; margin: 20px 0 8px; color: #1e293b; border-left: 4px solid #4f46e5; padding-left: 10px; }
  h3 { font-size: 16px; margin: 16px 0 6px; color: #1e293b; }
  h4 { font-size: 14px; margin: 14px 0 5px; color: #334155; }
  p { font-size: 13.5px; line-height: 1.65; margin: 8px 0; color: #334155; }
  ul, ol { font-size: 13.5px; line-height: 1.6; margin: 8px 0 8px 22px; padding: 0; }
  li { margin: 4px 0; }
  table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 12.5px; }
  th, td { border: 1px solid #cbd5e1; padding: 7px 10px; text-align: left; vertical-align: top; line-height: 1.5; }
  th { background: #f1f5f9; color: #0f172a; font-weight: 700; }
  tr:nth-child(even) td { background: #f8fafc; }
  figure { margin: 18px 0; text-align: center; }
  figure img { max-width: 100%; height: auto; border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; }
  .doc-meta { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; font-size: 12px; color: #64748b; border-bottom: 1px solid #e2e8f0; padding-bottom: 12px; margin-bottom: 16px; }
  .doc-back { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: #4f46e5; text-decoration: none; font-weight: 700; background: #eef2ff; border: 1px solid #c7d2fe; padding: 6px 12px; border-radius: 8px; }
  .doc-back:hover { background: #e0e7ff; }
  .sim-card { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 14px; padding: 20px 22px; margin-bottom: 24px; }
  .sim-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
  .sim-select { padding: 8px 12px; border-radius: 8px; border: 1px solid #94a3b8; font: inherit; font-size: 13px; background: #fff; color: #0f172a; min-width: 280px; }
  .sim-grid { display: grid; grid-template-columns: 340px 1fr; gap: 20px; align-items: start; }
  @media (max-width: 860px) { .sim-grid { grid-template-columns: 1fr; } }
  .slider-row { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 8px 12px; margin-bottom: 8px; }
  .slider-top { display: flex; justify-content: space-between; font-size: 12px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
  .slider-top span.val { font-family: Consolas, monospace; color: #4f46e5; }
  .slider-row input[type=range] { width: 100%; accent-color: #4f46e5; cursor: pointer; }
  .slider-sub { display: flex; justify-content: space-between; font-size: 11px; color: #64748b; font-family: Consolas, monospace; }
  .nsis-banner { display: flex; justify-content: space-between; align-items: center; background: #0f172a; color: #f8fafc; padding: 12px 16px; border-radius: 10px; margin-bottom: 12px; font-size: 13px; }
  .nsis-banner b { font-family: Consolas, monospace; font-size: 18px; color: #38bdf8; }
  .chart-wrap { position: relative; height: 340px; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; }
  .band-pill { font-size: 10.5px; font-weight: 700; padding: 2px 7px; border-radius: 999px; }
  .b-l3 { background: #dcfce7; color: #166534; }
  .b-l2 { background: #fef3c7; color: #92400e; }
  .b-l1 { background: #f1f5f9; color: #475569; }
"""


def _build_interactive_simulator_html() -> str:
    """Build the live interactive 7-dimension Coupled Bell-Curve Assessment Matrix Simulator."""
    import json
    from .assessment_math import DIMENSIONS, evaluate_pattern_matrix
    from .pattern_store import get_pattern_graph, list_patterns

    presets: list[dict[str, Any]] = []
    try:
        rows = list_patterns(status="", limit=40)
        for r in rows[:25]:
            pid = int(r.get("id") or 0)
            g = get_pattern_graph(pid) if pid else {"relations": []}
            rels = g.get("relations") or []
            n_ent = len({(x.get("source_name"), x.get("source_type")) for x in rels} | {(x.get("target_name"), x.get("target_type")) for x in rels})
            ev = evaluate_pattern_matrix(r, graph={"entities": n_ent, "relations": len(rels)})
            presets.append(
                {
                    "id": pid,
                    "title": f"#{pid} — {str(r.get('title') or 'Untitled Pattern')[:68]}",
                    "x_levels": ev.get("x_levels") or {},
                    "nsis": ev.get("nsis") or 0.0,
                }
            )
    except Exception:
        pass

    presets_json = json.dumps(presets, ensure_ascii=False)
    options_html = '<option value="custom">Custom Interactive Simulation (Manual Sliders)</option>' + "".join(
        f'<option value="{p["id"]}" {"selected" if idx == 0 else ""}>{html.escape(p["title"])}</option>'
        for idx, p in enumerate(presets)
    )

    sliders_html = "".join(
        f"""
        <div class="slider-row" data-dim="{d}">
          <div class="slider-top">
            <span>{d}</span>
            <span class="val" id="val-{d.replace(' ', '_')}">5.00</span>
          </div>
          <input type="range" min="0" max="10" step="0.1" value="5.0" id="sl-{d.replace(' ', '_')}" data-dim="{d}">
          <div class="slider-sub">
            <span id="param-{d.replace(' ', '_')}">&mu;=5.0 &sigma;=1.5 A=1.0</span>
            <span id="sd-{d.replace(' ', '_')}">SD: 14.3%</span>
          </div>
        </div>
        """
        for d in DIMENSIONS
    )

    return f"""
    <section class="sim-card" id="interactive-simulator">
      <div class="sim-head">
        <div>
          <div style="font-size:11px;font-weight:800;letter-spacing:1.2px;text-transform:uppercase;color:#4f46e5;">Interactive Coupled Gaussian Engine</div>
          <h2 style="margin:4px 0 0;border:0;padding:0;">Live Assessment Matrix &amp; Coupled Bell-Curve Simulator</h2>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <label for="simPatternSelect" style="font-size:12px;font-weight:700;color:#475569;">Load Pattern Profile:</label>
          <select id="simPatternSelect" class="sim-select">{options_html}</select>
        </div>
      </div>
      <div class="sim-grid">
        <div>
          <div class="nsis-banner">
            <div>
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;">Net Sustainable Impact Score</div>
              <div style="font-size:12px;color:#cbd5e1;">Coupled Rules A, B &amp; C Active</div>
            </div>
            <b id="simNsisVal">0.0000</b>
          </div>
          {sliders_html}
        </div>
        <div>
          <div class="chart-wrap">
            <canvas id="simCurveCanvas"></canvas>
          </div>
          <table style="margin-top:12px;">
            <thead>
              <tr>
                <th>Dimension</th>
                <th>x<sub>i</sub></th>
                <th>&mu;<sub>i</sub></th>
                <th>&sigma;<sub>i</sub></th>
                <th>A<sub>i</sub></th>
                <th>S<sub>i</sub>(x)</th>
                <th>W<sub>i</sub></th>
                <th>SD<sub>i</sub>(%)</th>
                <th>Band</th>
              </tr>
            </thead>
            <tbody id="simMatrixTbody"></tbody>
          </table>
        </div>
      </div>
    </section>
    <script id="simPresetsData" type="application/json">{presets_json}</script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script>
    (() => {{
      const DIMS = ["Knowledge", "Societal", "Scientific", "Decision", "Intelligence", "Human Agency", "Risk"];
      const WEIGHTS = {{ "Knowledge": 0.14, "Societal": 0.16, "Scientific": 0.14, "Decision": 0.14, "Intelligence": 0.12, "Human Agency": 0.15, "Risk": 0.15 }};
      const BASE = {{
        "Knowledge":    {{ mu: 6.5, sigma: 1.8, A: 1.0 }},
        "Societal":     {{ mu: 6.0, sigma: 1.6, A: 1.0 }},
        "Scientific":   {{ mu: 7.0, sigma: 1.5, A: 1.0 }},
        "Decision":     {{ mu: 6.0, sigma: 1.5, A: 1.0 }},
        "Intelligence": {{ mu: 6.5, sigma: 1.7, A: 1.0 }},
        "Human Agency": {{ mu: 5.5, sigma: 1.4, A: 1.0 }},
        "Risk":         {{ mu: 3.0, sigma: 1.2, A: 1.0 }},
      }};
      const COLORS = ["#4f46e5", "#0891b2", "#b45309", "#be185d", "#15803d", "#7c3aed", "#dc2626"];
      const presets = JSON.parse(document.getElementById("simPresetsData").textContent || "[]");

      function clamp(v, lo, hi) {{ return Math.max(lo, Math.min(hi, v)); }}
      function gauss(x, mu, sigma, A) {{
        const s = Math.max(sigma, 0.25);
        return A * Math.exp(-Math.pow(x - mu, 2) / (2 * s * s));
      }}
      function bandFor(x) {{
        if (x < 3.5) return ["Level 1 — Local / Narrow", "b-l1"];
        if (x < 7.0) return ["Level 2 — Cross-Field", "b-l2"];
        return ["Level 3 — Paradigm Shift", "b-l3"];
      }}

      let chart = null;

      function computeAndRender() {{
        const x = {{}};
        DIMS.forEach(d => {{
          const el = document.getElementById("sl-" + d.replace(" ", "_"));
          x[d] = el ? parseFloat(el.value) || 0 : 5.0;
        }});

        const dyn = {{}};
        DIMS.forEach(d => {{ dyn[d] = {{ ...BASE[d] }}; }});

        // Rule A: Intelligence -> Human Agency
        const deltaIntel = Math.max(0, x["Intelligence"] - 5.0);
        dyn["Human Agency"].sigma = clamp(BASE["Human Agency"].sigma - 0.12 * deltaIntel, 0.55, 2.5);
        dyn["Human Agency"].mu = clamp(BASE["Human Agency"].mu + 0.18 * deltaIntel, 1.0, 9.5);

        // Rule B: Risk -> Societal & Decision
        const deltaRisk = Math.max(0, x["Risk"] - 3.0);
        dyn["Societal"].sigma = clamp(BASE["Societal"].sigma + 0.22 * deltaRisk, 0.6, 3.4);
        dyn["Societal"].A = clamp(BASE["Societal"].A - 0.06 * deltaRisk, 0.35, 1.2);
        dyn["Decision"].mu = clamp(BASE["Decision"].mu - 0.20 * deltaRisk, 1.0, 9.0);

        // Rule C: Scientific -> Knowledge
        const deltaSci = Math.max(0, x["Scientific"] - 5.0);
        dyn["Knowledge"].A = clamp(BASE["Knowledge"].A + 0.05 * deltaSci, 0.5, 1.35);

        const s = {{}};
        let nsis = 0;
        DIMS.forEach(d => {{
          s[d] = gauss(x[d], dyn[d].mu, dyn[d].sigma, dyn[d].A);
          if (d === "Risk") {{
            nsis -= WEIGHTS[d] * (1.0 - s[d]);
          }} else {{
            nsis += WEIGHTS[d] * s[d];
          }}
        }});

        const posSum = DIMS.reduce((acc, d) => acc + WEIGHTS[d] * s[d], 0) || 1e-9;
        const sd = {{}};
        DIMS.forEach(d => {{ sd[d] = (WEIGHTS[d] * s[d] / posSum) * 100.0; }});

        document.getElementById("simNsisVal").textContent = nsis.toFixed(4);

        const tbody = document.getElementById("simMatrixTbody");
        tbody.innerHTML = DIMS.map(d => {{
          const key = d.replace(" ", "_");
          document.getElementById("val-" + key).textContent = x[d].toFixed(2);
          document.getElementById("param-" + key).textContent = `μ=${{dyn[d].mu.toFixed(1)}} σ=${{dyn[d].sigma.toFixed(1)}} A=${{dyn[d].A.toFixed(2)}}`;
          document.getElementById("sd-" + key).textContent = `SD: ${{sd[d].toFixed(1)}}%`;
          const [bLbl, bCls] = bandFor(x[d]);
          return `<tr>
            <td><b>${{d}}</b></td>
            <td>${{x[d].toFixed(2)}}</td>
            <td>${{dyn[d].mu.toFixed(2)}}</td>
            <td>${{dyn[d].sigma.toFixed(2)}}</td>
            <td>${{dyn[d].A.toFixed(2)}}</td>
            <td>${{s[d].toFixed(3)}}</td>
            <td>${{WEIGHTS[d].toFixed(2)}}</td>
            <td><b>${{sd[d].toFixed(1)}}%</b></td>
            <td><span class="band-pill ${{bCls}}">${{bLbl}}</span></td>
          </tr>`;
        }}).join("");

        const xs = [];
        for (let i = 0; i <= 40; i++) xs.push((i * 0.25).toFixed(1));
        const datasets = DIMS.map((d, idx) => ({{
          label: d,
          data: xs.map(v => gauss(parseFloat(v), dyn[d].mu, dyn[d].sigma, dyn[d].A)),
          borderColor: COLORS[idx % COLORS.length],
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.35,
        }}));
        datasets.push({{
          label: "NET Sustainability Envelope",
          data: xs.map(v => {{
            const xv = parseFloat(v);
            return DIMS.reduce((acc, d) => acc + WEIGHTS[d] * gauss(xv, dyn[d].mu, dyn[d].sigma, dyn[d].A), 0);
          }}),
          borderColor: "#0f172a",
          borderDash: [6, 4],
          borderWidth: 3,
          pointRadius: 0,
          tension: 0.35,
        }});

        const ctx = document.getElementById("simCurveCanvas");
        if (ctx && window.Chart) {{
          if (!chart) {{
            chart = new Chart(ctx, {{
              type: "line",
              data: {{ labels: xs, datasets }},
              options: {{
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {{
                  x: {{ title: {{ display: true, text: "Operating Level x (0 - 10)" }} }},
                  y: {{ min: 0, max: 1.35, title: {{ display: true, text: "Coupled Gaussian Impact G_i(x)" }} }},
                }},
                plugins: {{ legend: {{ position: "bottom" }} }},
              }},
            }});
          }} else {{
            chart.data.labels = xs;
            chart.data.datasets = datasets;
            chart.update();
          }}
        }}
      }}

      function loadPreset(pid) {{
        const found = presets.find(p => String(p.id) === String(pid));
        if (!found) return;
        DIMS.forEach(d => {{
          const el = document.getElementById("sl-" + d.replace(" ", "_"));
          if (el && found.x_levels && found.x_levels[d] != null) {{
            el.value = Number(found.x_levels[d]).toFixed(2);
          }}
        }});
        computeAndRender();
      }}

      DIMS.forEach(d => {{
        const el = document.getElementById("sl-" + d.replace(" ", "_"));
        if (el) el.addEventListener("input", () => {{
          document.getElementById("simPatternSelect").value = "custom";
          computeAndRender();
        }});
      }});
      const sel = document.getElementById("simPatternSelect");
      if (sel) {{
        sel.addEventListener("change", () => {{
          if (sel.value !== "custom") loadPreset(sel.value);
        }});
      }}
      window.addEventListener("DOMContentLoaded", () => {{
        if (presets.length > 0) loadPreset(presets[0].id);
        else computeAndRender();
      }});
      setTimeout(() => {{
        if (presets.length > 0) loadPreset(presets[0].id);
        else computeAndRender();
      }}, 80);
    }})();
    </script>
    """


def render_assessment_matrix_html(
    project_root: Path,
    *,
    back_link: bool = True,
) -> str:
    """Render the interactive Assessment Matrix Simulator + clean specification tables/figures."""
    path = assessment_docx_path(project_root)
    if not path.exists():
        raise FileNotFoundError(f"Assessment Matrix document not found: {path}")

    with zipfile.ZipFile(path) as zf:
        document_xml = zf.read("word/document.xml")
        relationships = _load_relationships(zf)

    root = ET.fromstring(document_xml)
    body = root.find(f"{_W}body")
    if body is None:
        raise ValueError("Assessment Matrix docx has no document body.")

    parts: list[str] = []
    _A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

    skip_raw_code_section = False
    for kind, element in _iter_block_items(body):
        if kind == "p":
            text = _paragraph_text(element)
            for blip in element.iter("{" + _A_NS + "}blip"):
                rid = blip.get(_R + "embed") or blip.get(_R + "link") or ""
                media = relationships.get(rid)
                if not media:
                    continue
                try:
                    with zipfile.ZipFile(path) as zf:
                        data_uri = _image_data_uri(zf, media)
                    parts.append(f"<figure><img src=\"{data_uri}\" alt=\"Assessment Matrix figure\"></figure>")
                except KeyError:
                    pass
            if not text:
                continue
            # Stop dumping raw React/Vue implementation source code at the bottom of the docx
            if any(
                marker in text
                for marker in (
                    "### React Component",
                    "### Vue 3 Component",
                    "Save the following as",
                    "npm install chart.js",
                    "import React,",
                    "<template>",
                )
            ):
                skip_raw_code_section = True
            if skip_raw_code_section:
                continue
            block = _classify_paragraph(element, text)
            if block == "code":
                continue
            if block.startswith("h"):
                parts.append(f"<{block}>{html.escape(text)}</{block}>")
            else:
                kind_list = _paragraph_is_list_item(element)
                if kind_list == "ul":
                    parts.append(f"<li>{html.escape(text)}</li>")
                else:
                    parts.append(f"<p>{html.escape(text)}</p>")
        elif kind == "tbl":
            rows = _table_rows(element)
            if not rows:
                continue
            head_cells = rows[0]
            body_rows = rows[1:]
            header_html = (
                "<tr>"
                + "".join(f"<th>{html.escape(' '.join(c))}</th>" for c in head_cells)
                + "</tr>"
            )
            body_html = "".join(
                "<tr>" + "".join(f"<td>{html.escape(' '.join(c))}</td>" for c in row) + "</tr>"
                for row in body_rows
            )
            parts.append(f"<table><thead>{header_html}</thead><tbody>{body_html}</tbody></table>")

    wrapped: list[str] = []
    in_list = False
    for part in parts:
        is_li = part.startswith("<li>")
        if is_li and not in_list:
            wrapped.append("<ul>")
            in_list = True
        elif not is_li and in_list:
            wrapped.append("</ul>")
            in_list = False
        wrapped.append(part)
    if in_list:
        wrapped.append("</ul>")
    body_html = "\n".join(wrapped)

    simulator_html = _build_interactive_simulator_html()
    rendered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    back_btn = '<a class="doc-back" href="/ui/patterns">&larr; Back to New Pattern Discovery</a>' if back_link else ""
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Assessment Matrix &amp; Simulator — New Pattern Discovery — Sentinari</title>\n"
        f"<style>{_DOC_CSS}</style>\n</head>\n<body>\n"
        "<div class=\"doc-shell\">\n"
        f"<div class=\"doc-meta\"><span><b>Sentinel Systemic Sustainability Assessment Matrix</b> &middot; Synchronized with Live Pattern Store ({rendered_at})</span>{back_btn}</div>\n"
        f"{simulator_html}\n"
        f"{body_html}\n"
        "</div>\n</body>\n</html>\n"
    )


def get_assessment_matrix_html(project_root: Path) -> str:
    """Render the interactive Assessment Matrix page with live pattern presets."""
    return render_assessment_matrix_html(project_root)

