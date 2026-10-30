"""Sentinari Engineering Formulas & Multi-Vocation Calculation Registry.

Provides structured engineering calculations, equations, units, and handbook citations
derived from authoritative engineering reference texts:
  - Tyler G. Hicks, P.E., "Civil Engineering Formulas", 2nd Edition, McGraw-Hill.
  - Tyler G. Hicks, P.E., "Handbook of Engineering Calculations", McGraw-Hill.
  - Dan B. Marghitu, "Mechanical Engineer's Handbook", Academic Press.
  - Tyler G. Hicks & Nicholas P. Chopey, "Handbook of Chemical Engineering Calculations", McGraw-Hill.
  - American Institute of Chemical Engineers (AIChE) Standards.
  - Mechanical Engineering Formulas & Reference Guide (Solid Mechanics, Fluid Mechanics, Thermodynamics).
"""

from __future__ import annotations

import re
import html as _html
from typing import Any

# ============================================================================
# COMPREHENSIVE ENGINEERING GLOSSARY & TOOLTIP DICTIONARY
# ============================================================================

TERM_GLOSSARY: dict[str, str] = {
    # Badges & Meta
    "AUTHORITATIVE HANDBOOK DOMAIN": "Peer-reviewed, accredited engineering discipline codified in official national and international engineering handbooks (McGraw-Hill, ACI, AISC, ASME, IEEE, AIChE).",
    "Authoritative Handbook Domain": "Peer-reviewed, accredited engineering discipline codified in official national and international engineering handbooks (McGraw-Hill, ACI, AISC, ASME, IEEE, AIChE).",
    "Electrical & Telecom Engineering (Autonomous Swarms)": "Engineering discipline focused on electromagnetic wave propagation, digital communications, RF link budgets, anti-jamming resilience, and decentralized multi-agent robotic swarms.",
    "Mechanical Engineering & Thermal-Fluids": "Engineering discipline addressing physical stress, strain, elasticity, aerodynamics, convective cooling, thermal conduction, and machine design.",
    "Civil & Structural Engineering": "Engineering discipline covering structural framing, beam deflection, column stability, reinforced concrete mechanics, foundation bearing, and open-channel hydraulics.",
    "Chemical & Environmental Process Engineering": "Engineering discipline covering chemical reaction kinetics, mass/energy transport, Monod bioreactor sizing, clarifier design, and sludge dewatering.",
    "Electrical": "Concerning the physical flow and control of electrons, electromagnetic fields, and electric circuitry.",
    "Telecom": "Telecommunications: The electronic transmission of voice, data, video, and control signals across wired, optical, or wireless RF media.",
    "Engineering": "The disciplined application of scientific and mathematical principles to design, construct, analyze, and optimize materials, structures, machines, and systems.",
    "Autonomous": "Capable of executing perception, path planning, and operational control independently without continuous human-in-the-loop guidance.",
    "Swarms": "Coordinated collectives of decentralized autonomous agents that interact locally to produce robust, self-organizing global behavior.",
    "Shannon": "Claude Shannon (1916-2001), father of information theory, who mathematically established the absolute limits of error-free data transfer over noisy channels.",
    "Friis": "Harald T. Friis (1893-1976), pioneer of radio engineering who formulated the Friis free-space transmission path loss equation.",
    "Skolnik": "Merrill Skolnik, author of the 'Radar Handbook', who pioneered electromagnetic signature modeling, radar cross-sections, and electronic counter-countermeasures.",
    "Sentinari RF Mesh Specifications": "Tactical sovereign ad-hoc mesh network protocols designed for mission-critical, satellite-denied military AI swarm operations.",
    "Tyler G. Hicks": "Tyler G. Hicks, P.E., renowned consulting engineer and author of 'Civil Engineering Formulas' and 'Handbook of Engineering Calculations' (McGraw-Hill).",
    "Dan B. Marghitu": "Dan B. Marghitu, author of 'Mechanical Engineer's Handbook' (Academic Press), specializing in solid mechanics, dynamics, and machine elements.",
    "AIChE": "American Institute of Chemical Engineers, the primary professional organization establishing chemical process, reactor, and kinetics standards.",
    "ACI 318": "American Concrete Institute standard code requirements for reinforced concrete structural design and evaluation.",
    "AISC LRFD": "American Institute of Steel Construction Load and Resistance Factor Design specification for structural steel buildings.",

    # Telecommunications & Electronic Warfare
    "Anti-Jamming": "Techniques and signal processing methods designed to resist intentional electromagnetic interference and maintain communication fidelity.",
    "Channel Capacity": "The theoretical maximum rate (in bits per second) at which information can be reliably transmitted over a communication channel without error.",
    "Link Budgets": "The comprehensive mathematical accounting of all gains and losses from transmitter power, through the transmission medium, to the receiver.",
    "Free-Space": "An idealized propagation path in a vacuum free from physical obstructions, reflections, multipath fading, or atmospheric absorption.",
    "Free-Space Path Loss": "The reduction in signal power density of an electromagnetic wave as it propagates through space, proportional to the square of distance and frequency.",
    "SINR": "Signal-to-Interference-plus-Noise Ratio: The ratio of desired carrier power to the combined power of background thermal noise and hostile electronic jamming.",
    "Bandwidth": "The physical width of the electromagnetic frequency spectrum (in Hertz) allocated to the signal, directly governing data throughput.",
    "Thermal Noise": "Electronic noise generated by the thermal agitation of electrons inside an electrical conductor at equilibrium (N0 = k * T).",
    "Jamming": "Intentional radiation, reradiation, or reflection of electromagnetic energy designed to degrade or disrupt friendly communication systems.",
    "Spatial Nulling": "Synthesizing a steep directional zero (dead zone) in a phased-array antenna's reception pattern steered directly toward the hostile emitter.",
    "Frequency Hopping": "Rapid pseudorandom switching of radio transmission frequencies across a broad spectrum (e.g. 1,200 hops/sec) to evade hostile intercept and spot jamming.",
    "Topological Reconvergence": "The time required for an ad-hoc mesh network to rediscover routes and re-establish end-to-end data flow following the destruction or loss of nodes.",
    "Post-Quantum Cryptography": "Cryptographic algorithms (such as NIST ML-KEM / Kyber) believed to be secure against decryption attacks by quantum computers.",

    # Mechanical & Materials Engineering
    "Hooke's Law": "Fundamental physical law stating that below the elastic limit, the mechanical strain in a solid body is directly proportional to the applied stress.",
    "Stress": "Internal force per unit cross-sectional area exerted by neighboring particles of a continuous material on one another (Pa or psi).",
    "Strain": "Dimensionless deformation representing the relative physical displacement of particles in a material body (change in length divided by original length).",
    "Young's Modulus": "Measure of the mechanical stiffness of a solid material, defined as the ratio of tensile stress to tensile strain.",
    "Axial Deformation": "Elongation or compression of a structural member along its longitudinal axis under applied axial force.",
    "Torsional Shear Stress": "Shear stress produced within a circular or non-circular shaft when subjected to a twisting moment or torque.",
    "Polar Moment of Inertia": "Geometric property of a cross section that quantifies its resistance to torsional deformation about a central axis.",
    "Factor of Safety": "Ratio of structural load-carrying capacity (yield or ultimate strength) to actual applied load, providing safety margin against unexpected forces.",
    "FoS": "Factor of Safety: Dimensionless multiplier (capacity / actual load). Military and critical avionics standard requires FoS >= 1.5 to 2.0.",

    # Fluid Mechanics
    "Bernoulli's Equation": "Conservation of mechanical energy along fluid streamlines: the sum of static pressure, dynamic kinetic energy, and elevation head remains constant.",
    "Reynolds Number": "Dimensionless ratio of inertial forces to viscous forces in fluid flow; categorizes flow as laminar (smooth) or turbulent (chaotic).",
    "Darcy-Weisbach": "Universal theoretical equation relating head loss and pressure drop caused by viscous wall shear friction in fluid pipelines.",
    "Viscosity": "Measure of a fluid's internal resistance to gradual deformation by shear stress or tensile stress ('thickness' of the fluid).",
    "Kinematic Viscosity": "Ratio of dynamic viscosity to fluid density (nu = mu / rho), measuring fluid resistance to flow under the influence of gravity.",
    "Friction Factor": "Dimensionless coefficient (from the Moody diagram) quantifying wall roughness resistance in pipe fluid flow.",

    # Thermodynamics & Heat Transfer
    "First Law of Thermodynamics": "Universal law of conservation of energy: the change in internal energy of a closed system equals net heat added minus work performed.",
    "Fourier's Law": "Fundamental law of thermal conduction: heat transfer rate through a material is proportional to the negative temperature gradient and area.",
    "Conduction": "Transfer of internal thermal energy by microscopic collisions of particles and movement of electrons within a solid body.",
    "Convection": "Transfer of heat between a solid surface and a moving liquid or gas surrounding it.",
    "Newton's Law of Cooling": "States that the rate of convective heat loss from a body is directly proportional to the temperature difference between the body and surroundings.",
    "Thermal Conductivity": "Intrinsic material property measuring its capability to conduct heat energy across a unit temperature gradient.",
    "Heat Sinking": "Passive or forced thermal dissipation subsystem removing excess heat from high-power electronic components (such as GaN RF amplifiers).",

    # Civil & Structural Engineering
    "Euler Buckling": "Critical axial compressive load at which a slender column suddenly bends and becomes unstable without material failure.",
    "Slenderness Ratio": "Ratio of a column's effective length to its least radius of gyration (L/r); governs buckling susceptibility.",
    "Lateral-Torsional Buckling": "Instability phenomenon where an unbraced beam subject to flexural bending suddenly twists and bows laterally.",
    "Castigliano's Theorem": "Structural analysis theorem: the partial derivative of total strain energy with respect to an applied force gives the deflection at that point.",
    "Bearing Capacity": "Maximum pressure that a foundation or soil stratum can withstand without undergoing shear failure or excessive settlement.",
    "Prandtl-Terzaghi": "Classical geotechnical failure model calculating ultimate bearing pressure of shallow footings on cohesive or frictional soils.",
    "Manning's Equation": "Empirical formula estimating the average flow velocity of water in an open channel or non-full conduit.",
    "Hydraulic Radius": "Ratio of the cross-sectional area of flowing water to its wetted perimeter (R = A / P).",
    "Monod Kinetics": "Mathematical model describing microbial growth and substrate biodegradation rates in biological wastewater reactors.",

    # Hypothesis Decision, Statistical Rigor & Falsifiability (Karl Popper & Vapnik-Chervonenkis)
    "Hypothesis Decision": "The formal scientific and statistical judgment determining whether empirical evidence warrants rejecting the null hypothesis (H₀) in favor of the alternative hypothesis (H₁).",
    "Null Hypothesis": "Null Hypothesis (H₀): The baseline proposition asserting no effect, no difference, or status-quo performance. In Sentinari, H₀ posits that the proposed innovation yields no systemic improvement over baseline.",
    "THE NULL HYPOTHESIS (H₀)": "Null Hypothesis (H₀): The baseline claim of no effect or status-quo performance (p >= α = 0.05).",
    "H₀": "Null Hypothesis (H₀): Baseline proposition that the proposed innovation produces no statistically significant systemic improvement (p >= α = 0.05).",
    "Alternative Hypothesis": "Alternative Hypothesis (H₁ or Ha): The scientific proposition asserting a true, measurable, and statistically significant systemic enhancement beyond baseline random variation.",
    "ALTERNATIVE HYPOTHESIS (H₁)": "Alternative Hypothesis (H₁): The experimental claim confirming systemic enhancement beyond random variation (p < α = 0.05).",
    "H₁": "Alternative Hypothesis (H₁): The scientific proposition asserting a true systemic enhancement beyond baseline random variation (p < α = 0.05).",
    "Ha": "Alternative Hypothesis (Ha): Designates the experimental claim tested against the null hypothesis.",
    "Falsifiability": "A fundamental scientific standard (Karl Popper): A hypothesis must make specific, testable predictions that can be empirically proven false by experiment. Guaranteed by defining threshold α before experimentation.",
    "Significance Level": "Predetermined probability threshold (α = 0.05) representing the maximum allowable risk of committing a Type I error (falsely rejecting a true null hypothesis).",
    "α": "Significance Level (Alpha = 0.05): The predetermined threshold below which the calculated p-value must fall to reject the null hypothesis.",
    "p-value": "The exact calculated probability of observing test results at least as extreme as the empirical data, assuming the null hypothesis (H₀) were true. When p < α, H₀ is rejected.",
    "t-test": "A parametric statistical test comparing the sample mean against a hypothesized baseline value or comparing two sample distributions.",
    "ANOVA": "Analysis of Variance: A statistical method testing for differences among three or more group means by partitioning total variance into explained and unexplained components.",
    "Chi-Square": "A non-parametric statistical test evaluating categorical frequencies against expected theoretical distributions.",
    "VC Dimension": "Vapnik-Chervonenkis Dimension (D_VC): In statistical learning theory, a measure of the capacity and flexibility of a hypothesis class. A finite, bounded VC dimension guarantees rigidity and mathematical falsifiability, preventing the model from curving to overfit random noise.",
    "D_VC": "Vapnik-Chervonenkis Dimension (D_VC < ∞): Quantitative metric of hypothesis complexity. Finite bounded dimension ensures genuine falsifiability.",
    "Finite Bounded": "A mathematical property where a metric or dimension is strictly constrained within real finite limits (D_VC < ∞), ensuring that the model cannot bend to arbitrarily fit random noise.",
    "Gist and Context Evaluation": "The rigorous academic synthesis that looks beyond raw statistical numbers to judge whether underlying causal mechanisms and systemic conclusions hold logical coherence.",
    "Post-Mortem Review": "A formal retrospective evaluation that inspects experimental methodology, sensor fidelity, and data integrity to verify whether empirical conclusions represent genuine physical laws or observational artifacts.",
    "Type I Error": "False Positive: The error of rejecting a true null hypothesis. Rigorously bounded by the pre-set significance level α (typically 5%).",
    "Type II Error": "False Negative (β): The error of failing to reject a false null hypothesis. Minimized by adequate statistical power (1 - β >= 0.80).",
    "Cohen's d": "A standardized parametric effect size metric expressing the difference between two means in units of standard deviation (d >= 0.8 denotes large effect size).",
    "Parametric Effect Size": "A standardized quantitative measure of the magnitude of an experimental effect, independent of sample size.",
    "Empirical Attestation": "A certified, cryptographically timestamped attestation by the sovereign validation engine confirming scientific reproducibility and compliance with the R&D protocol.",
    "Net Systemic Impact Score": "NSIS: Normalized composite score spanning [-1.0, 1.0] derived from multi-dimensional sustainability indicators.",
    "NSIS": "Net Systemic Impact Score: Normalized composite metric evaluating system-wide performance improvement.",
    "Statistical Rigor": "The disciplined application of formal mathematical hypothesis testing, sample size adequacy, confidence intervals, and effect size calculations to rule out random coincidence.",
    "Falsifiable": "Capable of being tested and potentially proven false by empirical observation or controlled experiment.",

    # Domain Hypothesis Attributes & Telecommunications Handover Terms
    "signal quality": "Received carrier signal strength and SINR metric quantifying link transmission fidelity.",
    "elevation angle": "The angular height of a satellite or aerial transceiver above the local horizon (degrees), directly influencing atmospheric attenuation and line-of-sight blockage.",
    "network load": "The aggregate data throughput demand and active subscriber connection count competing for shared radio resource blocks.",
    "utility function": "A mathematical function mapping multiple competing operational objectives into a single scalar payoff value for optimal decision-making.",
    "stability bonus": "A mathematical hysteresis incentive added to the utility payoff to prevent rapid, unnecessary ping-pong transitions between transceivers.",
    "handover": "The operational process of transferring an ongoing call, data session, or RF link from one base station / satellite beam to another without session termination.",
    "handover frequency": "The rate at which an active mobile terminal or transceiver transitions its connection between adjacent base stations or satellite beams.",
    "computational overhead": "The CPU/GPU instruction cycles, memory footprint, and algorithmic execution latency consumed by the decision engine.",
    "status-quo baseline": "The incumbent conventional operational regime or legacy standard operating without sovereign multi-attribute optimization.",
    "Kuramoto": "Decentralized non-linear phase-coupled oscillator model governing spontaneous biological and physical synchronization.",
    "phase-coupled": "Physical or algorithmic coupling where individual node oscillations influence and synchronize neighbor phase angles.",
    "phase-locking": "A steady-state condition where two or more oscillating nodes maintain a constant relative phase angle despite differing natural frequencies.",
    "Hierarchical Cellular Automata Mesh": "A decentralized, multi-tiered cellular network structure where local neighbor interaction rules govern self-healing and topology management.",
    "HCAM": "Hierarchical Cellular Automata Mesh: Decentralized self-organizing mesh architecture for resilient mission-critical communications.",
    "self-healing": "The autonomous capability of a decentralized system to detect faults, isolate degraded nodes, and reroute network traffic without manual intervention.",
    "re-convergence": "The algorithmic process and time interval required for a distributed network to restore coherent topological state after node disruptions.",
    "Proof": "A rigorous mathematical and empirical demonstration establishing the validity of a scientific proposition beyond doubt.",
    "Formalism": "A mathematically rigorous symbolic framework defining the exact variables, relations, and operations governing a system.",
    "Empirical": "Originating in or based on actual observation, controlled experiment, and verifiable measurement data rather than pure conjecture.",

    # Formal Mathematical Invariants, Quantifiers & Automated Hypothesis Calibration
    "∀": "Universal Quantifier (∀): 'For all' or 'for every' element in the specified mathematical domain or index set.",
    "∈": "Set Membership (∈): Denotes that an element belongs to or is contained within a specified set.",
    "≤": "Less-Than-or-Equal (≤): Mathematical relational operator specifying non-decreasing or bounded ordering.",
    "A[i]": "Array Element: The discrete value stored at zero-based index i in array or sequence A.",
    "A[i+1]": "Successor Element: The adjacent element immediately following index i in array A.",
    "∀i ∈ {0, …, n-2}": "Index Quantification: 'For every index i from 0 up to n-2', spanning all adjacent element pairs in an array of size n.",
    "A[i] ≤ A[i+1]": "Monotonic Sorting Condition: 'The element at current index is less than or equal to the element at the next index', enforcing non-decreasing order.",
    "∀i∈{0,…,n−2}:A[i]≤A[i+1]": "Formal Sorted Array Invariant: Mathematically proves that array A of size n is sorted in non-decreasing (ascending) order across all adjacent pairs.",
    "Non-Decreasing Order": "A monotonic sequence where each successive term is greater than or equal to the preceding term (A[0] ≤ A[1] ≤ … ≤ A[n-1]).",
    "Sorted Array Invariant": "A formal invariant establishing that every adjacent pair satisfies A[i] ≤ A[i+1], guaranteeing ordered telemetry and algorithmic stability.",
    "0.6524": "Calibrated Benchmark Factor: Dr. Pierre C. Wepener's high-rigor baseline threshold against which empirical NSIS and R&D yield are evaluated to automate H₁ hypothesis confirmation.",
    "Calibrated Factor": "Calibrated Factor (0.6524): Dr. Wepener's quantitative threshold ensuring that only high-impact innovations (NSIS ≥ 0.6524) trigger automated H₁ confirmation.",
    "Significance Column": "The empirical p-value column in Section 5.2b/5.3 where every tested economic and operational metric achieves p < 0.02.",
    "p < 0.02": "Empirical Significance Standard: Every modeled economic and operational metric achieves p < 0.02, far exceeding the standard α = 0.05 threshold.",
    "Automated Hypothesis Judgment": "Algorithmic falsifiability pipeline that evaluates row-level significance (all p_j < 0.02) and benchmark factor (NSIS ≥ 0.6524) to deterministically issue the H₁ Reject H₀ seal without human subjectivity."
}

