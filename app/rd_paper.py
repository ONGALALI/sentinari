"""§79 — R&D Validation Paper generation (owner request, corrections/R&DPaper.md).

"Request R&D Paper" on a New Patterns pattern card produces a real
peer-review-style validation paper rendered from the pattern's stored data —
not just a log entry. The reference implementation in corrections/R&DPaper.md
is a viewer for a `reportData` JSON object with this schema:

    {
      paper_title, pattern_id, abstract,
      hypothesis_formulation,
      mathematical_proof_or_formalism,        (LaTeX, rendered with KaTeX)
      literature_review: { historical_context, inline_citations: [key...] },
      documented_benefits: [str...],
      bibliography: [ { citation_key, full_reference } ... ],
      matrix_scores: { dimension: 0-10, ... }
    }

Owner directive (this session): the math is NOT a handout — it is coded and
must reflect the actual data each discovered pattern produced. So:

- matrix_scores / SD_i(%) / the bell curves are computed by
  app/assessment_math.py (the Assessment Matrix engine) from the pattern's
  real extraction record: evidence chunks, graph mass, confidence,
  cross-field span, recorded benefits.
- Section 2 renders the ACTUAL numbers: the instantiated equation with the
  pattern's measured x_i levels, the applied coupling-rule deltas, S_i
  scores, NSIS, and each dimension's SD_i(%) — plus KaTeX display of the
  canonical equations.
- Section 6 plots the coupled G_i bell curves and the NET Sustainability
  Envelope (Chart.js from CDN, same data the document's simulator uses).
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime, timezone
from typing import Any

from .assessment_math import DIMENSIONS, LEVEL_BANDS, WEIGHTS, evaluate_pattern_matrix
from .llm_gateway import LLMGatewayError, get_gateway
from .pattern_report import _citations_for_pattern, _load_fields
from .pattern_store import get_pattern, get_pattern_graph

_PAPER_CSS = """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #f1f5f9; color: #1e293b; }
  .wrap { max-width: 920px; margin: 0 auto; padding: 24px 22px 60px; }
  .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 26px 28px; margin-top: 18px; box-shadow: 0 1px 3px rgba(15,23,42,0.05); }
  .head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; border-bottom: 1px solid #f1f5f9; padding-bottom: 20px; margin-bottom: 20px; }
  .badge { display: inline-block; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase; background: #eef2ff; color: #4338ca; padding: 4px 12px; border-radius: 8px; }
  h1 { font-size: 26px; margin: 12px 0 0; letter-spacing: -0.4px; line-height: 1.25; }
  .pid { font-family: Consolas, monospace; font-size: 12px; background: #f8fafc; border: 1px solid #e2e8f0; padding: 4px 10px; border-radius: 6px; white-space: nowrap; }
  .label { font-size: 11px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: #94a3b8; margin-bottom: 8px; }
  .abstract { font-style: italic; font-family: Georgia, serif; font-size: 14px; line-height: 1.7; background: #f8fafc; border: 1px solid #f1f5f9; border-radius: 12px; padding: 14px 18px; text-align: justify; }
  h3.sec { font-size: 17px; border-left: 4px solid #4f46e5; padding-left: 12px; margin: 0 0 12px; }
  p.body { font-size: 13.5px; line-height: 1.75; white-space: pre-wrap; }
  .katexbox { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px; text-align: center; overflow-x: auto; margin: 10px 0; }
  .computed { font-family: Consolas, 'Courier New', monospace; font-size: 12px; background: #0f172a; color: #a5f3fc; border-radius: 12px; padding: 16px 18px; overflow-x: auto; line-height: 1.65; white-space: pre; }
  .computed .k { color: #fbbf24; }
  .computed .c { color: #64748b; }
  table.calc { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 12.5px; font-family: Consolas, monospace; }
  table.calc th, table.calc td { border: 1px solid #e2e8f0; padding: 6px 9px; text-align: right; }
  table.calc th { background: #f1f5f9; font-weight: 700; }
  table.calc td:first-child, table.calc th:first-child { text-align: left; }
  .band-1 { color: #64748b; } .band-2 { color: #b45309; font-weight: 700; } .band-3 { color: #15803d; font-weight: 700; }
  .cite-keys { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .cite-key { font-family: Consolas, monospace; font-size: 11px; font-weight: 700; background: #eef2ff; color: #4338ca; border: 1px solid #e0e7ff; padding: 2px 8px; border-radius: 6px; }
  ul.benefits { list-style: none; padding: 0; margin: 0; }
  ul.benefits li { display: flex; gap: 10px; font-size: 13.5px; line-height: 1.65; margin: 9px 0; color: #475569; }
  ul.benefits li::before { content: "\\2022"; color: #4f46e5; font-size: 18px; line-height: 1.2; }
  .bib-toggle { width: 100%; display: flex; justify-content: space-between; align-items: center; background: #f8fafc; border: 0; border-bottom: 1px solid #e2e8f0; font: inherit; font-weight: 700; font-size: 15px; padding: 16px 20px; cursor: pointer; text-align: left; }
  .bib-toggle:hover { background: #f1f5f9; }
  .bib-item { display: flex; gap: 14px; padding: 12px 20px; font-size: 13px; align-items: flex-start; }
  .bib-item + .bib-item { border-top: 1px solid #f1f5f9; }
  .bib-key { font-family: Consolas, monospace; font-weight: 700; color: #4338ca; background: #eef2ff; border: 1px solid #e0e7ff; padding: 2px 8px; border-radius: 6px; white-space: nowrap; }
  .bib-ref { font-family: Georgia, serif; text-align: justify; line-height: 1.6; color: #475569; }
  .chartbox { position: relative; height: 380px; margin-top: 8px; }
  .chart-note { font-size: 11.5px; color: #64748b; margin-top: 8px; line-height: 1.6; }
  .sdrow { margin: 13px 0; }
  .sdhead { display: flex; justify-content: space-between; font-size: 11.5px; font-weight: 700; letter-spacing: 0.6px; text-transform: uppercase; color: #475569; margin-bottom: 5px; }
  .sdhead .val { font-family: Consolas, monospace; color: #0f172a; }
  .track { height: 9px; background: #f1f5f9; border-radius: 999px; overflow: hidden; border: 1px solid #eef2f7; }
  .fill { height: 100%; background: linear-gradient(90deg, #6366f1, #4f46e5); border-radius: 999px; }
  .band { font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 6px; background: #f1f5f9; color: #64748b; margin-left: 8px; letter-spacing: 0.4px; }
  .foot { font-size: 11.5px; color: #94a3b8; margin-top: 20px; text-align: center; line-height: 1.7; }
  @media print { body { background: #fff; } .wrap { max-width: none; } .card { box-shadow: none; break-inside: avoid; } .chartbox { height: 300px; } }
"""


# ---------------------------------------------------------------------------
# reportData construction
# ---------------------------------------------------------------------------

def _cite_key(index: int) -> str:
    return f"[{index}]"


def _llm_json(messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
    """Gateway chat call that tolerates fenced JSON and wrappers."""
    text = get_gateway().chat(messages, temperature=0.2, max_tokens=max_tokens)
    text = str(text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Model did not return a JSON object.")
    return json.loads(text[start : end + 1])


def _canonical_latex() -> str:
    return (
        r"\text{SD}_{i}(\%)=\frac{W_{i}\cdot S_{i}(x)}{\sum_{j=1}^{n}W_{j}\cdot S_{j}(x)}\times 100"
        r"\qquad\quad G_{i}(x)=A_{i}\cdot\exp\!\left(-\frac{(x-\mu_{i})^{2}}{2\sigma_{i}^{2}}\right)"
    )


def _computed_formalism_latex(evaluation: dict[str, Any]) -> str:
    """One display equation with THIS pattern's measured numbers substituted in:
    the x_i vector, the resulting S_i scores, and the NSIS value."""
    x = evaluation["x_levels"]
    s = evaluation["s_scores"]
    nsis = evaluation["nsis"]
    x_vec = ",\\; ".join(f"x_{{\\text{{{d}}}}}={x[d]:.2f}" for d in DIMENSIONS)
    s_vec = ",\\; ".join(f"S_{{\\text{{{d}}}}}={s[d]:.3f}" for d in DIMENSIONS)
    return (
        r"\text{NSIS}=\sum_{j=1}^{7}W_{j}\cdot S_{j}(x)=" + f"{nsis:.4f}"
        r"\qquad \text{with } " + x_vec
        + r"\qquad \text{yielding } " + s_vec
    )


def generate_rd_report(pattern_id: int) -> dict[str, Any]:
    """Build the full reportData object for one pattern (math + LLM-assisted prose)."""
    pattern = get_pattern(int(pattern_id))
    if pattern is None:
        raise ValueError(f"Pattern {pattern_id} not found.")

    fields = _load_fields(str(pattern.get("fields_involved") or "[]"))
    field_pretty = ", ".join(f.replace("-", " ").title() for f in fields) or "Interdisciplinary"
    evidence = []
    for e in (pattern.get("evidence") or [])[:5]:
        t = str((e or {}).get("chunk_text") or "").strip()
        if t:
            evidence.append(t[:500])
    evidence_text = "\n".join(f"- {t}" for t in evidence) or "(no evidence chunks recorded)"

    graph = get_pattern_graph(int(pattern_id))
    n_relations = len(graph.get("relations") or [])
    n_entities = len({
        (r.get("source_name"), r.get("source_type")) for r in graph.get("relations") or []
    } | {
        (r.get("target_name"), r.get("target_type")) for r in graph.get("relations") or []
    })

    # THE MATH — computed from the pattern's actual extraction record.
    evaluation = evaluate_pattern_matrix(
        pattern, graph={"entities": n_entities, "relations": n_relations}
    )

    refs = _citations_for_pattern(pattern)
    bibliography: list[dict[str, str]] = []
    ref_keys: list[str] = []
    for i, ref in enumerate(refs[:12], start=1):
        key = _cite_key(i)
        ref_keys.append(key)
        bibliography.append({"citation_key": key, "full_reference": ref})

    # LLM prose: abstract, hypothesis, historical context. The formalism is
    # NEVER the LLM's — it is the computed engine result.
    analysis: dict[str, Any] = {}
    try:
        analysis = _llm_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Sentinel, a rigorous interdisciplinary research analyst. "
                        "Return ONLY a JSON object (no markdown fences) with keys: "
                        "\"abstract\" (2-3 sentence academic abstract), "
                        "\"hypothesis_formulation\" (3-5 sentences, formal hypothesis plus a "
                        "falsifiable prediction), "
                        "\"historical_context\" (3-5 sentences situating the pattern in prior "
                        "literature, neutral and evidence-based)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Pattern: {pattern.get('title')}\n"
                        f"Type: {pattern.get('pattern_type')}\n"
                        f"Fields: {field_pretty}\n"
                        f"Statement: {pattern.get('statement')}\n"
                        f"Evidence excerpts:\n{evidence_text}\n"
                        f"Known benefits: {str(pattern.get('benefits') or '(none analysed yet)')}\n"
                        f"Measured matrix levels x_i: {evaluation['x_levels']}"
                    ),
                },
            ],
            max_tokens=800,
        )
    except (LLMGatewayError, ValueError, json.JSONDecodeError):
        analysis = {}

    abstract = str(analysis.get("abstract") or "").strip() or (
        f"This paper validates the discovered pattern \u201c{pattern.get('title')}\u201d, "
        f"observed across {field_pretty} with {float(pattern.get('confidence') or 0):.0%} "
        f"extraction confidence and {len(evidence)} evidence chunk(s). The Assessment "
        f"Matrix engine computes a Net Sustainable Impact Score (NSIS) of "
        f"{evaluation['nsis']:.4f} from the pattern's measured operating levels."
    )
    hypothesis = str(analysis.get("hypothesis_formulation") or "").strip() or (
        f"Statement under validation: {pattern.get('statement')}"
    )
    historical = str(analysis.get("historical_context") or "").strip() or (
        "Historical context could not be generated (analysis engine unavailable). "
        "The bibliography below lists the source documents from which this pattern's "
        "evidence was extracted."
    )

    # Documented benefits: reuse the cached LLM benefit notes when present.
    documented: list[str] = []
    benefits_text = str(pattern.get("benefits") or "").strip()
    if benefits_text:
        for line in re.split(r"\n+|\d+\.\s", benefits_text):
            line = line.strip().lstrip("-\u2022 ")
            if len(line) > 20:
                documented.append(line[:400])
    if not documented and evidence:
        documented = [f"Grounded in library evidence: {t[:180]}" for t in evidence[:2]]
    if not documented:
        documented = ["No benefit analysis recorded yet — use 'Analyze benefits' on the pattern card first."]

    title = str(pattern.get("title") or "Untitled pattern")
    return {
        "paper_title": f"Validation of a Cross-Domain Pattern in {field_pretty}: {title}",
        "pattern_id": int(pattern_id),
        "abstract": abstract,
        "hypothesis_formulation": hypothesis,
        "mathematical_proof_or_formalism": _canonical_latex(),
        "computed_formalism": _computed_formalism_latex(evaluation),
        "literature_review": {
            "historical_context": historical,
            "inline_citations": ref_keys,
        },
        "documented_benefits": documented[:6],
        "bibliography": bibliography,
        # Section 6 is now the real engine output.
        "matrix_scores": {d: round(evaluation["sd_percent"][d], 1) for d in DIMENSIONS},
        "matrix_evaluation": evaluation,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "pattern_status": str(pattern.get("status") or "candidate"),
            "fields": fields,
            "llm_assisted": bool(analysis),
            "engine": "app/assessment_math.py — G_i(x) coupled bell curves, coupling rules A/B/C, SD_i(%) normalised by NSIS",
        },
    }


def get_or_generate_rd_report(pattern_id: int, force: bool = False) -> dict[str, Any]:
    """Generate once, cache the JSON in the pattern store, reuse afterwards."""
    from .pattern_store import _connect as _store_connect, ensure_pattern_store

    ensure_pattern_store()
    if not force:
        with _store_connect() as conn:
            row = conn.execute(
                "SELECT note FROM future_requests WHERE kind = 'rd_paper' AND pattern_id = ? ORDER BY id DESC LIMIT 1",
                (int(pattern_id),),
            ).fetchone()
        if row is not None:
            try:
                cached = json.loads(str(row["note"] or ""))
                if isinstance(cached, dict) and cached.get("paper_title"):
                    return cached
            except Exception:
                pass
    report = generate_rd_report(int(pattern_id))
    payload = json.dumps(report, ensure_ascii=False)
    with _store_connect() as conn:
        conn.execute(
            """
            INSERT INTO future_requests (kind, pattern_id, topic, fields, note, status, updated_at)
            VALUES ('rd_paper', ?, ?, ?, ?, 'generated', datetime('now'))
            """,
            (
                int(pattern_id),
                str(report.get("paper_title") or "")[:300],
                json.dumps(report.get("_meta", {}).get("fields") or []),
                payload[:60000],
            ),
        )
        conn.commit()
    return report


# ---------------------------------------------------------------------------
# HTML renderer (corrections/R&DPaper.md layout + the real computed math)
# ---------------------------------------------------------------------------

_CURVE_COLORS = ["#4f46e5", "#0891b2", "#b45309", "#be185d", "#15803d", "#7c3aed", "#dc2626"]


def render_rd_report_html(report: dict[str, Any]) -> str:
    e = _html.escape
    lit = report.get("literature_review") or {}
    bib = report.get("bibliography") or []
    meta = report.get("_meta") or {}
    ev = report.get("matrix_evaluation") or {}
    sd: dict[str, float] = report.get("matrix_scores") or {}

    cite_keys = "".join(
        f"<span class='cite-key'>{e(k)}</span>" for k in (lit.get("inline_citations") or [])
    )
    benefits = "".join(f"<li>{e(b)}</li>" for b in (report.get("documented_benefits") or []))
    bib_rows = "".join(
        "<div class='bib-item'>"
        f"<span class='bib-key'>{e(b.get('citation_key', ''))}</span>"
        f"<p class='bib-ref'>{e(b.get('full_reference', ''))}</p>"
        "</div>"
        for b in bib
    )
    if not bib_rows:
        bib_rows = "<div class='bib-item'><p class='bib-ref'>No citation-ready source documents recorded for this pattern's evidence yet.</p></div>"

    def band_class(label: str) -> str:
        return "band-3" if "Level 3" in label else ("band-2" if "Level 2" in label else "band-1")

    # --- Section 2: canonical equations (KaTeX) + the instantiated computation
    bands = ev.get("level_bands") or {}
    sd_rows = "".join(
        "<div class='sdrow'>"
        f"<div class='sdhead'><span>{e(d)}<span class='band {band_class(str(bands.get(d, '')))}'>{e(str(bands.get(d, '')))}</span></span>"
        f"<span class='val'>{float(sd.get(d, 0)):.1f}%</span></div>"
        f"<div class='track'><div class='fill' style='width:{max(0.0, min(100.0, float(sd.get(d, 0)))):.0f}%'></div></div>"
        "</div>"
        for d in DIMENSIONS
    )

    calc_rows = "".join(
        "<tr>"
        f"<td>{e(d)}</td>"
        f"<td>{float((ev.get('x_levels') or {}).get(d, 0)):.2f}</td>"
        f"<td>{float((ev.get('dynamic_params') or {}).get(d, {}).get('mu', 0)):.2f}</td>"
        f"<td>{float((ev.get('dynamic_params') or {}).get(d, {}).get('sigma', 0)):.2f}</td>"
        f"<td>{float((ev.get('dynamic_params') or {}).get(d, {}).get('A', 0)):.2f}</td>"
        f"<td>{float((ev.get('s_scores') or {}).get(d, 0)):.3f}</td>"
        f"<td>{WEIGHTS.get(d, 0):.2f}</td>"
        f"<td>{float(sd.get(d, 0)):.1f}%</td>"
        f"<td class='{band_class(str(bands.get(d, '')))}'>{e(str(bands.get(d, '')))}</td>"
        "</tr>"
        for d in DIMENSIONS
    )

    measured_rows = "".join(
        "<div class='sdhead'><span>" + e(d) + "</span><span class='val'>"
        + " + ".join(f"{e(k)} {v:.2f}" for k, v in ((ev.get('measured') or {}).get(d, {}) or {}).get('contributions', {}).items())
        + f" = {float((ev.get('x_levels') or {}).get(d, 0)):.2f}</span></div>"
        for d in DIMENSIONS
    )

    nsis = float(ev.get("nsis") or 0.0)
    formalism = str(report.get("mathematical_proof_or_formalism") or "")
    computed = str(report.get("computed_formalism") or "")

    section2 = f"""
    <h3 class="sec">2. Mathematical Formalism — Computed From the Pattern's Measured Data</h3>
    <p class="body">The Assessment Matrix engine (app/assessment_math.py) implements the scoring law from
    corrections/Assessment_Matrix.docx directly against this pattern's extraction record. First the canonical
    equations:</p>
    <div class="katexbox" data-latex="{e(formalism)}"></div>
    <p class="body">Each dimension's operational level <b>x<sub>i</sub></b> is measured from the pattern's real
    data (evidence-chunk depth, source-document breadth, entity/relation graph mass, extraction confidence,
    cross-field span, recorded benefit analysis), the document's three interdependence rules are applied, and
    S<sub>i</sub>(x) = G<sub>i</sub>(x)/A<sub>i</sub> is evaluated on the coupled bell curves:</p>
    <div class="katexbox" data-latex="{e(computed)}"></div>
    <table class="calc">
      <thead><tr><th>Dimension</th><th>x&#8202;_i</th><th>&mu;_i</th><th>&sigma;_i</th><th>A_i</th><th>S_i(x)</th><th>W_i</th><th>SD_i(%)</th><th>Level</th></tr></thead>
      <tbody>{calc_rows}</tbody>
    </table>
    <p class="body" style="font-size:12.5px;color:#64748b;">NSIS (Net Sustainable Impact Score) = <b>{nsis:.4f}</b> &middot;
    SD<sub>i</sub>(%) values are normalised against NSIS and always sum to 100%. Measured level derivations:</p>
    <div class="computed"><span class="c">// measured x_i levels — each term is a quantity extracted from the pattern store</span>
{measured_rows}
<span class="c">// coupling rules applied: A) Intelligence&gt;7 contracts Human Agency &mu;/&sigma;; B) Risk&gt;5 widens Societal &sigma; and drops Decision &mu;; C) Scientific&gt;7 lifts Knowledge A</span></div>
    """

    # --- Section 6: SD_i bars + the live coupled bell-curve chart
    curve_payload = json.dumps(
        {
            "labels": ev.get("curve_x") or [],
            "curves": ev.get("curves") or {},
            "envelope": ev.get("envelope") or [],
        },
        ensure_ascii=False,
    )

    section6 = f"""
    <h3 class="sec">6. Systemic Sustainability Matrix Assessment — Measured Results</h3>
    <p class="body" style="font-size:12.5px;color:#64748b;">Normalized Dimension Impact SD<sub>i</sub>(%)
    computed for this pattern's measured operating levels — how the pattern's actual footprint distributes
    across the seven Assessment Matrix pillars (impact level bands: 0&ndash;33.33% Low, 33.34&ndash;67.67% Medium,
    67.68&ndash;100% High).</p>
    {sd_rows}
    <h3 class="sec" style="margin-top:22px;">Coupled Bell-Curve Simulator — This Pattern's Footprint</h3>
    <p class="body" style="font-size:12.5px;color:#64748b;">G<sub>i</sub>(x) = A<sub>i</sub>&middot;exp(&minus;(x&minus;&mu;<sub>i</sub>)&sup2;/2&sigma;<sub>i</sub>&sup2;)
    for the pattern's measured levels, with the document's interdependence rules applied to (&mu;, &sigma;, A).
    The dashed black curve is the NET Sustainability Envelope (mean of all seven).</p>
    <div class="chartbox"><canvas id="curveChart"></canvas></div>
    <div class="chart-note">Solid curves: dimension impact across the 0&ndash;10 operating scale. Dashed: net envelope.
    Narrow-variance dimensions (Risk, Human Agency) are the document's <i>volatility anchors</i>; broad high-amplitude
    ones (Scientific, Knowledge) are the <i>paradigm multipliers</i> that lift the whole matrix.</div>
    <script id="curveData" type="application/json">{curve_payload}</script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script>
    (() => {{
      const el = document.getElementById('curveData');
      const data = JSON.parse(el.textContent);
      const labels = data.labels.map(v => v.toFixed(1));
      const datasets = Object.entries(data.curves).map(([dim, ys], i) => ({{
        label: dim, data: ys, borderColor: '{_CURVE_COLORS[0]}'.replace('COLORSLOT', ['{_CURVE_COLORS[0]}']),
        borderWidth: 2, pointRadius: 0, tension: 0.4, fill: false,
      }}));
      // assign per-dimension colors deterministically
      Object.keys(data.curves).forEach((dim, i) => {{ datasets[i].borderColor = ['{_CURVE_COLORS[0]}','{_CURVE_COLORS[1]}','{_CURVE_COLORS[2]}','{_CURVE_COLORS[3]}','{_CURVE_COLORS[4]}','{_CURVE_COLORS[5]}','{_CURVE_COLORS[6]}'][i % 7]; }});
      datasets.push({{
        label: 'NET Sustainability Envelope', data: data.envelope,
        borderColor: '#0f172a', borderDash: [6, 4], borderWidth: 3, pointRadius: 0, tension: 0.4, fill: false,
      }});
      const ctx = document.getElementById('curveChart');
      if (ctx && window.Chart) {{
        new Chart(ctx, {{
          type: 'line',
          data: {{ labels, datasets }},
          options: {{
            responsive: true, maintainAspectRatio: false,
            scales: {{
              x: {{ title: {{ display: true, text: 'Dimension operating level x (0 - 10)' }} }},
              y: {{ min: 0, max: 1.1, title: {{ display: true, text: 'Impact G_i(x)' }} }},
            }},
            plugins: {{ legend: {{ position: 'right' }} }},
          }},
        }});
      }}
    }})();
    </script>
    """

    llm_note = "" if meta.get("llm_assisted") else (
        "<div class='foot'>Prose sections generated deterministically from stored pattern data (analysis engine unavailable at generation time); all computed values are engine output either way.</div>"
    )
    generated = str(meta.get("generated_at") or "")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(str(report.get('paper_title') or ''))} — R&D Validation Paper</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<style>{_PAPER_CSS}</style></head><body>
<div class="wrap">
  <div class="card">
    <div class="head">
      <div>
        <span class="badge">Peer-Reviewed R&amp;D Validation Paper</span>
        <h1>{e(str(report.get('paper_title') or ''))}</h1>
      </div>
      <span class="pid">ID: {e(str(report.get('pattern_id') or ''))}</span>
    </div>
    <div class="label">Abstract</div>
    <p class="abstract">{e(str(report.get('abstract') or ''))}</p>
    <div style="font-size:12px;color:#64748b;margin-top:8px;">Generated {e(generated)} &middot; pattern status: {e(str(meta.get('pattern_status') or 'candidate'))} &middot; engine: {e(str(meta.get('engine') or ''))}</div>
  </div>

  <section class="card">
    <h3 class="sec">1. Hypothesis Formulation</h3>
    <p class="body">{e(str(report.get('hypothesis_formulation') or ''))}</p>
  </section>

  <section class="card">{section2}</section>

  <section class="card">
    <h3 class="sec">3. Literature Review &amp; Historical Context</h3>
    <p class="body">{e(str(lit.get('historical_context') or ''))}</p>
    <div class="cite-keys"><span style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Linked inlines:</span>{cite_keys}</div>
  </section>

  <section class="card">
    <h3 class="sec">4. Documented System Benefits</h3>
    <ul class="benefits">{benefits or '<li>None recorded.</li>'}</ul>
  </section>

  <section class="card" style="padding:0;overflow:hidden;">
    <button class="bib-toggle" type="button" onclick="const p=document.getElementById('bibBody');p.hidden=!p.hidden;this.querySelector('.t').textContent=p.hidden?'\\u25B2':'\\u25BC'">
      <span>&#128218; 5. Comprehensive Bibliography ({len(bib)})</span><span class="t">&#9660;</span>
    </button>
    <div id="bibBody">{bib_rows}</div>
  </section>

  <section class="card" style="border-top:4px solid #4f46e5;">{section6}</section>
  {llm_note}
  <div class="foot">Sentinel &middot; New Patterns workspace &middot; R&amp;D Validation Paper — all matrix values computed by the Assessment Matrix engine from the pattern's extraction record.</div>
</div>
<script>
window.addEventListener('DOMContentLoaded', () => {{
  if (window.katex) {{
    document.querySelectorAll('.katexbox[data-latex]').forEach((el) => {{
      try {{ katex.render(el.getAttribute('data-latex'), el, {{ displayMode: true, throwOnError: false }}); }} catch (_) {{}}
    }});
  }}
}});
</script>
</body></html>"""
