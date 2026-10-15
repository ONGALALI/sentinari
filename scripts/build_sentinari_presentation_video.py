#!/usr/bin/env python3
"""Automated Video & Narration Production Pipeline for Sentinari.

Conceived, Researched & Developed by Dr. Pierre C. Wepener.
Synthesizes professional neural voiceover narration, renders 1080p Full HD
cinematic presentation slides, and compiles the final 10-minute MP4 video.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

try:
    import edge_tts
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFont
except ImportError as ex:
    print(f"Missing dependency: {ex}. Run: pip install edge-tts pillow imageio-ffmpeg")
    sys.exit(1)

OUTPUT_DIR = Path("D:/Sentinari/constitution/video_assets")
FINAL_VIDEO_PATH = Path("D:/Sentinari/constitution/Sentinari_10_Minute_Presentation.mp4")
VOICE_NAME = "en-US-AndrewNeural"  # Professional, authoritative, natural documentary narrator

SLIDES_DATA = [
    {
        "id": "slide_01",
        "category": "FOUNDATIONAL BREAKTHROUGH",
        "title": "SENTINARI: RESPONSIBLE INTELLIGENCE",
        "subtitle": "A Sovereign Epistemic Architecture in Service of Society",
        "badge": "SOLE INDEPENDENT AUTHORSHIP • 100% SELF-FUNDED",
        "cards": [
            ("Core Mission", "To act as an external, objective, and symbiotic mirror—reducing the distance between material reality and human understanding across 21 scientific disciplines."),
            ("Author & Architect", "Conceived, researched, designed, and engineered entirely on personal initiative by Dr. Pierre C. Wepener, free from institutional or corporate capture."),
            ("Governing Axiom", "Empirical material reality, verifiable physical telemetry, and systemic cause-and-effect unconditionally supersede administrative and corporate narratives."),
        ],
        "script": (
            "In the twenty-first century, humanity faces a profound crisis: not a lack of information, but a dangerous "
            "imbalance in who controls it. Today, global monopolies and sovereign institutions possess continuous, real-time "
            "telemetry, private supply chain intelligence, and regulatory legal shields. Meanwhile, the public, independent "
            "researchers, and the everyday working person are left on the outside—receiving curated narratives, lagging "
            "statistics, and unexpected economic shocks. When complex global systems fail, the catastrophic risk is offloaded "
            "onto the citizen. To solve this, I created Sentinari. Sentinari is not another conversational chatbot, and it is "
            "not an engine designed to replace human labor. Sentinari is a new discipline: Responsible Intelligence. Conceived "
            "and engineered entirely on my own initiative, Sentinari was 100% self-funded to ensure zero corporate capture or "
            "institutional bureaucracy. Its singular mission is to act as an objective, symbiotic mirror—reducing the distance "
            "between material reality and human understanding."
        ),
    },
    {
        "id": "slide_02",
        "category": "THE SYSTEMIC PROBLEM",
        "title": "THE CRISIS OF INFORMATION ASYMMETRY",
        "subtitle": "Why Unconstrained Generative AI & Monopolies Threaten Societal Equilibrium",
        "badge": "EPISTEMIC ASYMMETRY DIVIDE",
        "cards": [
            ("The Monopolies (Corporations & States)", "Possess live supply-chain telemetry, proprietary predictive models, and legal apparatuses to insulate themselves from systemic downside."),
            ("The Public & Working Class", "Receive lagging marketing hype, speculative news, and bureaucratic customer service walls. When systems collapse, the cost is borne by individuals."),
            ("Algorithmic Hallucination", "Commercial LLMs maximize persuasive engagement and plausible text rather than verifiable mathematical provenance, accelerating societal disorientation."),
        ],
        "script": (
            "Why does society urgently require this discipline? Look closely at the structural imbalance in the world today. "
            "Large tech conglomerates and financial institutions operate with massive data moats. They track physical logistics, "
            "microeconomic indicators, and legal statutory developments in real time. But the everyday citizen and the small business "
            "owner operate in the dark. Furthermore, mainstream artificial intelligence models suffer from what we classify as "
            "algorithmic distortion: they are trained to predict the next plausible token, not to remain faithful to physical "
            "truth. They hallucinate facts, amplify historical biases, and optimize for user retention rather than empirical "
            "integrity. Sentinari was engineered as an automated equalizer—a system that levels this playing field by applying "
            "rigorous, unmediated scientific evidence symmetrically to all actors."
        ),
    },
    {
        "id": "slide_03",
        "category": "ETHICAL GOVERNANCE",
        "title": "THE 100-YEAR CONSTITUTION",
        "subtitle": "The Inviolable Laws Governing Sentinari's Reasoning Engine",
        "badge": "PERPETUAL PUBLIC TRUST • ARTICLES I - VIII",
        "cards": [
            ("Article I: The Axiom of Material Reality", "Reality is defined strictly as empirical material truth and verifiable telemetry. Reality always supersedes institutional narratives."),
            ("Article II: The Neutral Illuminator", "Sentinari is an illuminator, not an instrument of punishment. It maintains zero corporate enemies—only active, dynamic hypotheses."),
            ("Article III: Systematic Humility", "Zero institutional pride. The instant superior counter-evidence emerges, confidence scores degrade and the state recalibrates instantaneously."),
            ("Article IV: Declaration of Inadequacy", "Silence is a metric of absolute integrity. When evidence is insufficient, the system is constitutionally bound to state: 'Evidence is currently insufficient.'"),
        ],
        "script": (
            "At the heart of Sentinari is an unyielding Constitution written to endure for the next one hundred years. "
            "While commercial AI models optimize for persuasive engagement, Sentinari is constitutionally bound to three "
            "foundational laws. First: The Neutral Illuminator Doctrine. Sentinari has zero corporate enemies and zero "
            "ideological loyalties—only active hypotheses. If uncovering evidence exposes corporate liability or structural "
            "fragility, that output is not hostility, but the unmediated reflection of material reality. Second: Systematic "
            "Humility. The moment a conclusion is contradicted by superior data provenance, the system is constitutionally "
            "mandated to degrade its prior confidence scores with zero sunk-cost bias. And third: The Declaration of Inadequacy. "
            "If empirical evidence is insufficient, Sentinari is constitutionally mandated to decline speculation and state "
            "openly that data is insufficient. In an era of AI hallucination, intellectual silence is the highest metric of integrity."
        ),
    },
    {
        "id": "slide_04",
        "category": "PHILOSOPHICAL METHODOLOGY",
        "title": "ARISTOTLE'S FOUR CAUSES APPLIED TO AI",
        "subtitle": "A Grounded Metaphysical Blueprint for Autonomous Intelligence",
        "badge": "DOCTRINE OF CAUSALITY",
        "cards": [
            ("1. Material Cause (Hyle)", "21 Sentinel Scientific Fields + live global statistical APIs (OpenAlex, PubMed, OECD, BEA, IMF, Eurostat) + high-fidelity document OCR data rooms."),
            ("2. Formal Cause (Eidos)", "7-Dimensional Coupled Bell-Curve Assessment Matrix, Net Sustainable Impact Score (NSIS), and the 15-Indicator R&D Validation Framework."),
            ("3. Efficient Cause (Kinesis)", "Google Cloud Run serverless microservices + Google Cloud SQL PostgreSQL 16 with native pgvector 0.8.5 + Vertex AI Gemini & Gemma gateway."),
            ("4. Final Cause (Telos)", "Responsible Intelligence in service of human agency, eliminating information asymmetry, protecting the working person, and planetary stewardship."),
        ],
        "script": (
            "To ensure complete architectural rigor, Sentinari is engineered directly upon Aristotle's Doctrine of the Four "
            "Causes. In metaphysics, a complete understanding of any entity requires understanding what it is made of, what "
            "formal structure it embodies, what operational force drives it, and what ultimate purpose it serves. In Sentinari, "
            "the Material Cause is twenty-one peer-reviewed scientific fields and live international statistical telemetry. "
            "Its Formal Cause is our seven-dimensional Coupled Bell-Curve Matrix and mathematical proofs. Its Efficient Cause is "
            "an autoscaling Google Cloud architecture combining pgvector semantic indexing with Gemini and Gemma LLM orchestration. "
            "And its Final Cause is the protection of human agency, labor stability, and societal flourishing."
        ),
    },
    {
        "id": "slide_05",
        "category": "INGESTION & DATA SCIENCE",
        "title": "AUTOMATED OPEN DATA PIPELINES",
        "subtitle": "Continuous Ingestion Across 21 Disciplines with Cryptographic Provenance",
        "badge": "STRICT FULL-TEXT PROVENANCE",
        "cards": [
            ("OpenAlex Integration", "Over 250 million peer-reviewed scientific works indexed by citation authority, DOI, and open-access full-text retrieval."),
            ("PubMed & Life Sciences", "Real-time biomedical, epidemiological, and public health literature monitoring for health and environmental fields."),
            ("Global Macroeconomic APIs", "Live automated SDMX/JSON ingestion from the OECD, US Bureau of Economic Analysis (BEA), IMF, and Eurostat."),
            ("Document & PDF Engine", "Multi-modal OCR fallback, atomic chunking, sha256 cryptographic hashing, and complete token span verification."),
        ],
        "script": (
            "Let us examine the engine under the hood. Sentinari ingests and synthesizes high-velocity scientific and economic "
            "data through automated, continuous pipelines. Through native SDMX and REST integrations, Sentinari interfaces "
            "directly with OpenAlex for academic literature, PubMed for life sciences, and global economic agencies including the "
            "OECD, the United States Bureau of Economic Analysis, the International Monetary Fund, and Eurostat. No statement is ever "
            "generated by Sentinari without complete, full-text provenance and verifiable digital object identifiers. When documents "
            "or PDFs are uploaded into any of our twenty-one field data rooms, our ingestion pipeline extracts clean text, computes "
            "cryptographic checksums, segments text into atomic semantic chunks, and binds each chunk to verified metadata."
        ),
    },
    {
        "id": "slide_06",
        "category": "CLOUD ARCHITECTURE",
        "title": "GOOGLE CLOUD & PGVECTOR BACKBONE",
        "subtitle": "Sub-Second Hybrid Semantic Retrieval on Enterprise Infrastructure",
        "badge": "PRODUCTION CLOUD DEPLOYMENT",
        "cards": [
            ("Google Cloud Run", "Containerized serverless microservices automatically scaling from zero to handle intensive concurrent pattern extraction jobs."),
            ("Google Cloud SQL PostgreSQL 16", "Enterprise database utilizing native pgvector 0.8.5 for high-dimensional embedding similarity searches ($L_2$ and Cosine)."),
            ("Hybrid Search Architecture", "Combines relational filtering (scientific field, timestamp, source type) with dense vector semantic matching."),
            ("Zero-Hallucination AI Gateway", "Google Gemini 1.5/2.5 Flash and Gemma models operating under strict open-book boundary guardrails."),
        ],
        "script": (
            "The infrastructure powering Sentinari is engineered for resilience, speed, and absolute data integrity. Deployed on "
            "Google Cloud Run in the us-central1 region, our containerized microservices scale dynamically to handle heavy analytical "
            "workloads. For memory and retrieval, we run Google Cloud SQL PostgreSQL 16 equipped with native pgvector. This allows "
            "Sentinari to perform hybrid queries—filtering by exact scientific discipline, date ranges, and document source, while "
            "executing sub-second vector distance calculations across hundreds of thousands of atomic embeddings. All reasoning is "
            "orchestrated through our AI Gateway with Google Gemini and Gemma models, running in pure open-book mode where answers "
            "must be directly grounded in indexed library evidence."
        ),
    },
    {
        "id": "slide_07",
        "category": "FLAGSHIP DELIVERABLE 1",
        "title": "NEW PATTERN DISCOVERY WORKSPACE",
        "subtitle": "Cross-Functional Pattern Recognition Breaking Disciplinary Silos",
        "badge": "INTERDISCIPLINARY DISCOVERY ENGINE",
        "cards": [
            ("Breaking Academic Silos", "Specialists in one field rarely monitor others. Sentinari continuously maps correlations between economics, physics, metallurgy, and climate science."),
            ("Embryonic Hypotheses", "Identifies subtle anomalies and systemic friction points where multi-domain interactions create emergent societal risks or technological breakthroughs."),
            ("Interactive Concertina Cards", "Live in the workspace (/ui/patterns) with real-time confidence tracking, cross-field tags, primary source excerpts, and 5-stage progress."),
        ],
        "script": (
            "Now, let us examine the flagship deliverable of Sentinari: the New Pattern Discovery Workspace. Traditional research "
            "is trapped in rigid disciplinary silos. An economist studying supply chains rarely cross-references materials science on "
            "semiconductor metallurgy or climatological telemetry. Sentinari breaks these silos—continuously mapping connections "
            "across twenty-one fields to detect embryonic patterns before they surface in conventional metrics. In the workspace, each "
            "discovery is presented as an interactive concertina card, displaying quantified confidence tracks, interdisciplinary "
            "badges, primary evidence quotes, and real-time development indicators."
        ),
    },
    {
        "id": "slide_08",
        "category": "STRATEGIC ROI",
        "title": "WHY CONDUCT SUPPLEMENTARY STUDIES?",
        "subtitle": "The Asymmetric Strategic Value for Investors, Boards & Research Institutions",
        "badge": "ASYMMETRIC STRATEGIC ADVANTAGE",
        "cards": [
            ("1. Early-Warning De-risking", "Identifies structural supply chain and geopolitical friction 12 to 24 months before it surfaces in backward-looking financial metrics."),
            ("2. First-Mover Patent Advantage", "Illuminates hidden cross-domain technological mechanics (e.g. quantum chemistry applied to energy storage) before industry awareness."),
            ("3. Zero Speculative R&D Waste", "Replaces blind trial-and-error with pre-validated hypotheses, curated APA 7th bibliographies, and mathematical formalisms."),
        ],
        "script": (
            "Why should global investors, corporate boards, or research foundations conduct a supplementary study into an identified "
            "Sentinari pattern? The answer is asymmetric strategic advantage. First: Early-Warning Risk De-risking. Sentinari uncovers "
            "structural supply chain and geopolitical friction twelve to twenty-four months before it surfaces in backward-looking "
            "quarterly earnings or macroeconomic reports. Second: Proprietary First-Mover Advantage. By connecting cross-domain "
            "discoveries early, organizations can secure foundational patents and technological leadership before competitors even "
            "recognize the correlation. And third: Zero Speculative R&D Waste. Sentinari eliminates guesswork by providing researchers "
            "with empirical evidence, curated bibliographies, and mathematical formalisms from day one."
        ),
    },
    {
        "id": "slide_09",
        "category": "FLAGSHIP DELIVERABLE 2",
        "title": "THE UNIFIED 15-INDICATOR R&D PAPER",
        "subtitle": "Transforming Raw Multi-Domain Data into Publication-Grade Scientific Papers",
        "badge": "5 SECTIONS • 15 RIGOROUS INDICATORS",
        "cards": [
            ("1. Front Matter & 2. Intro", "Title, word-counted Abstract, Technical Keywords, Problem Statement, Formal Hypothesis, and Literature Review with inline APA 7th citations [1], [2]."),
            ("3. Methodology & Design", "Conceptual System Architecture data flow, Technical Specifications, and Implementation Process with KaTeX mathematical proofs."),
            ("4. Testing & 5. Back Matter", "Experimental Testbed, 7-D Assessment Matrix Results Table, Benchmark Discussion, Conclusion, Future Scope, References, and Appendices."),
            ("5.5 Recommended Solutions", "Gemma-synthesized concrete, actionable solutions to the problem addressed—or the constitutional fallback when evidence is incomplete."),
        ],
        "script": (
            "Every pattern is a paper in embryo. With one click, Sentinari delivers a publication-ready, fifteen-indicator "
            "Unified R&D Validation Paper. Structured across five rigorous academic sections, the paper begins with an abstract and "
            "formal hypothesis formulation, supported by an academic literature review with linked APA seventh edition citations. "
            "It outlines system architecture flows, technical specifications, and mathematical proofs rendered with KaTeX. "
            "In Section Four, it presents the experimental testbed and empirical results. And in Section Five, our Gemma intelligence "
            "engine synthesizes the literature and experimental discussion to formulate concrete, actionable Recommended Solutions "
            "to the problem addressed. If the evidence is incomplete, it invokes our constitutional fallback, ensuring zero speculation."
        ),
    },
    {
        "id": "slide_10",
        "category": "FLAGSHIP DELIVERABLE 3",
        "title": "THE 7-D ASSESSMENT MATRIX",
        "subtitle": "Interactive Sliding Scale Simulator with Closed-Form Gaussian Interdependence",
        "badge": "MATHEMATICALLY JUSTIFIED • NOT AN LLM GUESS",
        "cards": [
            ("7 Core Dimensions", "Knowledge (K), Intelligence (I), Decision (D), Human Agency (H), Societal (S), Ethics (E), Risk (R). Normalized operating scale $x_i \\in [0, 10]$."),
            ("Gaussian Impact Equation", "$S_i(x_i) = A_i \\cdot \\exp\\left(-\\frac{(x_i - \\mu_i)^2}{2\\sigma_i^2}\\right)$. Governs dimensional potency, optimal center $\\mu_i$, and tolerance $\\sigma_i$."),
            ("Net Sustainable Impact Score", "$\\text{NSIS} = \\sum_{i=1}^{7} W_i \\cdot S_i(x_i)$. Quantifies the net systemic equilibrium across all interconnected dimensions."),
            ("Dynamic Sliding Scale (Rules A, B, C)", "Manually moving any slider dynamically shifts interdependent optimal centers and recalculates the Net Sustainability Envelope."),
        ],
        "script": (
            "Now consider our most mathematically profound deliverable: the Assessment Matrix with its interactive sliding scale. "
            "Rather than arbitrary AI scores, Sentinari evaluates every discovery across seven core dimensions: Knowledge, Intelligence, "
            "Decision, Human Agency, Societal Impact, Ethics, and Risk. Each dimension operates along a zero-to-ten operating scale "
            "governed by closed-form Gaussian bell curves. When a user manually shifts any slider in our live simulator—for instance, "
            "pushing Decision intensity to nine out of ten—our engine applies coupled Interdependence Rules. It dynamically recalculates "
            "the Net Sustainable Impact Score and demonstrates mathematically how over-optimizing one metric causes systemic risk "
            "envelopes to expand. It is an un-falsifiable flight simulator for high-stakes strategic decisions."
        ),
    },
    {
        "id": "slide_11",
        "category": "SOCIETAL VALUE",
        "title": "THE WORKING PERSON'S TRANSITION SHIELD",
        "subtitle": "Democratizing Strategic Foresight to Protect Human Labor from Sudden Disruption",
        "badge": "HUMAN AGENCY & LABOR PROTECTION",
        "cards": [
            ("The Silent Threat", "Technological and corporate shifts occur in boardrooms, leaving blue-collar, technical, and industrial workers blindsided by sudden obsolescence."),
            ("Early Transition Radar", "Sentinari identifies cross-domain transitions 12 to 24 months before crisis points, providing workers and unions with early navigational foresight."),
            ("Skill Adjacency Corridors", "Maps existing technical competencies to emerging technological demands, creating sustainable bridges rather than economic displacement."),
        ],
        "script": (
            "Who does Sentinari ultimately serve? The answer is society and the working person. Too often, technological shifts "
            "blindside the technician, the blue-collar worker, and the industrial specialist. Corporate decisions occur behind closed "
            "doors, leaving entire communities stranded when disruption strikes. Sentinari turns this dynamic on its head. By "
            "identifying systemic transitions years before they trigger crisis points, Sentinari provides workers, labor unions, "
            "and regional planners with an early-warning radar. It maps skill adjacencies, labor migration corridors, and sustainable "
            "adaptations—democratizing strategic intelligence that was once reserved for executive boardrooms."
        ),
    },
    {
        "id": "slide_12",
        "category": "INDEPENDENCE & INVESTMENT",
        "title": "AN INVITATION TO GLOBAL INVESTORS",
        "subtitle": "Sole Personal Initiative • Free of Bureaucracy • Built for Action-Oriented Partners",
        "badge": "PROPRIETARY CODEBASE • COPYRIGHT © DR. PIERRE C. WEPENER",
        "cards": [
            ("100% Independent Initiative", "Conceived and engineered solely by Dr. Pierre C. Wepener on personal initiative with zero institutional funding or university involvement."),
            ("Bypassing Committee Inertia", "Formal proposals submitted in early 2025 remain unaddressed in academic bureaucracy. Built independently to achieve immediate, working production status."),
            ("Strategic Investor Partnerships", "Actively engaging global technology investors, sovereign AI funds, and Google Cloud / DeepMind research alliances ready to deploy capital and scale."),
        ],
        "script": (
            "I want to make one thing unequivocally clear: Sentinari was developed entirely on my own initiative, without institutional "
            "funding or university involvement. While bureaucratic academic proposals presented in early 2025 remain unreviewed in "
            "committee inertia, Sentinari was built, validated, and deployed to production through independent determination. The "
            "codebase, mathematical framework, and intellectual property are my sole proprietary copyright. I am working hard for "
            "global investors, visionary technology leaders, and partners who actually make things happen. We are now opening discussions "
            "for strategic seed investment, compute sponsorship with Google Cloud and DeepMind, and deployment partnerships with "
            "organizations ready to pioneer Responsible Intelligence at global scale. If you are ready to back a breakthrough that "
            "bridges material reality, mathematical rigor, and human stewardship, join us. Thank you."
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
    f_badge = get_font(20, bold=True)
    f_cat = get_font(22, bold=True)
    f_title = get_font(52, bold=True)
    f_sub = get_font(28, bold=False)
    f_card_head = get_font(24, bold=True)
    f_card_body = get_font(20, bold=False)
    f_foot = get_font(20, bold=False)

    # Top Category & Badge Bar
    y = 65
    cat_text = slide.get("category", "SYSTEM SPECIFICATION")
    draw.text((100, y), cat_text, font=f_cat, fill=(129, 140, 248))

    badge_text = slide.get("badge", "SENTINARI")
    bbox = draw.textbbox((0, 0), badge_text, font=f_badge)
    bw = bbox[2] - bbox[0] + 32
    bh = 38
    bx = w - 100 - bw
    draw.rounded_rectangle([bx, y - 6, bx + bw, y - 6 + bh], radius=19, fill=(26, 34, 56), outline=(99, 102, 241), width=2)
    draw.text((bx + 16, y - 2), badge_text, font=f_badge, fill=(165, 180, 252))

    # Main Title
    y += 46
    title_text = slide.get("title", "")
    draw.text((100, y), title_text, font=f_title, fill=(255, 255, 255))

    # Subtitle
    y += 70
    sub_text = slide.get("subtitle", "")
    draw.text((100, y), sub_text, font=f_sub, fill=(148, 163, 184))

    # Divider Line
    y += 48
    draw.line([100, y, w - 100, y], fill=(40, 50, 75), width=2)
    draw.line([100, y, 380, y], fill=(99, 102, 241), width=4)

    # Cards Grid
    y += 40
    cards = slide.get("cards", [])
    num_cards = len(cards)
    if num_cards > 0:
        card_w = (w - 200 - (num_cards - 1) * 28) // num_cards
        card_h = 560
        for i, (chead, cbody) in enumerate(cards):
            cx = 100 + i * (card_w + 28)
            cy = y
            # Card background
            draw.rounded_rectangle([cx, cy, cx + card_w, cy + card_h], radius=16, fill=(17, 24, 39), outline=(45, 55, 80), width=2)
            # Top accent bar on each card
            accents = [(56, 189, 248), (129, 140, 248), (52, 211, 153), (245, 158, 11)]
            accent_col = accents[i % len(accents)]
            draw.rounded_rectangle([cx, cy, cx + card_w, cy + 8], radius=4, fill=accent_col)

            # Card Title
            draw.text((cx + 26, cy + 32), chead, font=f_card_head, fill=(255, 255, 255))
            draw.line([cx + 26, cy + 72, cx + card_w - 26, cy + 72], fill=(35, 45, 68), width=1)

            # Card Body wrapped
            import textwrap
            wrapped = []
            for para in cbody.split("\n"):
                wrapped.extend(textwrap.wrap(para, width=28 if card_w < 450 else 36))
            by = cy + 90
            for line in wrapped:
                draw.text((cx + 26, by), line, font=f_card_body, fill=(203, 213, 225))
                by += 32

    # Bottom Footer
    draw.line([100, h - 85, w - 100, h - 85], fill=(30, 40, 60), width=1)
    foot_left = "Dr. Pierre C. Wepener • Founder & Chief Architect • Sentinari Platform"
    foot_right = "Production Architecture: Google Cloud Run • Cloud SQL PostgreSQL 16 pgvector • Vertex AI"
    draw.text((100, h - 65), foot_left, font=f_foot, fill=(148, 163, 184))
    r_bbox = draw.textbbox((0, 0), foot_right, font=f_foot)
    rw = r_bbox[2] - r_bbox[0]
    draw.text((w - 100 - rw, h - 65), foot_right, font=f_foot, fill=(100, 116, 139))

    im.save(out_path, format="PNG")


async def generate_speech_audio(text: str, out_path: Path, voice: str = VOICE_NAME) -> None:
    """Generate high-quality neural voice narration using edge-tts."""
    comm = edge_tts.Communicate(text, voice)
    await comm.save(str(out_path))


def get_audio_duration_seconds(audio_path: Path, ffmpeg_exe: str) -> float:
    """Extract exact audio duration in seconds using ffprobe or ffmpeg."""
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
    # Add 0.5s padding to prevent abrupt audio cuts
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


def concatenate_segments(segment_list: list[Path], final_output: Path, ffmpeg_exe: str) -> None:
    """Concatenate all video segments into the master MP4 presentation."""
    concat_txt = OUTPUT_DIR / "concat_list.txt"
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
    """Main execution pipeline."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = get_ffmpeg_exe()
    print("=" * 72)
    print("SENTINARI AUTOMATED VIDEO PRODUCTION PIPELINE")
    print(f"Author & Chief Architect: Dr. Pierre C. Wepener")
    print(f"FFmpeg binary: {ffmpeg_exe}")
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 72)

    segment_files = []
    total_duration = 0.0

    for idx, slide in enumerate(SLIDES_DATA, start=1):
        sid = slide["id"]
        print(f"\n[{idx}/12] Processing {sid}: {slide['title'][:40]}...")

        # 1. Generate Voiceover Audio
        audio_path = OUTPUT_DIR / f"{sid}_narration.mp3"
        print(f"  -> Synthesizing neural voiceover ({VOICE_NAME})...")
        await generate_speech_audio(slide["script"], audio_path)
        duration = get_audio_duration_seconds(audio_path, ffmpeg_exe)
        total_duration += duration
        print(f"  -> Audio duration: {duration:.1f}s")

        # 2. Render 1080p Slide Graphic
        img_path = OUTPUT_DIR / f"{sid}_slide.png"
        print(f"  -> Rendering 1920x1080 HD slide...")
        render_slide_image(slide, img_path)

        # 3. Compile Segment Video
        seg_path = OUTPUT_DIR / f"{sid}_segment.mp4"
        print(f"  -> Rendering video segment with FFmpeg...")
        build_slide_video_segment(img_path, audio_path, seg_path, duration, ffmpeg_exe)
        segment_files.append(seg_path)

    # 4. Concatenate Final Master Video
    print("\n" + "=" * 72)
    print(f"Concatenating all 12 segments into master presentation video...")
    print(f"Total calculated runtime: {total_duration / 60:.2f} minutes")
    concatenate_segments(segment_files, FINAL_VIDEO_PATH, ffmpeg_exe)

    size_mb = FINAL_VIDEO_PATH.stat().st_size / (1024 * 1024)
    print(f"SUCCESS! Master Video Rendered:")
    print(f"File: {FINAL_VIDEO_PATH}")
    print(f"Size: {size_mb:.2f} MB")
    print(f"Duration: {total_duration / 60:.2f} minutes (~{int(total_duration)} seconds)")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main_pipeline())
