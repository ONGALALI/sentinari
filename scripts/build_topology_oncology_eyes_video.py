#!/usr/bin/env python3
"""
Sentinari Master Video Production: Topology, Oncology Precision & Eyes Vision Lab
================================================================================
Comprehensive, Element-by-Element Master Walkthrough Video with:
- Active On-Screen Focus Indicators (Pulsing Neon Callout Boxes & Focus Badges)
- High-Contrast Synchronized Subtitles / Lower-Third Caption Banners
- Professional Neural Voiceover (en-US-AndrewNeural)
- 1080p Full HD Cinematic Slides

Conceived, Researched & Engineered by Dr. Pierre C. Wepener
Institutional Affiliation: Inspirari Research Initiative & Sentinari Architecture
"""

from __future__ import annotations

import asyncio
import os
import shutil
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

OUTPUT_DIR = Path("D:/Sentinari/constitution/walkthrough_assets/topology_eyes")
MASTER_VIDEO_PATH = Path("D:/Sentinari/constitution/Sentinari_Topology_Oncology_and_Eyes_Master_Walkthrough.mp4")
STATIC_VIDEO_PATH = Path("D:/Sentinari/static/topology_oncology_eyes_walkthrough.mp4")
VOICE_NAME = "en-US-AndrewNeural"