UNIT_GLOSSARY: dict[str, str] = {
    "Pa or N/m²": "Pascals or Newtons per square meter: SI unit of pressure and mechanical stress.",
    "Pa": "Pascal: International Standard (SI) unit of pressure and stress (1 Pa = 1 N/m²).",
    "psi": "Pounds per square inch: US Customary System (USCS) unit of pressure and mechanical stress.",
    "m": "Meter: SI base unit of length.",
    "in": "Inch: US Customary System unit of length (1 in = 25.4 mm).",
    "N": "Newton: SI unit of mechanical force (force required to accelerate 1 kg at 1 m/s²).",
    "lbf": "Pound-force: USCS unit of force (force exerted by gravity on a mass of one avoirdupois pound).",
    "m²": "Square meter: SI derived unit of area.",
    "in²": "Square inch: USCS unit of cross-sectional area.",
    "N·m": "Newton-meter: SI unit of torque, moment of force, and mechanical work.",
    "lbf·in": "Pound-force inch: USCS unit of torque and twisting moment.",
    "m⁴": "Meter to the fourth power: SI unit of area moment of inertia and polar moment of inertia.",
    "in⁴": "Inch to the fourth power: USCS unit of area moment of inertia.",
    "ratio": "Dimensionless ratio: Pure numerical quotient comparing two identical physical dimensions.",
    "dimensionless": "Dimensionless quantity: Pure number without physical units of measurement.",
    "kg/m³": "Kilogram per cubic meter: SI unit of mass density.",
    "lb/ft³": "Pounds per cubic foot: USCS unit of weight density.",
    "m/s": "Meters per second: SI unit of velocity and speed.",
    "ft/s": "Feet per second: USCS unit of velocity and speed.",
    "9.81 m/s²": "Standard terrestrial acceleration due to gravity in SI units.",
    "32.2 ft/s²": "Standard terrestrial acceleration due to gravity in USCS units.",
    "Pa·s": "Pascal-second: SI unit of dynamic shear viscosity.",
    "lb·s/ft²": "Pound-second per square foot: USCS unit of dynamic viscosity.",
    "m²/s": "Square meter per second: SI unit of kinematic viscosity.",
    "ft²/s": "Square foot per second: USCS unit of kinematic viscosity.",
    "J": "Joule: SI unit of work, heat, and energy (1 J = 1 N·m = 1 W·s).",
    "Btu": "British thermal unit: Traditional unit of heat (energy needed to heat 1 lb of water by 1°F).",
    "W": "Watt: SI unit of power (rate of energy conversion of 1 Joule per second).",
    "Btu/h": "British thermal units per hour: USCS unit of thermal power / heat dissipation rate.",
    "W/(m·K)": "Watt per meter-Kelvin: SI unit of thermal conductivity (k).",
    "Btu·in/(h·ft²·°F)": "USCS unit of thermal conductivity.",
    "W/(m²·K)": "Watt per square meter-Kelvin: SI unit of convective heat transfer coefficient (h_c).",
    "Btu/(h·ft²·°F)": "USCS unit of convective heat transfer coefficient.",
    "K or °C": "Kelvin or Degree Celsius: Metric temperature units.",
    "°F": "Degree Fahrenheit: USCS temperature unit.",
    "bits/sec (bps)": "Bits per second: International standard rate of digital data transmission.",
    "bps": "Bits per second: Transmission speed of binary information across a communication channel.",
    "Hz": "Hertz: SI unit of frequency (1 oscillation cycle per second).",
    "dBm": "Decibel-milliwatts: Logarithmic power unit referenced to 1.0 milliwatt (30 dBm = 1 Watt).",
    "dBi": "Decibels isotropic: Directional antenna gain relative to a theoretical isotropic antenna.",
    "dB": "Decibel: Logarithmic unit expressing the ratio between two physical values (power or intensity).",
    "hops": "Network hops: Number of intermediate relay node transitions across the mesh.",
    "s": "Second: SI base unit of time.",
    "ms": "Millisecond: One thousandth of a second (10⁻³ seconds).",
    "kips": "Kilopound: US structural engineering unit equal to 1,000 pounds-force.",
    "ksi": "Kilopounds per square inch: US structural engineering unit equal to 1,000 psi.",
    "MPa": "Megapascal: Metric unit of stress and pressure equal to 1,000,000 Pascals (1 N/mm²).",
    "degrees": "Angular degrees: Unit of plane angle (360 degrees in a complete circle).",
    "m³": "Cubic meter: SI unit of volume.",
    "Mgal": "Million gallons: US water and wastewater engineering volume unit.",
    "days": "Mean solar days (24 hours): Unit of biological residence time and sludge age.",
    "m³/day": "Cubic meters per day: SI unit of volumetric fluid flow rate.",
    "Mgd": "Million gallons per day: US municipal wastewater flow rate unit.",
    "mg/L": "Milligrams per liter: Concentration unit (equivalent to parts per million in water).",
    "day⁻¹": "Per day: Biological microbial decay rate constant unit."
}

