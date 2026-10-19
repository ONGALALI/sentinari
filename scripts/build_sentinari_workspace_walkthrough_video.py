#!/usr/bin/env python3
"""Automated Master Workspace Walkthrough Video Production Pipeline for Sentinari.

Conceived, Researched & Developed by Dr. Pierre C. Wepener.
Renders 1080p Full HD cinematic presentation slides, synthesizes professional
neural voiceover narration across all 6 core sections, and compiles individual
section video clips and the complete master walkthrough MP4 video.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
from pathlib import Path

try:
    import edge_tts
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFont
except ImportError as ex:
    print(f"Missing dependency: {ex}. Run: pip install edge-tts pillow imageio-ffmpeg")
    sys.exit(1)

OUTPUT_DIR = Path("D:/Sentinari/constitution/walkthrough_assets")
MASTER_VIDEO_PATH = Path("D:/Sentinari/constitution/Sentinari_Complete_Workspace_Walkthrough.mp4")
VOICE_NAME = "en-US-AndrewNeural"  # Professional, authoritative, natural documentary narrator

SECTIONS_CONFIG = [
    {
        "section_id": "sec_01",
        "section_num": 1,
        "section_title": "Architecture & 100-Year Constitution",
        "slides": ["slide_01", "slide_02"],
        "out_filename": "section_01_architecture_constitution.mp4",
    },
    {
        "section_id": "sec_02",
        "section_num": 2,
        "section_title": "Playground & Database Reindexing",
        "slides": ["slide_03", "slide_04"],
        "out_filename": "section_02_playground_database_refresh.mp4",
    },
    {
        "section_id": "sec_03",
        "section_num": 3,
        "section_title": "New Pattern Discovery & 7-D Assessment Matrix",
        "slides": ["slide_05", "slide_06", "slide_07", "slide_08"],
        "out_filename": "section_03_pattern_discovery_deep_dive.mp4",
    },
    {
        "section_id": "sec_04",
        "section_num": 4,
        "section_title": "Qualia Lab & Forensic Governance Deception Suite",
        "slides": ["slide_09", "slide_10"],
        "out_filename": "section_04_qualia_forensic_governance.mp4",
    },
    {
        "section_id": "sec_05",
        "section_num": 5,
        "section_title": "Learning Index & Assessment Ladder",
        "slides": ["slide_11"],
        "out_filename": "section_05_learning_hle_benchmarks.mp4",
    },
    {
        "section_id": "sec_06",
        "section_num": 6,
        "section_title": "Synthesis & Master Operational Workflow",
        "slides": ["slide_12"],
        "out_filename": "section_06_master_workflow_synthesis.mp4",
    },
]

SLIDES_DATA = [
    # -------------------------------------------------------------------------
    # SECTION 1: ARCHITECTURE & CONSTITUTION
    # -------------------------------------------------------------------------
    {
        "id": "slide_01",
        "section": "SECTION 1: OVERVIEW",
        "category": "TECHNICAL SHOWCASE & WORKSPACE TOUR",
        "title": "SENTINARI: WORKSPACE & SUBSYSTEM MASTER WALKTHROUGH",
        "subtitle": "An Element-by-Element Operational Guide to the Sovereign Epistemic Platform",
        "badge": "COMPLETE SYSTEM SPECIFICATION • DR. PIERRE C. WEPENER",
        "cards": [
            ("Sovereign Epistemic Platform", "A zero-cloud, multi-disciplinary intelligence engine designed to eliminate information asymmetry and bridge material reality with human understanding."),
            ("Author & Chief Architect", "Conceived, researched, designed, and engineered entirely on personal initiative by Dr. Pierre C. Wepener as a 100% self-funded breakthrough."),
            ("Scope of this Walkthrough", "A comprehensive visual and operational inspection of every console: Start Menu, Playground, Pattern Discovery, Qualia Lab, and Learning Index."),
        ],
        "script": (
            "Welcome to the official, in-depth architectural and operational walkthrough of Sentinari. Conceived, researched, "
            "and engineered entirely on personal initiative by Dr. Pierre C. Wepener, Sentinari is a sovereign, Responsible "
            "Intelligence platform created to bridge the widening chasm between complex material reality and human comprehension. "
            "In this master showcase, we will conduct a granular, element-by-element tour across every console, lab, and workspace—from "
            "the underlying database synchronization engine and the New Pattern Discovery matrix to the Qualia vector lab and our "
            "merciless courtroom forensic governance deception audit. Every subsystem is designed to operate harmoniously, providing "
            "unparalleled transparency, rigorous provenance, and empirical accountability."
        ),
    },
    {
        "id": "slide_02",
        "section": "SECTION 1: GOVERNANCE & START",
        "category": "FOUNDATIONAL DOCTRINE",
        "title": "THE 100-YEAR CONSTITUTION & STUDIO START CONSOLE",
        "subtitle": "Inviolable Laws of Epistemic Integrity and The Unified Workspace Cockpit",
        "badge": "SOVEREIGN CHARTER • ARTICLES I - VIII",
        "cards": [
            ("The 100-Year Constitution", "Available directly from the top menu as D:/Constitution.pdf. Binds the reasoning engine to 8 immutable articles of material reality, humility, and zero bias."),
            ("Studio Start Console (/ui/start)", "The central command cockpit. Provides live process inspection, engine startup toggles, and instant one-click switching across all workspaces."),
            ("Fail-Closed Security Doctrine", "The dormant challenger Victus, autonomous loops, and third-party gateways sit behind explicit configuration gates, ensuring zero unmonitored execution."),
        ],
        "script": (
            "Every operation in Sentinari is anchored in an unyielding ethical charter: The 100-Year Constitution, authored by "
            "Dr. Pierre C. Wepener and now accessible directly from the top navigation bar across all workspaces. Article One establishes "
            "the Axiom of Material Reality: empirical truth and physical telemetry unconditionally supersede institutional narratives. "
            "Article Two mandates the Neutral Illuminator doctrine: Sentinari possesses zero corporate enemies and zero ideological loyalties—only "
            "verifiable hypotheses. Article Three enforces Systematic Humility, degrading confidence the moment superior counter-evidence "
            "emerges. And Article Four dictates the Declaration of Inadequacy, refusing speculative hallucination when data is incomplete. "
            "At the gateway to this platform sits the Studio Start Console at /ui/start, providing a single cockpit to inspect local server "
            "health, verify local model bindings, and navigate seamlessly across all specialized labs."
        ),
    },

    # -------------------------------------------------------------------------
    # SECTION 2: PLAYGROUND & DATABASE REINDEXING
    # -------------------------------------------------------------------------
    {
        "id": "slide_03",
        "section": "SECTION 2: PLAYGROUND DASHBOARD",
        "category": "WORKSPACE 1: THE PLAYGROUND",
        "title": "SCIENTIFIC CURATED DOMAINS & DASHBOARD",
        "subtitle": "Unified Monitoring Across 21 Sentinel Disciplines & Knowledge Corpora",
        "badge": "21 SCIENTIFIC DISCIPLINES • /ui/playground",
        "cards": [
            ("The 21 Scientific Disciplines", "Physics, Chemistry, Biology, Economics, Constitutional Law, Earth & Climate, Metallurgy, Medicine, Computer Science, and Engineering."),
            ("Corpus Telemetry", "Real-time indexed library telemetry: 15,041+ Curated Works, 1,280+ Analyzed Datasets, and over 445,000 atomic semantic chunks."),
            ("Inference & Session Memory", "Tracks conversation turns, active context windows, and local model bindings with zero reliance on opaque external black-box LLM APIs."),
        ],
        "script": (
            "Let us step into Workspace One: The Sentinari Playground at /ui/playground. The Playground is our primary laboratory "
            "for knowledge curation and interactive exploration. Across the main dashboard, you see the twenty-one Sentinel scientific "
            "domains—ranging from physics and biochemistry to macroeconomics, jurisprudence, and climatology. The dashboard surfaces "
            "live telemetry from our knowledge base: currently tracking over fifteen thousand curated scholarly works and more than twelve "
            "hundred deeply analyzed empirical datasets. Each domain tile displays its ingested document volume, active semantic density, "
            "and health status. From here, researchers can launch targeted domain queries, inspect session memories, and monitor "
            "the continuous ingestion queue as new scientific literature is assimilated."
        ),
    },
    {
        "id": "slide_04",
        "section": "SECTION 2: DATABASE REINDEXING",
        "category": "WORKSPACE 1: ENGINE MECHANICS",
        "title": "SYNCHRONOUS DATABASE REFRESH & INGESTION PIPELINE",
        "subtitle": "Under the Hood: SQLite WAL Mode, Multi-Process Lock Armor & Full-Text Search",
        "badge": "DATABASE SYNCHRONIZATION & ZERO-LOCK ARMOR",
        "cards": [
            ("The 'Refresh Database' Action", "Probes SQLite sentinari.db (and PostgreSQL 16 pgvector on Cloud SQL). Validates schema integrity, active connections, and table index health."),
            ("Ingestion & Embedding Lane", "Newly deposited documents are parsed, chunked, and embedded into 768-dimensional float vectors with strict timeout budgets to prevent queue starvation."),
            ("FTS5 Shadow Tables", "SQLite FTS5 full-text shadow tables are synchronously updated alongside vector stores, powering instant hybrid lexical-plus-semantic lookups."),
            ("Zero-Lock Concurrency", "Engineered with PRAGMA busy_timeout armor and WAL journaling to permit concurrent reader queries while background ingest workers commit batches."),
        ],
        "script": (
            "A critical element often asked about is the database refresh operation on the Playground. When you click Refresh Status or "
            "initiate an ingestion cycle, Sentinari executes an advanced, multi-stage synchronization pipeline. First, it probes the primary "
            "database—sentinari.db in local mode, or Google Cloud SQL PostgreSQL sixteen with native pgvector in the cloud. It verifies schema "
            "integrity and updates live document counts across all twenty-one fields. Next, the ingestion queue worker picks up newly deposited "
            "PDFs and datasets, parsing them into atomic semantic chunks. Each chunk is embedded into high-dimensional vector space under a strict "
            "forty-five-second budget to prevent pipeline starvation. Simultaneously, SQLite FTS5 shadow tables are reindexed for lightning-fast "
            "lexical search. To guarantee absolute stability without database lock crashes, Sentinari employs Write-Ahead Logging and adaptive "
            "busy-timeout backoff, ensuring seamless multi-threaded read and write concurrency."
        ),
    },

    # -------------------------------------------------------------------------
    # SECTION 3: PATTERN DISCOVERY & 7-D MATRIX
    # -------------------------------------------------------------------------
    {
        "id": "slide_05",
        "section": "SECTION 3: PATTERN DISCOVERY",
        "category": "WORKSPACE 2: FLAGSHIP DISCOVERY",
        "title": "THE NEW PATTERN DISCOVERY WORKSPACE",
        "subtitle": "Breaking Academic Silos to Surface Cross-Disciplinary Embryonic Correlations",
        "badge": "CROSS-DISCIPLINARY DISCOVERY • /ui/patterns",
        "cards": [
            ("Collapsible Concertina Design", "Patterns are organized into 8-per-page collapsible concertinas. Maximizes screen ergonomics while minimizing browser DOM memory and GPU load."),
            ("Multi-Domain Confidence Tracks", "Quantifies empirical confidence (0–100%) by correlating primary sources across disciplines that single-field specialists never cross-reference."),
            ("5-Stage Maturity Pipeline", "Tracks embryonic hypotheses from Initial Ingestion -> Literature Cross-Verification -> Empirical Modeling -> Experimental Validation -> Final Assessment."),
            ("Primary Source Provenance", "Every pattern card provides direct verbatim excerpts, author attributions, and document IDs from the underlying 15,000+ library works."),
        ],
        "script": (
            "We now arrive at the flagship technological deliverable of Sentinari: The New Pattern Discovery Workspace at /ui/patterns. "
            "Academic and industrial research has long suffered from rigid disciplinary silos. A materials scientist researching battery "
            "alloys rarely monitors geopolitical supply-chain treaties or macro-fiscal monetary shifts. Sentinari shatters these silos. "
            "Our background discovery daemon continuously cross-correlates findings across all disciplines, surfacing emergent correlations "
            "long before they appear in mainstream literature. In the workspace, discoveries are displayed as sleek, collapsible concertina cards "
            "rendered eight per page to ensure optimal memory performance. Each card displays an overall confidence score, multi-disciplinary tags, "
            "exact primary evidence quotes, and a five-stage indicator tracking the pattern's journey from an embryonic spark to full scientific validation."
        ),
    },
    {
        "id": "slide_06",
        "section": "SECTION 3: ASSESSMENT MATRIX",
        "category": "WORKSPACE 2: MATHEMATICAL MODEL",
        "title": "THE 7-D ASSESSMENT MATRIX SIMULATOR",
        "subtitle": "Closed-Form Gaussian Bell Curves & Coupled Multi-Dimensional Equilibrium",
        "badge": "MATHEMATICALLY FORMULATED • NOT AN AI GUESS",
        "cards": [
            ("7 Evaluated Dimensions", "Knowledge (K), Intelligence (I), Decision (D), Human Agency (H), Societal (S), Ethics (E), and Risk (R) on normalized operating scales x_i in [0, 10]."),
            ("Gaussian Potency Law", "S_i(x_i) = A_i * exp(-(x_i - mu_i)^2 / (2 * sigma_i^2)). Defines amplitude A_i, optimal center mu_i, and variance tolerance sigma_i."),
            ("Interdependence Rules (A, B, C)", "Adjusting any slider recalculates adjacent dimensions: escalating Decision (D) pulls Societal (S) and expands the systemic Risk (R) envelope."),
            ("Net Sustainable Impact Score", "NSIS = sum(W_i * S_i(x_i)). Proves mathematically whether an organizational policy or technology is sustainable or heading for systemic failure."),
        ],
        "script": (
            "Inside the Pattern Discovery workspace sits one of our most mathematically rigorous systems: The 7-D Assessment Matrix "
            "and its interactive sliding-scale simulator. Sentinari does not rely on subjective AI opinions; every discovery is evaluated "
            "across seven interconnected dimensions: Knowledge, Intelligence, Decision, Human Agency, Societal Impact, Ethics, and Risk. "
            "Each dimension is governed by closed-form Gaussian bell curves that define its amplitude, optimal center, and tolerance envelope. "
            "In our live simulator, when a user pushes a slider—for example, aggressively maximizing Decision velocity to nine out of ten—coupled "
            "Interdependence Rules take effect immediately. The simulator demonstrates how over-optimizing one variable pulls Societal equilibrium "
            "and causes the Risk envelope to expand exponentially. The Net Sustainable Impact Score quantifies whether the technological "
            "trajectory is stable, providing leaders with an unfalsifiable predictive flight simulator."
        ),
    },
    {
        "id": "slide_07",
        "section": "SECTION 3: R&D PAPERS",
        "category": "WORKSPACE 2: SCIENTIFIC DELIVERABLES",
        "title": "THE UNIFIED 15-INDICATOR R&D VALIDATION PAPER",
        "subtitle": "Autonomous Generation of Publication-Grade Scientific Papers with APA 7th Citations",
        "badge": "5 RIGOROUS SECTIONS • 15 MATURITY INDICATORS",
        "cards": [
            ("Section 1 & 2: Front Matter & Intro", "Publication Title, Word-Counted Abstract, Technical Keywords, Formal Problem Statement, Hypothesis, and Literature Review with inline APA 7 citations."),
            ("Section 3: Methodology & KaTeX Proofs", "Architectural data-flow diagrams, technical specifications, and mathematical proofs rendered with KaTeX."),
            ("Section 4: Testing & Empirical Matrices", "Experimental Testbed configuration, 7-D Assessment Matrix empirical results table, and quantitative benchmark evaluation."),
            ("Section 5: Recommended Solutions", "Gemma-synthesized concrete, actionable solutions to solve the problem—or constitutional fallback when evidence is incomplete."),
        ],
        "script": (
            "Every validated pattern is an academic paper in embryo. With one click, Sentinari generates a complete, publication-grade "
            "Fifteen-Indicator Unified R&D Validation Paper. Structured across five rigorous academic sections, the paper begins with "
            "a formal abstract and technical keywords, followed by a detailed Problem Statement and Hypothesis grounded in an academic "
            "literature review with clickable APA seventh edition citations. Section Three details the technical system architecture, data flows, "
            "and mathematical proofs rendered in KaTeX. Section Four outlines the experimental testbed and empirical results. Finally, Section Five "
            "delivers concrete, actionable Recommended Solutions synthesized from the indexed evidence. If empirical data is incomplete, "
            "the engine invokes its constitutional fallback, refusing to hallucinate."
        ),
    },
    {
        "id": "slide_08",
        "section": "SECTION 3: ECONOMIC MODEL",
        "category": "WORKSPACE 2: ECONOMIC IMPACT",
        "title": "EMPIRICAL ECONOMIC TRAJECTORY MODEL (FIGURE 6.4)",
        "subtitle": "Transforming Scientific Patterns into Boardroom-Ready Fiscal Forecasts",
        "badge": "QUANTITATIVE ECONOMIC FORECASTING",
        "cards": [
            ("Trajectory Equation V(t)", "V(t) = V_0 + Delta_V * (1 - exp(-k * t)). Mathematically models economic value maturation over a 5-year deployment horizon."),
            ("Quantitative Fiscal Metrics", "Projects capital investment required, projected annual cost savings, and risk mitigation economic value in millions of dollars."),
            ("Strategic Boardroom Presentation", "Provides corporate boards, venture funds, and governments with rigorous fiscal justifications rather than speculative AI hand-waving."),
        ],
        "script": (
            "To bridge scientific discovery with real-world investment, every R&D Paper incorporates our Empirical Economic Trajectory Model, "
            "illustrated in Figure 6.4. Using exponential saturation kinetics, the equation V of t equals V zero plus Delta V times one minus "
            "e to the negative k t, modeling value realization across a five-year horizon. Sentinari computes exact capital expenditure requirements, "
            "projected annual operating cost savings, and cumulative systemic risk mitigation value. This gives corporate boards, venture capital "
            "alliances, and sovereign funds a clear, quantitatively defended business case—translating multi-disciplinary breakthroughs into "
            "unassailable economic ROI."
        ),
    },

    # -------------------------------------------------------------------------
    # SECTION 4: QUALIA LAB & FORENSIC DECEPTION
    # -------------------------------------------------------------------------
    {
        "id": "slide_09",
        "section": "SECTION 4: QUALIA LAB",
        "category": "WORKSPACE 3: COGNITIVE VECTOR LAB",
        "title": "THE QUALIA LAB & PSEUDODYNAMIC SIMULATION",
        "subtitle": "Steering and Damping Cognitive Trajectories Across S, A, and Q Vector Fields",
        "badge": "VECTOR DYNAMICS & ATTENTION TRAJECTORY • /ui/qualia",
        "cards": [
            ("Vector Parameter Controls", "Q0 (semantic prior), A0 (attention vector), and S (stabilizer attractor) steer the cognitive response process."),
            ("Hyperparameter Dynamics", "Alpha (state persistence), Beta (stabilizer pull), and Gamma (cross-coupling coherence pressure) clamped by the Gamma Cap."),
            ("Trajectory & Spider Vector Plots", "Visualizes attention movement over discrete simulation steps and plots multi-model radar overlays to evaluate response stability vs. anxiety."),
        ],
        "script": (
            "Next, we enter Workspace Three: The Sentinari Qualia Lab at /ui/qualia. The Qualia Lab provides a revolutionary interface "
            "for inspecting and steering the internal dynamics of reasoning models. Rather than treating artificial intelligence as an "
            "uncontrollable black box, the Qualia Lab exposes the underlying vector field. Researchers can tune Q zero, representing the starting "
            "semantic prior, A zero, the attention vector, and S, the stabilizing attractor. Hyperparameters like Alpha govern state persistence, "
            "Beta controls stabilizer pull, and Gamma modulates cross-coupling coherence. Real-time SVG plots render the trajectory curve "
            "over simulation steps, while our spider radar plots compare multi-model attention distributions, evaluating stability versus cognitive anxiety."
        ),
    },
    {
        "id": "slide_10",
        "section": "SECTION 4: FORENSIC DECEPTION",
        "category": "WORKSPACE 3: FORENSIC AUDITING",
        "title": "FORENSIC GOVERNANCE & COURTROOM DECEPTION ENGINE",
        "subtitle": "Dr. Pierre C. Wepener Architecture: Criminal Psychology Cross-Examination",
        "badge": "SCAN / CBCA LINGUISTIC ANALYSIS & MERCILESS A4 AUDIT",
        "cards": [
            ("Courtroom Deception Taxonomy", "Linguistic statement analysis (SCAN/CBCA) detecting agency dissociation, epistemic hedging, unsolicited candor oaths, and euphemisms."),
            ("Discourse Noise Decoupling", "Isolates and strips rhetorical fluff, political spin, and emotional padding to expose residual naked factual assertions."),
            ("Merciless 1-Page A4 Audit Sheet", "Synthesizes an uncompromising APA 7th referenced audit report with 5 societal impact dimensions and a Projected Research ROI %."),
            ("1-Click Printable PDF Standard", "Fully print-optimized to output an official 1-page A4 cross-examination sheet with cryptographic time-stamping."),
        ],
        "script": (
            "Embedded directly inside the Qualia Lab is one of Dr. Wepener's signature contributions: The Forensic Governance and Courtroom "
            "Deception Engine. Drawing upon Dr. Wepener's background in criminal psychology and courtroom lie-detection, this suite cross-examines "
            "high-priority governance statements, geopolitical communiqués, and corporate subpoena defenses. Users can paste up to five thousand "
            "characters of text or load pre-configured exemplars such as Russia-Ukraine diplomatic evasion. The engine scans for six clinical deception "
            "markers: agency dissociation, where leaders use passive voice to avoid personal accountability; epistemic equivocation designed "
            "to survive perjury; unsolicited oaths of honesty; and euphemistic minimization. It decouples rhetorical noise, isolates the naked "
            "factual core, and generates an uncompromising, one-page A4 audit report referenced in strict APA seventh edition format."
        ),
    },

    # -------------------------------------------------------------------------
    # SECTION 5: LEARNING INDEX & BENCHMARKS
    # -------------------------------------------------------------------------
    {
        "id": "slide_11",
        "section": "SECTION 5: LEARNING INDEX",
        "category": "WORKSPACE 4: CONTINUOUS EXAMINER",
        "title": "THE LEARNING INDEX & ASSESSMENT LADDER",
        "subtitle": "Proving That Ingested Knowledge is Authentically Applied and Rigorously Graded",
        "badge": "HUMANITY'S LAST EXAM & SWE-BENCH PRO • /ui/learning",
        "cards": [
            ("% Learned Progress Gauge", "Tracks corpus ingestion, factual assimilation, and active application across all 21 Sentinel scientific fields."),
            ("Humanity's Last Exam (HLE)", "Integration with the most demanding global academic benchmark, evaluating multimodal reasoning and complex scientific problems."),
            ("SWE-Bench Pro Loader", "Evaluates real-world software engineering and code-repair capabilities under isolated test execution harnesses."),
            ("Strict Calibration Gate Law", "Calibration unlocks at 60% Formative Assessment; HLE opens at 55% post-calibration; Workbench opens at 50% HLE."),
        ],
        "script": (
            "Workspace Four brings us to the Sentinari Learning Index at /ui/learning. In conventional systems, models ingest vast text corpora "
            "with zero verification of true comprehension. Sentinari rejects this unverified approach through the Learning Index and Assessment "
            "Ladder. The workspace displays a real-time Percent Learned progress gauge, continuously auditing whether indexed documents are "
            "actively understood. We integrate Humanity's Last Exam—the most rigorous multi-disciplinary academic benchmark in the world—alongside "
            "SWE-Bench Pro for autonomous software engineering validation. In accordance with our gate laws, higher-order capabilities only unlock "
            "once prerequisite mastery thresholds are proven, guaranteeing that Sentinari remains an authenticated, graded knowledge engine."
        ),
    },

    # -------------------------------------------------------------------------
    # SECTION 6: MASTER WORKFLOW & SYNTHESIS
    # -------------------------------------------------------------------------
    {
        "id": "slide_12",
        "section": "SECTION 6: MASTER WORKFLOW",
        "category": "SYNTHESIS & PARTNERSHIP",
        "title": "THE COMPLETE SOVEREIGN INTELLIGENCE PLATFORM",
        "subtitle": "100% Self-Funded Personal Initiative • Ready for Global Scale and Strategic Capital",
        "badge": "COPYRIGHT © DR. PIERRE C. WEPENER • READY FOR PARTNERSHIP",
        "cards": [
            ("Complete Unified Workflow", "From document ingestion in Playground -> Pattern discovery -> 7-D matrix simulation -> Qualia vector steering -> Forensic governance audit."),
            ("Sole Proprietary Authorship", "Conceived, architected, and engineered solely by Dr. Pierre C. Wepener. Zero institutional debt, zero corporate capture, zero bureaucratic delay."),
            ("Partnership Opportunities", "Open for strategic seed investment, sovereign compute alliances, and enterprise deployments with forward-thinking leaders."),
        ],
        "script": (
            "In conclusion, Sentinari represents a unified, production-ready cognitive architecture. From document ingestion and database "
            "reindexing in the Playground to interdisciplinary pattern discovery, seven-dimensional Gaussian impact modeling, Qualia vector "
            "steering, and forensic courtroom cross-examination—every workspace serves a singular mission: Responsible Intelligence in "
            "service of human society. Conceived, architected, and engineered entirely on personal initiative by Dr. Pierre C. Wepener, Sentinari "
            "bypassed academic bureaucracy to deliver working, enterprise-grade software. The entire codebase, mathematical formalisms, and "
            "constitutional framework are ready for strategic global investors, Google Cloud and DeepMind research partners, and agile technology "
            "leaders ready to deploy transformative intelligence. Thank you."
        ),
    },
]


def get_ffmpeg_exe() -> str:
    """Locate the ffmpeg binary from imageio_ffmpeg or system path."""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load Segoe UI or Arial font."""
    font_names = (
        ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold
        else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]
    )
    for p in font_names:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def render_slide_image(slide: dict, out_path: Path) -> None:
    """Render a stunning 1920x1080 Full HD slide graphic with PIL."""
    w, h = 1920, 1080
    im = Image.new("RGB", (w, h), (11, 15, 25))
    draw = ImageDraw.Draw(im)

    # Ambient gradients / decorative glow
    draw.rectangle([0, 0, w, h], fill=(11, 15, 25))
    draw.ellipse([w - 600, -200, w + 300, 500], fill=(24, 32, 60))
    draw.ellipse([-300, h - 500, 400, h + 200], fill=(16, 38, 48))

    # Fonts
    f_sec = get_font(18, bold=True)
    f_badge = get_font(19, bold=True)
    f_cat = get_font(22, bold=True)
    f_title = get_font(46, bold=True)
    f_sub = get_font(26, bold=False)
    f_card_head = get_font(23, bold=True)
    f_card_body = get_font(19, bold=False)
    f_foot = get_font(19, bold=False)

    # Top Section Label & Category Bar
    y = 55
    sec_label = slide.get("section", "MASTER WALKTHROUGH")
    cat_text = slide.get("category", "SYSTEM SPECIFICATION")
    draw.text((100, y), f"{sec_label} • {cat_text}", font=f_cat, fill=(129, 140, 248))

    # Top Right Badge
    badge_text = slide.get("badge", "SENTINARI")
    bbox = draw.textbbox((0, 0), badge_text, font=f_badge)
    bw = bbox[2] - bbox[0] + 32
    bh = 36
    bx = w - 100 - bw
    draw.rounded_rectangle([bx, y - 5, bx + bw, y - 5 + bh], radius=18, fill=(26, 34, 56), outline=(99, 102, 241), width=2)
    draw.text((bx + 16, y - 1), badge_text, font=f_badge, fill=(165, 180, 252))

    # Main Title
    y += 44
    title_text = slide.get("title", "")
    draw.text((100, y), title_text, font=f_title, fill=(255, 255, 255))

    # Subtitle
    y += 64
    sub_text = slide.get("subtitle", "")
    draw.text((100, y), sub_text, font=f_sub, fill=(148, 163, 184))

    # Divider Line
    y += 42
    draw.line([100, y, w - 100, y], fill=(40, 50, 75), width=2)
    draw.line([100, y, 420, y], fill=(99, 102, 241), width=4)

    # Cards Grid
    y += 36
    cards = slide.get("cards", [])
    num_cards = len(cards)
    if num_cards > 0:
        card_w = (w - 200 - (num_cards - 1) * 26) // num_cards
        card_h = 580
        for i, (chead, cbody) in enumerate(cards):
            cx = 100 + i * (card_w + 26)
            cy = y
            # Card background
            draw.rounded_rectangle([cx, cy, cx + card_w, cy + card_h], radius=16, fill=(17, 24, 39), outline=(45, 55, 80), width=2)
            # Top accent bar
            accents = [(56, 189, 248), (129, 140, 248), (52, 211, 153), (245, 158, 11)]
            accent_col = accents[i % len(accents)]
            draw.rounded_rectangle([cx, cy, cx + card_w, cy + 8], radius=4, fill=accent_col)

            # Card Title
            draw.text((cx + 24, cy + 28), chead, font=f_card_head, fill=(255, 255, 255))
            draw.line([cx + 24, cy + 68, cx + card_w - 24, cy + 68], fill=(35, 45, 68), width=1)

            # Card Body wrapped
            wrapped = []
            for para in cbody.split("\n"):
                wrapped.extend(textwrap.wrap(para, width=28 if card_w < 440 else 36))
            by = cy + 84
            for line in wrapped:
                draw.text((cx + 24, by), line, font=f_card_body, fill=(203, 213, 225))
                by += 30

    # Bottom Footer
    draw.line([100, h - 80, w - 100, h - 80], fill=(30, 40, 60), width=1)
    foot_left = "Dr. Pierre C. Wepener • Founder & Chief Architect • Sentinari Master Walkthrough"
    foot_right = "21 Sentinel Disciplines • /ui/playground • /ui/patterns • /ui/qualia • /ui/learning"
    draw.text((100, h - 60), foot_left, font=f_foot, fill=(148, 163, 184))
    r_bbox = draw.textbbox((0, 0), foot_right, font=f_foot)
    rw = r_bbox[2] - r_bbox[0]
    draw.text((w - 100 - rw, h - 60), foot_right, font=f_foot, fill=(100, 116, 139))

    im.save(out_path, format="PNG")