SLIDES_DATA = [
    # -------------------------------------------------------------------------
    # SLIDE 1: SYSTEM SPECIFICATION & SOVEREIGN ARCHITECTURE
    # -------------------------------------------------------------------------
    {
        "id": "slide_01_architecture",
        "section": "SECTION 1: FOUNDATIONAL ARCHITECTURE",
        "category": "SOVEREIGN EPISTEMIC VISUAL ENGINE",
        "title": "TOPOLOGY, ONCOLOGY PRECISION & VISION LAB",
        "subtitle": "An Element-by-Element Master Guide to Sentinari's Topological Capabilities",
        "badge": "DR. PIERRE C. WEPENER  INSPIRARI RESEARCH",
        "active_index": 0,
        "active_label": "SOVEREIGN ARCHITECTURAL PARADIGM",
        "cards": [
            (
                "Sovereign Architectural Paradigm",
                "Replaces opaque deep-learning black boxes with coordinate-free algebraic topology, guaranteeing geometric invariance against tissue rotation, scaling, and staining drift."
            ),
            (
                "Two Integrated Laboratories",
                "Oncology Precision (/ui/oncology) for pharmacodynamic synergy and cytogenetics; Vision Lab (/ui/vision) for digital pathology and physical tissue simplicial homology."
            ),
            (
                "Constitutional Compliance",
                "Every diagnostic hypothesis is bound by the 100-Year Constitution, US FDA 21 CFR 312 / ICH S9 safety standards, and Gate 2 Net Sustainability Envelope (NSIS) laws."
            ),
        ],
        "script": (
            "Welcome to the official technical walkthrough of Sentinari's Topological Architecture, conceived, researched, and "
            "engineered by Dr. Pierre C. Wepener. In this master video, we inspect every element, report, metric, and clinical "
            "standard powering our two specialized medical environments: The Oncology Precision Workspace and the newly introduced "
            "Vision Lab. Instead of relying on fragile statistical approximations, Sentinari grounds clinical perception in the "
            "immutable laws of Topological Data Analysis."
        ),
        "subtitle": "Welcome to the technical walkthrough of Sentinari's Topological Architecture, conceived by Dr. Pierre C. Wepener."
    },

    # -------------------------------------------------------------------------
    # SLIDE 2: MATHEMATICAL FOUNDATIONS OF TDA
    # -------------------------------------------------------------------------
    {
        "id": "slide_02_math_tda",
        "section": "SECTION 2: MATHEMATICAL FORMALISMS",
        "category": "ALGEBRAIC TOPOLOGY & PERSISTENT HOMOLOGY",
        "title": "SIMPLICIAL COMPLEXES & TOPOLOGICAL INVARIANTS",
        "subtitle": "Vietoris-Rips vs. Delaunay Alpha-Complexes and the Stability Theorem",
        "badge": "HOMOLOGY GROUPS H_0, H_1, H_2",
        "active_index": 1,
        "active_label": "DELAUNAY ALPHA-COMPLEX O(N log N)",
        "cards": [
            (
                "Simplicial Filtration Theory",
                "Points expand spherical balls of radius epsilon. Overlaps form 0-simplices (vertices), 1-simplices (edges), and 2-simplices (triangles) to capture true shape."
            ),
            (
                "Delaunay Alpha-Complex O(N log N)",
                "Replaces standard Vietoris-Rips combinatorial explosion. Evaluates up to 50,000 cellular nuclei in 400 milliseconds while preserving the exact homotopy type."
            ),
            (
                "Bottleneck Stability Guarantee",
                "Mathematically proven: distance between persistence diagrams cannot exceed the supremum norm of empirical perturbation: d_B(D_f, D_g) <= ||f - g||_inf."
            ),
        ],
        "script": (
            "Notice our focus on the second panel: The Delaunay Alpha Complex. Standard Vietoris-Rips filtration scales combinatorially "
            "at two to the power of N, which would freeze clinical hardware on whole-slide biopsy images. Sentinari solves this by utilizing "
            "Alpha Complexes dual to the Delaunay triangulation, reducing algorithmic complexity to O of N log N while preserving the "
            "exact homotopy type and persistent homology groups H zero and H one."
        ),
        "subtitle": "Notice the active focus: Alpha Complexes reduce complexity to O(N log N), ensuring sub-second execution on massive slides."
    },

    # -------------------------------------------------------------------------
    # SLIDE 3: ONCOLOGY PRECISION WORKSPACE (/ui/oncology)
    # -------------------------------------------------------------------------
    {
        "id": "slide_03_oncology_workspace",
        "section": "SECTION 3: ONCOLOGY PRECISION",
        "category": "CLINICAL PHARMACODYNAMICS & GENETICS",
        "title": "CHOU-TALALAY SYNERGY & CYTOGENETIC STRATIFICATION",
        "subtitle": "Quantitative Adjuvant Modeling Under ELN 2022 Consensus Guidelines",
        "badge": "ONCOLOGY PRECISION  /ui/oncology",
        "active_index": 0,
        "active_label": "CHOU-TALALAY COMBINATION INDEX (CI)",
        "cards": [
            (
                "Chou-Talalay Combination Index (CI)",
                "Quantifies drug interaction: CI < 0.3 (Strong Synergism), 0.7-0.9 (Moderate Synergism), 0.9-1.1 (Additive), and CI > 1.1 (Antagonism requiring immediate regimen rejection)."
            ),
            (
                "ELN 2022 Cytogenetic Risk Matrix",
                "Automates stratification across Favorable (inv16, t8;21), Intermediate, and Adverse categories (TP53 mutations, complex karyotypes, MECOM rearrangements)."
            ),
            (
                "Interactive Dosage Sliders",
                "Adjust Venetoclax, Azacitidine, and Daunorubicin concentrations dynamically to project clonal blast clearance and drug-drug metabolic impact."
            ),
        ],
        "script": (
            "Now looking at the active element on the left: The Chou-Talalay Combination Index in the Oncology Precision Workspace. "
            "Here, adjuvant regimens are quantitatively evaluated against the median-effect equation. A Combination Index below zero point "
            "nine indicates true pharmacological synergism, while values exceeding one point one trigger an immediate antagonism warning. "
            "This is cross-referenced with the European LeukemiaNet 2022 cytogenetic risk classification."
        ),
        "subtitle": "Inspecting the Chou-Talalay Combination Index: Quantifies synergistic blast clearance below CI 0.9."
    },

    # -------------------------------------------------------------------------
    # SLIDE 4: REGULATORY STANDARDS & CLINICAL TRIALS RETRIEVAL
    # -------------------------------------------------------------------------
    {
        "id": "slide_04_regulatory_trials",
        "section": "SECTION 4: REGULATORY GOVERNANCE",
        "category": "STANDARDS, AUDIT TRAILS & EVIDENCE",
        "title": "US FDA 21 CFR 312, ICH S9 & CLINICAL TRIAL RETRIEVAL",
        "subtitle": "Real-Time Highest-Achievement Study Extraction and Non-Clinical Safety Gates",
        "badge": "US FDA 21 CFR 312  ICH S9 NON-CLINICAL SAFETY",
        "active_index": 1,
        "active_label": "REAL-TIME CLINICAL TRIALS RETRIEVER",
        "cards": [
            (
                "FDA 21 CFR 312 IND Guardrails",
                "Enforces Investigational New Drug application requirements, ensuring all simulated dose regimens strictly adhere to documented clinical trial safety thresholds."
            ),
            (
                "Real-Time Clinical Trials Retriever",
                "Directly queries ClinicalTrials.gov for completed Phase 2 and 3 oncology trials, extracting verified overall response rates (ORR) and progression-free survival."
            ),
            (
                "ICH S9 Toxicological Law",
                "Defines non-clinical evaluation parameters for anticancer pharmaceuticals, safeguarding patient safety by flagging dose-limiting organ toxicities."
            ),
        ],
        "script": (
            "We now focus on the central element: The Real-Time Clinical Trials Retriever. Under US FDA Title 21 CFR 312 and International "
            "Council for Harmonisation S9 guidelines, Sentinari cross-examines proposed adjuvant combinations against verified, completed "
            "Phase Three human clinical trials. The system extracts progression-free survival data and overall response rates, guaranteeing "
            "that theoretical simulations remain anchored in validated clinical evidence."
        ),
        "subtitle": "Active Focus: Real-Time Clinical Trials Retriever anchoring simulations in FDA 21 CFR 312 evidence."
    },

    # -------------------------------------------------------------------------
    # SLIDE 5: GIVING SENTINARI EYES  THE VISION LAB (/ui/vision)
    # -------------------------------------------------------------------------
    {
        "id": "slide_05_eyes_vision_lab",
        "section": "SECTION 5: VISION LAB ARCHITECTURE",
        "category": "THE EYES WORKSPACE  /ui/vision",
        "title": "FROM SPATIAL PIXELS TO SIMPLICIAL COMPLEXES",
        "subtitle": "Ruifrok-Johnston Color Deconvolution & Coordinate-Free Centroid Extraction",
        "badge": "RUIFROK-JOHNSTON OPTICAL DENSITY SEPARATION",
        "active_index": 0,
        "active_label": "RUIFROK-JOHNSTON COLOR DECONVOLUTION",
        "cards": [
            (
                "Ruifrok-Johnston Color Deconvolution",
                "Separates optical density absorption vectors. Isolates blue-violet Hematoxylin (nuclear chromatin) from pink Eosin (cytoplasm/stroma), eliminating false centroids from collagen."
            ),
            (
                "Spatial Coordinate Matrix (N, 2)",
                "Converts raw microscopy frames into discrete (x, y) cellular coordinates. Distance epsilon now represents true physical tissue micrometers rather than pixel coordinates."
            ),
            (
                "Dual-Panel Visual Canvas",
                "Left panel renders the physical tissue with live simplicial edges; right panel tracks the synchronized topological persistence barcode."
            ),
        ],
        "script": (
            "Shifting to our new Vision Lab workspace at /ui/vision, observe the first highlighted card: Ruifrok-Johnston Color Deconvolution. "
            "To give Sentinari reliable sight, we cannot simply convert an image to grayscale. Ruifrok optical density separation extracts "
            "the pure Hematoxylin absorption vector, isolating cellular nuclei while discarding stroma and collagen artifacts. This creates "
            "a clean spatial coordinate matrix where distances have real physical and biological meaning."
        ),
        "subtitle": "Inspecting Ruifrok-Johnston Color Deconvolution: Isolates cellular chromatin from stroma to prevent false centroids."
    },

    # -------------------------------------------------------------------------
    # SLIDE 6: PERSISTENCE SPECTRUM, H_1 CYCLES & FILTRATION
    # -------------------------------------------------------------------------
    {
        "id": "slide_06_persistence_spectrum",
        "section": "SECTION 6: TOPOLOGICAL METRICS",
        "category": "BARCODES & SPECTRAL FILTRATION",
        "title": "H_0 CLUSTERS, H_1 LOOPS & THE DYNAMIC EPSILON SLIDER",
        "subtitle": "Tracking Microvascular Cavities, Tissue Lumens, and Persistent Homology Lifespans",
        "badge": "DYNAMIC FILTRATION RADIUS EPSILON IN [0.05, 1.00]",
        "active_index": 1,
        "active_label": "PERSISTENT H_1 LOOPS & LUMEN CYCLES",
        "cards": [
            (
                "H_0 Connected Components",
                "Tracks the birth and merging of individual cellular clusters as the filtration radius grows, modeling spatial clonal density."
            ),
            (
                "Persistent H_1 Loops & Lumen Cycles",
                "Captures 1-dimensional topological cavities: disorganized microvascular loops, abnormal angiogenic rings, and ductal carcinoma lumens that survive across wide epsilon intervals."
            ),
            (
                "Dynamic Threshold Slider (epsilon)",
                "The orange dashed baseline indicates the clinician's active filtration radius, instantly updating active edges and glowing cavity indicators on screen."
            ),
        ],
        "script": (
            "Focusing on the center panel: Persistent H One Loops and Lumen Cycles. On the live barcode spectrum, blue bars depict "
            "topological features. When a feature is short-lived, the math proves it is empirical noise. However, when an H One cycle "
            "survives across a wide filtration span, it signifies a real physical tissue cavity—such as an aberrant angiogenic loop in ductal "
            "carcinoma or disordered microvascular networking. Adjusting the orange epsilon slider instantly recalibrates active cycles."
        ),
        "subtitle": "Active Focus: H_1 Persistent Loops mathematically identify abnormal vascular and ductal tissue cavities."
    },

    # -------------------------------------------------------------------------
    # SLIDE 7: SHANNON ENTROPY REDUCTION & GATE 2 NSIS
    # -------------------------------------------------------------------------
    {
        "id": "slide_07_entropy_gate2",
        "section": "SECTION 7: THERMODYNAMIC GOVERNANCE",
        "category": "INFORMATION THEORY & EQUILIBRIUM",
        "title": "TOPOLOGICAL SHANNON ENTROPY & GATE 2 NSIS",
        "subtitle": "Thermodynamic Verification: Persistent Signal Compresses Entropy (Delta H <= -1.0)",
        "badge": "NET SUSTAINABILITY ENVELOPE (NSIS) RUBRIC",
        "active_index": 0,
        "active_label": "TOPOLOGICAL SHANNON ENTROPY (Delta H)",
        "cards": [
            (
                "Topological Shannon Entropy (Delta H)",
                "Calculated from the normalized lifespan probability distribution of H_1 bars. Genuine biophysiological structure compresses entropy (Delta H <= -1.0 bits), whereas noise expands it."
            ),
            (
                "Gate 2 NSIS Hypothesis Gatekeeper",
                "When Delta H satisfies the reduction law, Gate 2 awards an approved NSIS score of 0.715. If random noise dominates, the score drops to 0.361 and flags an alert."
            ),
            (
                "7-Dimensional Assessment Matrix",
                "Integrates intelligence and scientific indices, ensuring visual perception remains strictly in trajectory equilibrium."
            ),
        ],
        "script": (
            "Notice our focus on the primary metric card: Topological Shannon Entropy, Delta H. In Sentinari's thermodynamic philosophy, "
            "meaningful geometric signal compresses entropy. By calculating the probability distribution of persistence bar lifespans, "
            "the system determines whether the tissue layout exhibits organized structure. A Delta H reduction of minus one point zero bits "
            "or greater satisfies Gate Two, verifying Net Sustainability Envelope equilibrium."
        ),
        "subtitle": "Active Focus: Delta H Shannon Entropy Reduction proves geometric signal compression over random noise."
    },

    # -------------------------------------------------------------------------
    # SLIDE 8: HEALTHY BLUEPRINTS, DISTANCES & LPAD SCANNER
    # -------------------------------------------------------------------------
    {
        "id": "slide_08_blueprints_lpad",
        "section": "SECTION 8: CLINICAL PROTOCOLS",
        "category": "BLUEPRINTS, METRICS & HARDWARE",
        "title": "HEALTHY NIH BLUEPRINTS, WASSERSTEIN & LPAD CAPTURE",
        "subtitle": "Zero-Friction Optical Scanner, A4 Auto-Sizer and 1-Click JSON Audit Export",
        "badge": "2-WASSERSTEIN (W_2) & BOTTLENECK DISTANCE",
        "active_index": 2,
        "active_label": "LPAD CLINIC TERMINAL LENS CAPTURE",
        "cards": [
            (
                "Healthy Blueprint Library",
                "Pre-compiled persistence arrays from the NIH Visible Human Project: gastrointestinal epithelium, chest lung network, and sagittal brain parenchyma."
            ),
            (
                "2-Wasserstein (W_2) Distance",
                "Computes the minimum transportation cost to morph live persistence pairs into healthy templates. Robust against isolated dust or slide tears."
            ),
            (
                "LPAD Clinic Terminal Lens Capture",
                "Auto-detects A4, US Letter, and Square Film. A four-point perspective warp completely flattens hard-copy sheets for zero-click surgical rounds."
            ),
        ],
        "script": (
            "Finally, examine the third element: The LPAD Clinic Terminal Lens Capture and Auto-Sizer. Clinicians do not have time "
            "to manually crop or resize pathology sheets. Sentinari's optical pipeline automatically detects standard international paper "
            "formats, flattens physical hard-copy scans via perspective transforms, and evaluates structural deviation against NIH Visible "
            "Human blueprints using 2-Wasserstein distance. With one click, surgeons export an audit-ready JSON record for clinical rounds."
        ),
        "subtitle": "Active Focus: LPAD Lens Capture flattens physical reports and matches NIH blueprints via Wasserstein distance."
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


def render_presentation_slide(slide: dict, out_path: Path) -> None:
    """
    Renders a 1920x1080 slide graphic with:
    - Glowing neon focus indicator around the active element card
    - 'ACTIVE FOCUS' crosshair badge
    - Lower-third high-contrast subtitle caption banner
    """
    w, h = 1920, 1080
    im = Image.new("RGB", (w, h), (10, 17, 26))
    draw = ImageDraw.Draw(im)

    # Ambient deep obsidian gradients
    draw.rectangle([0, 0, w, h], fill=(10, 17, 26))
    draw.ellipse([w - 600, -200, w + 300, 500], fill=(16, 28, 44))
    draw.ellipse([-300, h - 500, 400, h + 200], fill=(12, 32, 38))

    # Fonts
    f_badge = get_font(18, bold=True)
    f_cat = get_font(21, bold=True)
    f_title = get_font(42, bold=True)
    f_sub = get_font(24, bold=False)
    f_card_head = get_font(22, bold=True)
    f_card_body = get_font(18, bold=False)
    f_active_badge = get_font(16, bold=True)
    f_caption = get_font(24, bold=True)
    f_foot = get_font(17, bold=False)

    # Top Section Label & Category Bar
    y = 50
    sec_label = slide.get("section", "MASTER WALKTHROUGH")
    cat_text = slide.get("category", "SYSTEM SPECIFICATION")
    draw.text((100, y), f"{sec_label}    {cat_text}", font=f_cat, fill=(0, 229, 255))

    # Top Right Badge
    badge_text = slide.get("badge", "SENTINARI")
    bbox = draw.textbbox((0, 0), badge_text, font=f_badge)
    bw = bbox[2] - bbox[0] + 32
    bh = 34
    bx = w - 100 - bw
    draw.rounded_rectangle([bx, y - 4, bx + bw, y - 4 + bh], radius=17, fill=(18, 32, 50), outline=(0, 230, 118), width=2)
    draw.text((bx + 16, y), badge_text, font=f_badge, fill=(105, 240, 174))

    # Main Title
    y += 42
    title_text = slide.get("title", "")
    draw.text((100, y), title_text, font=f_title, fill=(255, 255, 255))

    # Subtitle
    y += 58
    sub_text = slide.get("subtitle", "")
    draw.text((100, y), sub_text, font=f_sub, fill=(144, 164, 174))

    # Divider Line
    y += 38
    draw.line([100, y, w - 100, y], fill=(30, 48, 70), width=2)
    draw.line([100, y, 460, y], fill=(0, 229, 255), width=4)

    # Cards Grid
    y += 32
    cards = slide.get("cards", [])
    num_cards = len(cards)
    active_idx = slide.get("active_index", 0)
    active_label = slide.get("active_label", "CURRENT INSPECTION TARGET")

    if num_cards > 0:
        card_w = (w - 200 - (num_cards - 1) * 26) // num_cards
        card_h = 490

        for i, (chead, cbody) in enumerate(cards):
            cx = 100 + i * (card_w + 26)
            cy = y
            is_active = (i == active_idx)

            if is_active:
                # GLOWING NEON BORDER & ELEVATED BACKGROUND FOR ACTIVE ELEMENT
                # Draw outer glow
                draw.rounded_rectangle(
                    [cx - 5, cy - 5, cx + card_w + 5, cy + card_h + 5],
                    radius=20,
                    outline=(0, 229, 255),
                    width=4
                )
                draw.rounded_rectangle(
                    [cx, cy, cx + card_w, cy + card_h],
                    radius=16,
                    fill=(20, 36, 56),
                    outline=(0, 230, 118),
                    width=2
                )
                # Active Top Accent Bar (Glowing Emerald)
                draw.rounded_rectangle([cx, cy, cx + card_w, cy + 10], radius=4, fill=(0, 230, 118))

                # ACTIVE FOCUS BADGE (Pulsing Indicator Above Card)
                badge_w = 340
                badge_h = 30
                draw.rounded_rectangle(
                    [cx + 16, cy + 18, cx + 16 + badge_w, cy + 18 + badge_h],
                    radius=8,
                    fill=(0, 229, 255),
                    outline=(255, 255, 255),
                    width=1
                )
                draw.text(
                    (cx + 26, cy + 23),
                    f" NOW INSPECTING: {active_label[:22]}",
                    font=f_active_badge,
                    fill=(0, 15, 25)
                )

                # Card Title (Bright White)
                draw.text((cx + 24, cy + 62), chead, font=f_card_head, fill=(255, 255, 255))
                draw.line([cx + 24, cy + 100, cx + card_w - 24, cy + 100], fill=(0, 229, 255), width=2)
                text_col = (240, 246, 252)
                start_by = cy + 116

            else:
                # Dimmed/inactive card background
                draw.rounded_rectangle(
                    [cx, cy, cx + card_w, cy + card_h],
                    radius=16,
                    fill=(13, 21, 33),
                    outline=(30, 46, 68),
                    width=1
                )
                # Subtle top bar
                draw.rounded_rectangle([cx, cy, cx + card_w, cy + 6], radius=4, fill=(45, 65, 90))

                # Card Title (Muted)
                draw.text((cx + 24, cy + 24), chead, font=f_card_head, fill=(176, 190, 197))
                draw.line([cx + 24, cy + 62, cx + card_w - 24, cy + 62], fill=(24, 38, 56), width=1)
                text_col = (144, 164, 174)
                start_by = cy + 78

            # Card Body wrapped
            wrapped = []
            for para in cbody.split("\n"):
                wrapped.extend(textwrap.wrap(para, width=28 if card_w < 440 else 36))
            by = start_by
            for line in wrapped:
                draw.text((cx + 24, by), line, font=f_card_body, fill=text_col)
                by += 28

    # -------------------------------------------------------------------------
    # SYNCHRONIZED LOWER-THIRD SUBTITLE / CAPTION BAR
    # -------------------------------------------------------------------------
    caption_y = h - 210
    caption_h = 110
    # Semi-transparent dark obsidian container with cyan glowing top border
    draw.rounded_rectangle(
        [100, caption_y, w - 100, caption_y + caption_h],
        radius=14,
        fill=(5, 12, 20),
        outline=(0, 229, 255),
        width=2
    )
    # Speaker / Context Pill
    draw.rounded_rectangle(
        [120, caption_y + 14, 290, caption_y + 40],
        radius=6,
        fill=(0, 230, 118),
        outline=(0, 200, 83),
        width=1
    )
    draw.text((130, caption_y + 18), " NARRATION (ANDREW)", font=f_active_badge, fill=(0, 20, 10))

    # Subtitle Text wrapped
    caption_text = slide.get("subtitle_caption", slide.get("subtitle", ""))
    caption_wrapped = textwrap.wrap(caption_text, width=82)
    cy_text = caption_y + 48
    for line in caption_wrapped[:2]:
        draw.text((124, cy_text), line, font=f_caption, fill=(255, 255, 255))
        cy_text += 28

    # Bottom Footer
    foot_left = "Dr. Pierre C. Wepener    Founder & Chief Architect    Inspirari Research Initiative    Sentinari Architecture"
    foot_right = "Oncology Precision: /ui/oncology  |  Vision Lab & TDA: /ui/vision  |  Gate 2 NSIS"
    draw.text((100, h - 55), foot_left, font=f_foot, fill=(120, 144, 156))
    r_bbox = draw.textbbox((0, 0), foot_right, font=f_foot)
    rw = r_bbox[2] - r_bbox[0]
    draw.text((w - 100 - rw, h - 55), foot_right, font=f_foot, fill=(0, 229, 255))

    im.save(out_path, format="PNG")


async def generate_speech_audio(text: str, out_path: Path, voice: str = VOICE_NAME, max_retries: int = 4) -> None:
    """Generate professional neural voiceover with edge-tts."""
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
    """Extract audio duration via ffmpeg."""
    cmd = [ffmpeg_exe, "-i", str(audio_path)]
    p = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
    if m:
        h, mn, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
        return h * 3600 + mn * 60 + s
    return 30.0


def build_slide_video_segment(slide_img: Path, audio_file: Path, out_segment: Path, duration: float, ffmpeg_exe: str) -> None:
    """Create video segment from slide image and audio."""
    dur = duration + 0.6
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
    """Concatenate video segments into master MP4."""
    concat_txt = OUTPUT_DIR / "concat_segments.txt"
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


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = get_ffmpeg_exe()

    print("=" * 80)
    print("PRODUCING TOPOLOGY, ONCOLOGY & EYES MASTER WALKTHROUGH VIDEO")
    print(f"Chief Architect: Dr. Pierre C. Wepener")
    print(f"Narrator: {VOICE_NAME}")
    print(f"FFmpeg binary: {ffmpeg_exe}")
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 80)

    segment_paths: list[Path] = []
    total_duration = 0.0

    for idx, slide in enumerate(SLIDES_DATA, start=1):
        sid = slide["id"]
        print(f"\n[{idx}/{len(SLIDES_DATA)}] Processing {sid}: {slide['title']}...")

        audio_path = OUTPUT_DIR / f"{sid}_narration.mp3"
        img_path = OUTPUT_DIR / f"{sid}_slide.png"
        seg_path = OUTPUT_DIR / f"{sid}_segment.mp4"

        print("  -> Synthesizing neural voiceover...")
        await generate_speech_audio(slide["script"], audio_path)
        duration = get_audio_duration_seconds(audio_path, ffmpeg_exe)
        total_duration += duration
        print(f"  -> Narration duration: {duration:.1f}s")

        print("  -> Rendering 1080p slide with glowing focus indicator and subtitle banner...")
        slide["subtitle_caption"] = slide["script"][:160] + "..."
        render_presentation_slide(slide, img_path)

        print("  -> Compiling video segment with FFmpeg...")
        build_slide_video_segment(img_path, audio_path, seg_path, duration, ffmpeg_exe)
        segment_paths.append(seg_path)

    print("\n" + "=" * 80)
    print(f"Concatenating all {len(segment_paths)} segments into Master MP4...")
    concatenate_segments(segment_paths, MASTER_VIDEO_PATH, ffmpeg_exe)
    print(f"[+] Master video generated: {MASTER_VIDEO_PATH} ({MASTER_VIDEO_PATH.stat().st_size / (1024*1024):.2f} MB)")

    # Copy to static for direct web streaming
    shutil.copy2(MASTER_VIDEO_PATH, STATIC_VIDEO_PATH)
    print(f"[+] Web static copy synced: {STATIC_VIDEO_PATH}")
    print(f"[+] Total Duration: {total_duration:.1f} seconds ({total_duration/60:.2f} minutes)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