def wrap_tag(term: str, display_text: str | None = None, role: str | None = None) -> str:
    """Wrap a word or term in an interactive educational pop-up tag."""
    disp = display_text if display_text is not None else term
    cleaned_key = term.strip()
    explanation = TERM_GLOSSARY.get(cleaned_key) or UNIT_GLOSSARY.get(cleaned_key)
    
    if not explanation:
        for k, v in TERM_GLOSSARY.items():
            if k.lower() == cleaned_key.lower():
                explanation = v
                break
        if not explanation:
            for k, v in UNIT_GLOSSARY.items():
                if k.lower() == cleaned_key.lower():
                    explanation = v
                    break

    if not explanation:
        explanation = f"Technical engineering parameter and calculation factor: {cleaned_key}."

    role_attr = f' data-role="{_html.escape(role)}"' if role else ""
    return (
        f'<span class="eng-tag" data-term="{_html.escape(cleaned_key)}"'
        f' data-tooltip="{_html.escape(explanation)}"{role_attr}>{disp}</span>'
    )

def wrap_badge(term: str, tooltip: str, bg: str = "#e0e7ff", color: str = "#3730a3", border: str = "#c7d2fe") -> str:
    """Wrap a badge in an interactive pop-up tag."""
    return (
        f'<span class="eng-badge-tag" data-term="{_html.escape(term)}"'
        f' data-tooltip="{_html.escape(tooltip)}"'
        f' style="background:{bg};color:{color};border:1px solid {border};font-weight:800;font-size:11px;padding:2px 8px;border-radius:999px;text-transform:uppercase;cursor:help;">'
        f'{term}</span>'
    )