async def generate_speech_audio(text: str, out_path: Path, voice: str = VOICE_NAME, max_retries: int = 4) -> None:
    """Generate high-quality neural voice narration using edge-tts with retry."""
    for attempt in range(1, max_retries + 1):
        try:
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
            comm = edge_tts.Communicate(text, voice)
            await comm.save(str(out_path))
            if out_path.exists() and out_path.stat().st_size > 1000:
                return
        except Exception as e:
            print(f"    [Retry {attempt}/{max_retries}] voiceover attempt: {e}")
            if attempt == max_retries:
                fallback_voice = "en-US-ChristopherNeural" if voice != "en-US-ChristopherNeural" else "en-US-GuyNeural"
                print(f"    Switching to fallback voice {fallback_voice}...")
                comm = edge_tts.Communicate(text, fallback_voice)
                await comm.save(str(out_path))
                return
            await asyncio.sleep(2.0 * attempt)


def get_audio_duration_seconds(audio_path: Path, ffmpeg_exe: str) -> float:
    """Extract exact audio duration in seconds using ffmpeg."""
    cmd = [ffmpeg_exe, "-i", str(audio_path)]
    p = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
    if m:
        h, mn, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
        return h * 3600 + mn * 60 + s
    return 30.0


def build_slide_video_segment(slide_img: Path, audio_file: Path, out_segment: Path, duration: float, ffmpeg_exe: str) -> None:
    """Create a video segment from a still slide and audio file."""
    dur = duration + 0.5
    cmd = [
        ffmpeg_exe,
        "-y",
        "-loop", "1",
        "-i", str(slide_img),
        "-i", str(audio_file),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-t", f"{dur:.2f}",
        str(out_segment),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def concatenate_segments(segment_list: list[Path], final_output: Path, ffmpeg_exe: str, list_filename: str = "concat_list.txt") -> None:
    """Concatenate video segments into an MP4 file."""
    concat_txt = OUTPUT_DIR / list_filename
    with open(concat_txt, "w", encoding="utf-8") as f:
        for s in segment_list:
            clean_p = str(s.resolve()).replace("\\", "/")
            f.write(f"file '{clean_p}'\n")

    cmd = [
        ffmpeg_exe,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_txt),
        "-c", "copy",
        str(final_output),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


async def main_pipeline():
    """Main execution pipeline: renders slides, voiceovers, section clips, and master video."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = get_ffmpeg_exe()
    print("=" * 80)
    print("SENTINARI MASTER WORKSPACE & ARCHITECTURE WALKTHROUGH VIDEO PIPELINE")
    print(f"Author & Chief Architect: Dr. Pierre C. Wepener")
    print(f"FFmpeg binary: {ffmpeg_exe}")
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 80)

    slide_segments_map: dict[str, Path] = {}
    total_master_duration = 0.0

    # 1. Render all 12 slides and narrations
    for idx, slide in enumerate(SLIDES_DATA, start=1):
        sid = slide["id"]
        print(f"\n[{idx}/12] Processing {sid}: {slide['title'][:40]}...")

        audio_path = OUTPUT_DIR / f"{sid}_narration.mp3"
        seg_path = OUTPUT_DIR / f"{sid}_segment.mp4"
        img_path = OUTPUT_DIR / f"{sid}_slide.png"

        # Check if already rendered and valid
        if seg_path.exists() and seg_path.stat().st_size > 50000 and audio_path.exists() and audio_path.stat().st_size > 1000:
            duration = get_audio_duration_seconds(audio_path, ffmpeg_exe)
            total_master_duration += duration
            print(f"  -> Segment already cached ({seg_path.stat().st_size / 1024:.1f} KB, {duration:.1f}s), skipping render.")
            slide_segments_map[sid] = seg_path
            continue

        print(f"  -> Synthesizing neural voiceover ({VOICE_NAME})...")
        await generate_speech_audio(slide["script"], audio_path)
        duration = get_audio_duration_seconds(audio_path, ffmpeg_exe)
        total_master_duration += duration
        print(f"  -> Audio duration: {duration:.1f}s")

        print(f"  -> Rendering 1920x1080 HD slide...")
        render_slide_image(slide, img_path)

        print(f"  -> Rendering video segment with FFmpeg...")
        build_slide_video_segment(img_path, audio_path, seg_path, duration, ffmpeg_exe)
        slide_segments_map[sid] = seg_path

    # 2. Compile individual Section Videos
    print("\n" + "=" * 80)
    print("COMPILING 6 INDIVIDUAL SECTION VIDEOS...")
    print("=" * 80)
    for sec in SECTIONS_CONFIG:
        sec_segs = [slide_segments_map[sid] for sid in sec["slides"]]
        sec_out = OUTPUT_DIR / sec["out_filename"]
        print(f"Section {sec['section_num']}: {sec['section_title']} -> {sec_out.name}")
        concatenate_segments(sec_segs, sec_out, ffmpeg_exe, list_filename=f"concat_{sec['section_id']}.txt")

    # 3. Compile Master Walkthrough Video
    all_segments = [slide_segments_map[slide["id"]] for slide in SLIDES_DATA]
    print("\n" + "=" * 80)
    print(f"Concatenating all 12 segments into Master Walkthrough Video...")
    print(f"Total calculated runtime: {total_master_duration / 60:.2f} minutes")
    concatenate_segments(all_segments, MASTER_VIDEO_PATH, ffmpeg_exe, list_filename="concat_master_list.txt")

    size_mb = MASTER_VIDEO_PATH.stat().st_size / (1024 * 1024)
    print("=" * 80)
    print(f"SUCCESS! Master Walkthrough Video Rendered:")
    print(f"File: {MASTER_VIDEO_PATH}")
    print(f"Size: {size_mb:.2f} MB")
    print(f"Duration: {total_master_duration / 60:.2f} minutes (~{int(total_master_duration)} seconds)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main_pipeline())