# ============================================================================
# ENGINEERING VOCATIONS & FORMULAS CATALOG
# ============================================================================

ENGINEERING_VOCATIONS: dict[str, dict[str, Any]] = {
    "electrical_telecom": {
        "name": "Electrical & Telecom Engineering (Autonomous Swarms)",
        "primary_source": "Shannon, Friis, Skolnik & Sentinari RF Mesh Specifications",
        "domains": [
            "telecommunication",
            "satellite",
            "swarm",
            "rf",
            "mesh",
            "wireless",
            "antenna",
            "signal",
            "anti-jam",
            "electronic warfare",
            "handover",
            "non-terrestrial",
            "ntn",
            "constellation",
            "cellular",
            "network",
        ],
        "formula_groups": [
            {
                "group_name": "Anti-Jamming Channel Capacity & Link Budgets",
                "source": "Shannon (1948) & Friis Free-Space RF Formulation",
                "formulas": [
                    {
                        "concept": "Shannon-Hartley Anti-Jam Channel Capacity",
                        "latex": r"C = B \log_2 \left(1 + \frac{P_{rx}}{N_0 B + P_{\text{jam}}}\right) = B \log_2(1 + \text{SINR})",
                        "purpose": "Calculates the absolute maximum error-free digital data throughput (bps) possible across a wireless tactical link under severe electronic warfare barrage jamming.",
                        "components": [
                            ("C", "Channel Capacity", "Maximum error-free data rate (bps) possible under the Shannon limit."),
                            ("B", "Modulation Bandwidth", "Allocated electromagnetic spectrum width (Hz)."),
                            ("log₂", "Binary Information Logarithm", "Transforms linear power ratios into digital information bits."),
                            ("P_rx", "Received Signal Power", "Electromagnetic carrier power arriving at receiver antenna (Watts)."),
                            ("N₀·B", "Thermal Noise Floor", "Product of thermal noise spectral density N0 and channel bandwidth B (Watts)."),
                            ("P_jam", "Hostile Jamming Power", "Direct intentional enemy electronic warfare interference power (Watts)."),
                            ("SINR", "Signal-to-Interference-plus-Noise Ratio", "Ratio of received carrier signal to total noise plus jamming.")
                        ],
                        "variables": [
                            ("C", "Theoretical maximum error-free channel capacity", "bits/sec (bps)", "bps"),
                            ("B", "Modulation channel bandwidth", "Hz", "Hz"),
                            ("P_{rx}", "Received carrier signal power", "W", "dBm"),
                            ("N_0 B", "Thermal background noise power floor", "W", "dBm"),
                            (r"P_{\text{jam}}", "Hostile electronic warfare jamming power", "W", "dBm"),
                        ],
                        "rule": "Defines theoretical information capacity under aggressive electronic warfare barrage conditions."
                    },
                    {
                        "concept": "Friis Transmission Link Budget with Jammer Attenuation",
                        "latex": r"P_{rx} = P_{tx} + G_{tx} + G_{rx} - 20\log_{10}\left(\frac{4\pi d}{\lambda}\right) - L_{\text{atm}} - L_{\text{jam}}",
                        "purpose": "Determines the net signal power received across line-of-sight space while accounting for transmitter power, directional antenna gains, geometric path spreading, and steerable spatial nulling.",
                        "components": [
                            ("P_rx", "Received Power", "Carrier power reaching receiver front-end (dBm)."),
                            ("P_tx", "Transmitter Power", "RF output power from GaN amplifier (dBm)."),
                            ("G_tx, G_rx", "Antenna Gains", "Directional gain of transmit/receive phased arrays (dBi)."),
                            ("4πd/λ", "Free-Space Path Loss", "Geometric power spreading loss as wave propagates over distance d."),
                            ("L_jam", "Spatial Nulling Attenuation", "Deep attenuation notch (45-60 dB) steered directly toward enemy jammer azimuth.")
                        ],
                        "variables": [
                            ("P_{rx}", "Received power at antenna port", "dBm", "dBm"),
                            ("P_{tx}", "Transmitter output power", "dBm", "dBm"),
                            ("G_{tx}, G_{rx}", "Transmitter & receiver antenna directional gain", "dBi", "dBi"),
                            ("d", "Line-of-sight separation distance", "m", "km / miles"),
                            (r"\lambda", "Electromagnetic carrier wavelength (c/f)", "m", "m"),
                            (r"L_{\text{jam}}", "Spatial nulling attenuation against hostile emitter", "dB", "dB"),
                        ],
                        "rule": "Steerable phased-array nulling delivers 45–60 dB attenuation toward the jammer azimuth."
                    },
                    {
                        "concept": "Topological Ad-Hoc Reconvergence Latency",
                        "latex": r"\tau_{\text{heal}} = \mathcal{O}(d_{\max} \cdot \Delta t_{\text{beacon}}) \le 2.5\,\text{ms}",
                        "purpose": "Calculates the maximum time required for the autonomous swarm to self-heal and restructure its routing graph when nodes are destroyed or jammed.",
                        "components": [
                            ("τ_heal", "Reconvergence Latency", "Time to restore complete swarm-wide graph reachability (seconds/ms)."),
                            ("d_max", "Graph Diameter", "Maximum hop distance between any two nodes across the swarm."),
                            ("Δt_beacon", "Heartbeat Interval", "Periodic beacon rate for state-vector and topology consensus exchange.")
                        ],
                        "variables": [
                            (r"\tau_{\text{heal}}", "Time to restore full network graph connectivity upon node loss", "s", "ms"),
                            (r"d_{\max}", "Graph diameter (maximum hop distance across swarm)", "hops", "hops"),
                            (r"\Delta t_{\text{beacon}}", "Inter-node heartbeat / state vector interval", "s", "ms"),
                        ],
                        "rule": "Ensures mission continuity and AI swarm decentralization without single points of failure."
                    }
                ]
            }
        ]
    },
    "mechanical": {
        "name": "Mechanical Engineering & Thermal-Fluids",
        "primary_source": "Marghitu (Mechanical Engineer's Handbook) & Hicks (Engineering Calculations)",
        "domains": ["thermal", "stress", "fluids", "structural", "aerospace", "heat", "mechanics", "chassis", "optics"],
        "formula_groups": [
            {
                "group_name": "Solid Mechanics & Strength of Materials",
                "source": "Mechanical Engineering Reference Guide §1 & Marghitu Ch. 2",
                "formulas": [
                    {
                        "concept": "Hooke's Law (Uniaxial Stress)",
                        "latex": r"\sigma = E \cdot \varepsilon",
                        "purpose": "Governs linear elastic deformation, establishing that internal mechanical stress is directly proportional to material strain below yield.",
                        "components": [
                            ("σ", "Mechanical Stress", "Internal restoring force per unit cross-sectional area (Pa or psi)."),
                            ("E", "Young's Modulus", "Intrinsic material stiffness constant."),
                            ("ε", "Mechanical Strain", "Dimensionless relative displacement or elongation.")
                        ],
                        "variables": [
                            (r"\sigma", "Normal stress", "Pa or N/m²", "psi"),
                            ("E", "Young's Modulus of Elasticity", "Pa", "psi"),
                            (r"\varepsilon", "Strain", "dimensionless", "dimensionless"),
                        ],
                        "rule": "Governs linear elastic deformation prior to yield limit."
                    },
                    {
                        "concept": "Axial Elongation / Deformation",
                        "latex": r"\delta = \frac{P \cdot L}{A \cdot E}",
                        "purpose": "Calculates the total physical elongation or compression of a structural member under tensile or compressive axial loading.",
                        "components": [
                            ("δ", "Axial Deformation", "Total physical stretch or contraction (meters or inches)."),
                            ("P", "Applied Axial Load", "Total tensile or compressive force acting on the member (Newtons or lbf)."),
                            ("L", "Length", "Initial unbraced member length."),
                            ("A", "Area", "Cross-sectional structural area."),
                            ("E", "Elastic Modulus", "Material modulus of elasticity.")
                        ],
                        "variables": [
                            (r"\delta", "Total axial elongation", "m", "in"),
                            ("P", "Applied axial tensile/compressive load", "N", "lbf"),
                            ("L", "Initial unbraced member length", "m", "in"),
                            ("A", "Cross-sectional area", "m²", "in²"),
                            ("E", "Modulus of elasticity", "Pa", "psi"),
                        ],
                        "rule": "Applies to prismatic homogeneous bars under uniform axial loading."
                    },
                    {
                        "concept": "Torsional Shear Stress (Circular Shafts)",
                        "latex": r"\tau = \frac{T \cdot r}{J}",
                        "purpose": "Calculates the shearing stress produced across a rotating or twisted circular shaft section under applied torque.",
                        "components": [
                            ("τ", "Torsional Shear Stress", "Shear stress distributed across the cross-section (Pa or psi)."),
                            ("T", "Applied Torque", "Twisting moment applied to the shaft (N·m or lbf·in)."),
                            ("r", "Radius", "Radial distance from shaft centerline to evaluated point."),
                            ("J", "Polar Moment of Inertia", "Resistance to torsional twist based on geometry.")
                        ],
                        "variables": [
                            (r"\tau", "Torsional shear stress", "Pa", "psi"),
                            ("T", "Applied torque", "N·m", "lbf·in"),
                            ("r", "Radial distance from shaft center", "m", "in"),
                            ("J", "Polar moment of inertia", "m⁴", "in⁴"),
                        ],
                        "rule": "Maximum shear stress occurs at the outer fiber (r = D/2)."
                    },
                    {
                        "concept": "Structural Factor of Safety (FoS)",
                        "latex": r"\text{FoS} = \frac{\sigma_{\text{allow}}}{\sigma_{\text{actual}}} \ge 1.50",
                        "purpose": "Provides design certainty that maximum operational shock and dynamic loads remain safely below material yield failure thresholds.",
                        "components": [
                            ("FoS", "Factor of Safety", "Ratio of capacity to actual operational demand."),
                            ("σ_allow", "Allowable Stress", "Material yield or ultimate tensile strength limit."),
                            ("σ_actual", "Actual Stress", "Peak Von Mises stress measured during operational peak.")
                        ],
                        "variables": [
                            (r"\text{FoS}", "Factor of safety", "ratio", "ratio"),
                            (r"\sigma_{\text{allow}}", "Allowable / yield structural capacity", "Pa", "psi"),
                            (r"\sigma_{\text{actual}}", "Maximum combined operating stress", "Pa", "psi"),
                        ],
                        "rule": "Military and mission-critical systems require FoS >= 1.5–2.0 under peak dynamic shock."
                    }
                ]
            },
            {
                "group_name": "Fluid Mechanics & Hydrodynamics",
                "source": "Mechanical Engineering Reference Guide §2 & Hicks Ch. 12",
                "formulas": [
                    {
                        "concept": "Bernoulli's Energy Conservation Equation",
                        "latex": r"P_1 + \frac{1}{2}\rho v_1^2 + \rho g h_1 = P_2 + \frac{1}{2}\rho v_2^2 + \rho g h_2 + h_f",
                        "purpose": "Calculates the conservation of total mechanical energy across fluid conduits and aerodynamic body contours.",
                        "components": [
                            ("P", "Static Pressure", "Hydrostatic fluid pressure (Pascals)."),
                            ("½ρv²", "Dynamic Pressure", "Kinetic energy per unit volume of fluid."),
                            ("ρgh", "Potential Head", "Gravitational potential energy per unit volume."),
                            ("h_f", "Head Loss", "Energy dissipated through viscous wall friction.")
                        ],
                        "variables": [
                            ("P", "Static fluid pressure", "Pa", "psf"),
                            (r"\rho", "Fluid density", "kg/m³", "lb/ft³"),
                            ("v", "Fluid velocity", "m/s", "ft/s"),
                            ("g", "Gravitational acceleration", "9.81 m/s²", "32.2 ft/s²"),
                            ("h", "Geometric elevation", "m", "ft"),
                            ("h_f", "Frictional head loss", "Pa", "psf"),
                        ],
                        "rule": "Fundamental law of conservation of mechanical energy along fluid streamlines."
                    },
                    {
                        "concept": "Reynolds Number (Flow Regime Criterion)",
                        "latex": r"Re = \frac{\rho \cdot v \cdot D}{\mu} = \frac{v \cdot D}{\nu}",
                        "purpose": "Predicts whether fluid flow over a surface or within a conduit is smooth/laminar, transitional, or turbulent.",
                        "components": [
                            ("Re", "Reynolds Number", "Dimensionless ratio of inertial forces to viscous forces."),
                            ("ρ", "Density", "Fluid mass density."),
                            ("v", "Velocity", "Relative flow velocity."),
                            ("D", "Hydraulic Diameter", "Characteristic geometric dimension."),
                            ("μ", "Dynamic Viscosity", "Molecular shear resistance of the fluid.")
                        ],
                        "variables": [
                            ("Re", "Reynolds number", "dimensionless", "dimensionless"),
                            ("v", "Flow velocity", "m/s", "ft/s"),
                            ("D", "Hydraulic diameter / pipe span", "m", "ft"),
                            (r"\mu", "Dynamic shear viscosity", "Pa·s", "lb·s/ft²"),
                            (r"\nu", "Kinematic viscosity", "m²/s", "ft²/s"),
                        ],
                        "rule": "Laminar flow for Re < 2,300; transition for 2,300 <= Re <= 4,000; fully turbulent for Re > 4,000."
                    },
                    {
                        "concept": "Darcy-Weisbach Friction Head Loss",
                        "latex": r"h_f = f \cdot \left(\frac{L}{D}\right) \cdot \left(\frac{v^2}{2g}\right)",
                        "purpose": "Calculates the exact hydraulic head loss and pressure drop generated by pipe wall shear friction over pipeline distance L.",
                        "components": [
                            ("h_f", "Friction Head Loss", "Energy head dissipated by friction (meters or feet of fluid)."),
                            ("f", "Darcy Friction Factor", "Roughness coefficient determined via Moody diagram."),
                            ("L/D", "Length-to-Diameter Ratio", "Dimensionless geometry of the conduit."),
                            ("v²/2g", "Velocity Head", "Kinetic energy head of the moving fluid.")
                        ],
                        "variables": [
                            ("h_f", "Head loss due to pipe wall friction", "m", "ft"),
                            ("f", "Darcy friction factor (Moody diagram)", "dimensionless", "dimensionless"),
                            ("L", "Conduit pipeline length", "m", "ft"),
                            ("D", "Hydraulic conduit diameter", "m", "ft"),
                            ("v", "Mean fluid flow velocity", "m/s", "ft/s"),
                        ],
                        "rule": "Standard universal formula for viscous dissipation across closed conduits."
                    }
                ]
            },
            {
                "group_name": "Thermodynamics & Heat Transfer",
                "source": "Mechanical Engineering Reference Guide §3 & Hicks Ch. 12",
                "formulas": [
                    {
                        "concept": "First Law of Thermodynamics (Closed System)",
                        "latex": r"\Delta U = Q - W",
                        "purpose": "Enforces global energy conservation, tracking changes in system internal energy produced by heat input versus mechanical work performed.",
                        "components": [
                            ("ΔU", "Internal Energy Change", "Net change in microscopic kinetic and potential energy of the system."),
                            ("Q", "Net Heat Added", "Thermal energy transferred across system boundary."),
                            ("W", "Net Work Done", "Mechanical or electrical work performed by the system.")
                        ],
                        "variables": [
                            (r"\Delta U", "Change in system internal energy", "J", "Btu"),
                            ("Q", "Net heat added to system boundary", "J", "Btu"),
                            ("W", "Net work performed by system boundary", "J", "Btu"),
                        ],
                        "rule": "Energy cannot be created or destroyed; state variable U depends solely on end states."
                    },
                    {
                        "concept": "Fourier's Law of Thermal Conduction",
                        "latex": r"q = -k \cdot A \cdot \left(\frac{dT}{dx}\right)",
                        "purpose": "Determines the rate of heat conduction through solid components (such as semiconductor substrates and heat spreaders) across a temperature gradient.",
                        "components": [
                            ("q", "Heat Conduction Rate", "Thermal power flow (Watts or Btu/h)."),
                            ("k", "Thermal Conductivity", "Material ability to transport thermal energy (W/(m·K))."),
                            ("A", "Conduction Area", "Cross-sectional surface perpendicular to heat flow."),
                            ("dT/dx", "Temperature Gradient", "Spatial rate of temperature drop across thickness dx.")
                        ],
                        "variables": [
                            ("q", "Heat transfer rate", "W", "Btu/h"),
                            ("k", "Thermal conductivity of material", "W/(m·K)", "Btu·in/(h·ft²·°F)"),
                            ("A", "Heat conduction surface area", "m²", "ft²"),
                            ("dT/dx", "Temperature gradient across medium", "K/m", "°F/in"),
                        ],
                        "rule": "Rate of heat conduction is directly proportional to temperature gradient and cross-sectional area."
                    },
                    {
                        "concept": "Newton's Law of Convective Cooling",
                        "latex": r"q = h_c \cdot A \cdot (T_s - T_\infty)",
                        "purpose": "Calculates the rate of convective heat removal from high-temperature electronic surfaces to ambient cooling airflow or liquid coolant.",
                        "components": [
                            ("q", "Convective Cooling Rate", "Rate of heat rejected to ambient fluid (Watts)."),
                            ("h_c", "Convective Coefficient", "Heat transfer coefficient based on flow velocity and fluid properties."),
                            ("A", "Wetted Surface Area", "Total exposed fin surface area of the heat sink."),
                            ("T_s - T_∞", "Temperature Differential", "Driving potential between hot component and surrounding coolant.")
                        ],
                        "variables": [
                            ("q", "Convective heat removal rate", "W", "Btu/h"),
                            ("h_c", "Convective heat transfer coefficient", "W/(m²·K)", "Btu/(h·ft²·°F)"),
                            ("A", "Wetted convective surface area", "m²", "ft²"),
                            ("T_s", "Solid surface temperature", "K or °C", "°F"),
                            (r"T_\infty", "Surrounding ambient fluid temperature", "K or °C", "°F"),
                        ],
                        "rule": "Critical for thermal throttling and heat sink design in high-power RF GaN electronics."
                    }
                ]
            }
        ]
    },
    "civil_structural": {
        "name": "Civil & Structural Engineering",
        "primary_source": "Tyler G. Hicks, P.E., 'Civil Engineering Formulas' (McGraw-Hill, 2nd Ed.)",
        "domains": ["civil", "bridge", "beam", "column", "foundation", "soil", "concrete", "timber", "culvert", "retaining"],
        "formula_groups": [
            {
                "group_name": "Beam Flexure, Shear & Elastic Buckling",
                "source": "Hicks Ch. 2 (Beam Formulas) & AISC Manual",
                "formulas": [
                    {
                        "concept": "Elastic Lateral-Torsional Buckling of Beams",
                        "latex": r"M_{\text{cr}} = \frac{\pi}{L} \sqrt{E \cdot I_y \cdot G \cdot J + I_y \cdot C_w \left(\frac{\pi E}{L}\right)^2}",
                        "purpose": "Determines the maximum bending moment an unbraced flexural member can support before catastrophically twisting and buckling laterally.",
                        "components": [
                            ("M_cr", "Critical Buckling Moment", "Threshold moment triggering lateral-torsional instability (N·m or kip·in)."),
                            ("L", "Unbraced Length", "Distance between lateral bracing supports."),
                            ("E, G", "Moduli", "Young's modulus and shear modulus of structural steel."),
                            ("I_y, J, C_w", "Section Properties", "Minor-axis moment of inertia, St. Venant torsional constant, and warping constant.")
                        ],
                        "variables": [
                            (r"M_{\text{cr}}", "Critical lateral buckling moment", "N·m", "kip·in"),
                            ("L", "Unbraced beam length", "m", "in"),
                            ("E", "Modulus of elasticity", "Pa", "psi"),
                            ("I_y", "Moment of inertia about minor y-axis", "m⁴", "in⁴"),
                            ("G", "Shear modulus of elasticity", "Pa", "psi"),
                            ("J", "Torsional constant", "m⁴", "in⁴"),
                            ("C_w", "Warping constant of open section", "m⁶", "in⁶"),
                        ],
                        "rule": "Prevents catastrophic lateral-torsional instability in unbraced flexural members."
                    },
                    {
                        "concept": "Castigliano's Deflection Theorem",
                        "latex": r"\delta_i = \frac{\partial U}{\partial P_i} = \int_0^L \frac{M(x)}{E I} \frac{\partial M(x)}{\partial P_i} dx",
                        "purpose": "Applies energy conservation and virtual work to determine exact physical deflections at any point on a structural beam.",
                        "components": [
                            ("δ_i", "Deflection", "Displacement at point of concentrated load application (meters or inches)."),
                            ("U", "Strain Energy", "Total elastic energy stored in the deformed structure."),
                            ("P_i", "Load", "Concentrated force acting at the evaluation point.")
                        ],
                        "variables": [
                            (r"\delta_i", "Deflection at point of load application", "m", "in"),
                            ("U", "Total strain energy of the elastic body", "J", "in·lbf"),
                            ("P_i", "Concentrated force at coordinate i", "N", "lbf"),
                            ("M(x)", "Bending moment equation along span", "N·m", "lbf·in"),
                        ],
                        "rule": "Exact virtual-work formulation for statically determinate and indeterminate beams."
                    }
                ]
            },
            {
                "group_name": "Column Stability & Axial Buckling",
                "source": "Hicks Ch. 3 (Column Formulas) & AISC LRFD",
                "formulas": [
                    {
                        "concept": "Euler Elastic Column Buckling",
                        "latex": r"P_{\text{cr}} = \frac{n \pi^2 E I}{L^2} = \frac{n \pi^2 E A}{(L/r)^2}",
                        "purpose": "Calculates the maximum axial compressive load that a slender column can carry before bowing laterally.",
                        "components": [
                            ("P_cr", "Critical Buckling Load", "Compressive force threshold triggering sudden lateral instability (Newtons or kips)."),
                            ("n", "End Fixity Factor", "1.0 for pinned-pinned; 4.0 for fixed-fixed; 0.25 for cantilever."),
                            ("L/r", "Slenderness Ratio", "Ratio of unbraced length to radius of gyration.")
                        ],
                        "variables": [
                            (r"P_{\text{cr}}", "Critical buckling capacity", "N", "lbf / kip"),
                            ("n", "End fixity condition (1.0 pinned-pinned, 4.0 fixed-fixed, 0.25 cantilever)", "constant", "constant"),
                            ("L/r", "Effective slenderness ratio", "ratio", "ratio"),
                            ("r", "Least radius of gyration (sqrt(I/A))", "m", "in"),
                        ],
                        "rule": "Valid for slender columns when slenderness ratio L/r exceeds critical threshold Cc."
                    },
                    {
                        "concept": "AISC LRFD Axially Loaded Column Capacity",
                        "latex": r"\phi P_n = 0.85 A_g F_{\text{cr}}, \quad F_{\text{cr}} = 0.658^{\lambda_c^2} F_y \ (\lambda_c \le 1.5)",
                        "purpose": "AISC industry standard formula providing factored design compression capacity accounting for initial crookedness and residual stresses.",
                        "components": [
                            ("φP_n", "Design Strength", "Factored axial compressive resistance (kips or kN)."),
                            ("A_g", "Gross Area", "Total cross-sectional steel area."),
                            ("F_cr", "Critical Stress", "Calculated inelastic or elastic buckling stress limit.")
                        ],
                        "variables": [
                            (r"\phi P_n", "Factored design axial compressive strength", "N", "kips"),
                            ("A_g", "Gross cross-sectional steel area", "m²", "in²"),
                            ("F_{\text{cr}}", "Critical buckling stress", "Pa", "ksi"),
                            (r"\lambda_c", r"\frac{KL}{r \pi}\sqrt{\frac{F_y}{E}} (column slenderness parameter)", "ratio", "ratio"),
                        ],
                        "rule": "Unified American Institute of Steel Construction specification for building structural columns."
                    }
                ]
            },
            {
                "group_name": "Concrete Mechanics & Foundation Stability",
                "source": "Hicks Ch. 4 & 5 (Concrete & Soil Mechanics) & ACI 318",
                "formulas": [
                    {
                        "concept": "ACI 318 Concrete Modulus of Elasticity",
                        "latex": r"E_c = 57,000\sqrt{f'_c} \ \text{(USCS, psi)} \ = 4,700\sqrt{f'_c} \ \text{(SI, MPa)}",
                        "purpose": "Empirical formula established by the American Concrete Institute to calculate the secant modulus of concrete stiffness from standard 28-day cylinder compressive strength.",
                        "components": [
                            ("E_c", "Concrete Modulus", "Stiffness modulus used for structural frame deflection calculations."),
                            ("f'_c", "Compressive Strength", "Specified 28-day compressive break strength.")
                        ],
                        "variables": [
                            ("E_c", "Secant modulus of elasticity of concrete", "MPa", "psi"),
                            ("f'_c", "28-day specified cylinder compressive strength", "MPa", "psi"),
                        ],
                        "rule": "Standard stiffness benchmark for reinforced concrete structural members."
                    },
                    {
                        "concept": "Prandtl-Terzaghi Ultimate Soil Bearing Capacity",
                        "latex": r"q_u = \frac{c}{\tan\phi} + \frac{1}{2}\gamma_{\text{dry}} b \sqrt{K_p}\left(K_p e^{\pi \tan\phi} - 1\right)",
                        "purpose": "Predicts the maximum ground pressure that a footing can transfer into supporting subgrade soils before shear failure occurs.",
                        "components": [
                            ("q_u", "Bearing Capacity", "Ultimate load intensity per unit foundation contact area (Pa or psf)."),
                            ("c", "Soil Cohesion", "Shearing strength possessed by intrinsic soil cohesion."),
                            ("φ", "Friction Angle", "Internal angle of granular friction between soil particles."),
                            ("K_p", "Passive Coefficient", "Rankine/Coulomb passive earth pressure multiplier.")
                        ],
                        "variables": [
                            ("q_u", "Ultimate soil bearing pressure", "Pa", "lb/ft²"),
                            ("c", "Soil cohesion", "Pa", "lb/ft²"),
                            (r"\phi", "Angle of internal soil friction", "degrees", "degrees"),
                            (r"\gamma_{\text{dry}}", "Dry unit weight of supporting soil", "N/m³", "lb/ft³"),
                            ("K_p", r"\tan^2(45^\circ + \phi/2) (passive pressure coefficient)", "ratio", "ratio"),
                        ],
                        "rule": "Determines footing and foundation stability against geotechnical soil shear failure."
                    }
                ]
            }
        ]
    },
    "chemical_process": {
        "name": "Chemical & Environmental Process Engineering",
        "primary_source": "Hicks & Chopey (Handbook of Chemical Engineering Calculations) & AIChE",
        "domains": ["chemical", "biochemical", "sludge", "reactor", "digestion", "kinetics", "catalyst", "filtration"],
        "formula_groups": [
            {
                "group_name": "Biochemical Reaction Kinetics & Digestion",
                "source": "Hicks Ch. 13 (Environmental Protection & Monod Kinetics)",
                "formulas": [
                    {
                        "concept": "Complete-Mix Activated Bioreactor Volume (Monod Kinetics)",
                        "latex": r"V_r = \frac{\theta_c \cdot Q \cdot Y \cdot (S_0 - S)}{X_a \cdot (1 + k_d \theta_c)}",
                        "purpose": "Sizes the required continuous stirred-tank bioreactor volume to guarantee complete organic substrate removal under bacterial kinetics.",
                        "components": [
                            ("V_r", "Reactor Volume", "Total liquid holding capacity needed for biological digestion."),
                            ("θ_c", "Mean Cell Residence Time", "Average microbial sludge retention time (sludge age)."),
                            ("Q", "Influent Flow Rate", "Daily wastewater volumetric flow rate."),
                            ("S_0 - S", "Substrate Consumed", "Organic material removed by microbial digestion."),
                            ("X_a", "Biomass Concentration", "Mixed liquor volatile suspended solids (MLVSS)."),
                            ("k_d", "Endogenous Decay", "Natural cell mass decay rate constant.")
                        ],
                        "variables": [
                            ("V_r", "Bioreactor tank volume", "m³", "Mgal"),
                            (r"\theta_c", "Mean cell residence time (sludge age)", "days", "days"),
                            ("Q", "Influent volumetric process flow rate", "m³/day", "Mgd"),
                            ("Y", "Maximum cell yield coefficient", "mg VSS/mg BOD₅", "ratio"),
                            ("S_0, S", "Influent and effluent substrate BOD concentration", "mg/L", "mg/L"),
                            ("X_a", "Active biomass concentration (MLVSS)", "mg/L", "mg/L"),
                            ("k_d", "Endogenous microbial decay coefficient", "day⁻¹", "day⁻¹"),
                        ],
                        "rule": "Sizes continuous stirred-tank reactors for complete organic matter conversion."
                    }
                ]
            }
        ]
    }
}


def detect_engineering_vocations(pattern_title: str, domain_summary: str = "") -> list[str]:
    """Detect the relevant engineering vocations for a given pattern based on keywords and heuristics."""
    combined = (f"{pattern_title} {domain_summary}").lower()
    scores: dict[str, int] = {}

    for voc_id, voc_data in ENGINEERING_VOCATIONS.items():
        score = 0
        for kw in voc_data["domains"]:
            matches = len(re.findall(r"\b" + re.escape(kw) + r"\b", combined))
            score += matches * 2
            if kw in combined:
                score += 1
        scores[voc_id] = score

    if any(k in combined for k in ["satellite", "swarm", "telecom", "handover", "non-terrestrial", "ntn", "cellular"]):
        scores["electrical_telecom"] = scores.get("electrical_telecom", 0) + 15
        scores["mechanical"] = scores.get("mechanical", 0) + 5

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    selected = [voc_id for voc_id, s in ranked if s > 0]
    return selected


def get_vocation_details(vocation_id: str) -> dict[str, Any] | None:
    """Retrieve the full formula catalog for a given vocation."""
    return ENGINEERING_VOCATIONS.get(vocation_id)


def generate_handbook_formulas_html(vocation_ids: list[str]) -> str:
    """Render an HTML card displaying active engineering formulas with rich pop-up tags on every word, symbol, and unit."""
    cards_html = []

    for voc_id in vocation_ids:
        voc = ENGINEERING_VOCATIONS.get(voc_id)
        if not voc:
            continue

        groups_html = []
        for grp in voc["formula_groups"]:
            formulas_html = []
            for f in grp["formulas"]:
                # 1. Purpose badge
                purpose_html = ""
                if f.get("purpose"):
                    p_desc = _html.escape(str(f.get("purpose") or ""))
                    purpose_html = (
                        f"<div style='margin:6px 0 10px 0;'>"
                        f"<span class='eng-badge-tag' data-term='Formula Purpose' data-tooltip='{p_desc}' style='background:#fef3c7;color:#92400e;border:1px solid #fde68a;padding:3px 10px;border-radius:6px;font-size:11.5px;font-weight:700;display:inline-flex;align-items:center;gap:6px;'>"
                        f"🎯 <b>Formula Purpose:</b> {p_desc}</span>"
                        f"</div>"
                    )

                # 2. Interactive Formula Component Breakdown Pill Bar
                components_html = ""
                if f.get("components"):
                    pills = []
                    for sym, label, desc in f["components"]:
                        pills.append(
                            f"<span class='eng-tag' data-term='{_html.escape(sym)}' data-tooltip='{_html.escape(desc)}' "
                            f"style='background:#ffffff;border:1px solid #cbd5e1;padding:2px 8px;border-radius:4px;font-size:11.5px;color:#1e293b;'>"
                            f"<b>{_html.escape(sym)}</b>: {_html.escape(label)}</span>"
                        )
                    components_html = (
                        f"<div style='margin:8px 0;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;padding:8px 12px;'>"
                        f"<div style='font-size:11px;font-weight:700;color:#475569;margin-bottom:6px;text-transform:uppercase;'>🔍 Interactive Formula Breakdown (Hover each symbol):</div>"
                        f"<div style='display:flex;flex-wrap:wrap;gap:6px;'>{''.join(pills)}</div>"
                        f"</div>"
                    )

                # 3. Variable Table with pop-up tags on Symbol, Parameter, SI, and USCS units
                var_rows = []
                for v in f["variables"]:
                    sym_clean = v[0].replace(r"\\", "").replace("{", "").replace("}", "").strip()
                    sym_tag = wrap_tag(sym_clean, display_text=f"<code>{v[0]}</code>", role=f"Mathematical symbol in {f['concept']}")
                    param_tag = wrap_tag(v[1], role="Physical / engineering variable")
                    unit_si_tag = wrap_tag(v[2], role="International System (SI) metric unit")
                    unit_uscs_tag = wrap_tag(v[3], role="United States Customary System (USCS) imperial unit")
                    var_rows.append(
                        f"<tr><td style='padding:5px 8px;'>{sym_tag}</td>"
                        f"<td style='padding:5px 8px;'>{param_tag}</td>"
                        f"<td style='padding:5px 8px;color:#475569;'>{unit_si_tag} &middot; {unit_uscs_tag}</td></tr>"
                    )

                # 4. Design Rule
                rule_text = f.get("rule", "")
                rule_html = (
                    f"<div style='font-size:11.5px;color:#334155;margin-top:8px;padding-top:6px;border-top:1px dashed #cbd5e1;'>"
                    f"<span class='eng-tag' data-term='Design Rule' data-tooltip='Mandatory engineering design constraint and safety boundary defined by professional standards.'><b>📐 Design Rule:</b></span> "
                    f"{_html.escape(rule_text)}</div>"
                )

                formulas_html.append(
                    f"<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin-bottom:14px;box-shadow:0 1px 2px rgba(0,0,0,0.02);'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;'>"
                    f"<div style='font-weight:700;font-size:14px;color:#0f172a;'>📐 {wrap_tag(f['concept'])}</div>"
                    f"</div>"
                    f"{purpose_html}"
                    f"<div style='padding:10px 14px;background:#ffffff;border:1px solid #cbd5e1;border-radius:8px;margin:8px 0;text-align:center;font-size:15px;overflow-x:auto;box-shadow:inset 0 1px 2px rgba(0,0,0,0.02);'>"
                    f"$${f['latex']}$$"
                    f"</div>"
                    f"{components_html}"
                    f"<table style='width:100%;font-size:11.5px;border-collapse:collapse;margin-top:8px;background:#ffffff;border-radius:6px;overflow:hidden;border:1px solid #e2e8f0;'>"
                    f"<thead><tr style='background:#f1f5f9;color:#334155;text-align:left;'>"
                    f"<th style='padding:6px 8px;'>{wrap_tag('Symbol')}</th><th style='padding:6px 8px;'>{wrap_tag('Parameter')}</th><th style='padding:6px 8px;'>{wrap_tag('Units')} (SI &middot; USCS)</th></tr></thead>"
                    f"<tbody>{''.join(var_rows)}</tbody>"
                    f"</table>"
                    f"{rule_html}"
                    f"</div>"
                )

            # Group header with tags on every word
            grp_words = []
            for w in grp["group_name"].split():
                clean_w = w.strip("&,()")
                if clean_w in TERM_GLOSSARY:
                    grp_words.append(wrap_tag(clean_w, display_text=w))
                else:
                    grp_words.append(_html.escape(w))
            grp_title_tagged = " ".join(grp_words)

            groups_html.append(
                f"<div style='margin-top:14px;'>"
                f"<div style='font-weight:700;font-size:14px;color:#1e293b;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin-bottom:10px;'>"
                f"📚 {grp_title_tagged} <span style='font-size:11.5px;color:#64748b;font-weight:normal;'>({_html.escape(grp['source'])})</span>"
                f"</div>"
                f"{''.join(formulas_html)}"
                f"</div>"
            )

        # Domain header with tags on every word
        voc_words = []
        for w in voc["name"].split():
            clean_w = w.strip("&,()")
            if clean_w in TERM_GLOSSARY:
                voc_words.append(wrap_tag(clean_w, display_text=w))
            else:
                voc_words.append(_html.escape(w))
        voc_title_tagged = " ".join(voc_words)

        src_words = []
        for w in voc["primary_source"].split():
            clean_w = w.strip("&,()")
            if clean_w in TERM_GLOSSARY:
                src_words.append(wrap_tag(clean_w, display_text=w))
            else:
                src_words.append(_html.escape(w))
        src_title_tagged = " ".join(src_words)

        domain_badge = wrap_badge(
            "Authoritative Handbook Domain",
            "Peer-reviewed, accredited engineering discipline codified in official standards (McGraw-Hill, ACI, AISC, ASME, IEEE, AIChE)."
        )

        cards_html.append(
            f"<div style='background:#ffffff;border:1px solid #cbd5e1;border-radius:12px;padding:18px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,0.03);'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:12px;'>"
            f"<div>{domain_badge} "
            f"<b style='font-size:15px;color:#0f172a;margin-left:8px;'>{voc_title_tagged}</b></div>"
            f"<span style='font-size:11.5px;color:#475569;background:#f1f5f9;padding:4px 10px;border-radius:6px;border:1px solid #e2e8f0;'>Source: {src_title_tagged}</span>"
            f"</div>"
            f"{''.join(groups_html)}"
            f"</div>"
        )

    registry_title_tag = wrap_tag("Authoritative Engineering Handbook & Formulas Registry", display_text="Authoritative Engineering Handbook &amp; Formulas Registry")
    return (
        f"<div class='handbook-registry-wrap' style='margin-top:20px;'>"
        f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>"
        f"<span style='font-size:18px;'>📖</span>"
        f"<h4 style='margin:0;font-size:15px;color:#0f172a;'>{registry_title_tag}</h4>"
        f"</div>"
        f"<p style='font-size:12.5px;color:#475569;margin-top:0;margin-bottom:14px;'>"
        f"Calibrated physical laws and exact mathematical formulations from Tyler G. Hicks (Civil &amp; Engineering Calculations), "
        f"Dan B. Marghitu (Mechanical Engineering), and AIChE Standards. <i>Hover over or tap any term, symbol, or formula purpose for instant explanations.</i>"
        f"</p>"
        f"{''.join(cards_html)}"
        f"</div>"
    )