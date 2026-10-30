# Sentinari by Inspirari

[![License: Proprietary](https://img.shields.io/badge/License-Proprietary%20%26%20All%20Rights%20Reserved-red.svg?style=for-the-badge)](LICENSE.md)
[![White Paper: 15-Page Edition](https://img.shields.io/badge/White%20Paper-15--Page%20Constitutional%20Edition-0066cc.svg?style=for-the-badge)](constitution/SENTINARI_CONSTITUTIONAL_WHITEPAPER_15_PAGE.md)
[![Assessment Matrix: Societal Manifesto](https://img.shields.io/badge/Assessment%20Matrix-7--D%20Societal%20Manifesto-10b981.svg?style=for-the-badge)](constitution/THE_7_DIMENSIONAL_ASSESSMENT_MATRIX_FOR_SOCIETY.md)
[![User Guide: Official PDF Manual](https://img.shields.io/badge/User%20Guide-Official%20PDF%20Manual-e11d48.svg?style=for-the-badge)](docs/SENTINARI_USER_GUIDE_AND_HELP_INDEX.pdf)
[![Cloud Run Production Studio](https://img.shields.io/badge/Production%20Studio-Cloud%20Run-6366f1?style=for-the-badge&logo=googlecloud)](https://sentinari-core-250830594433.us-central1.run.app)

> ⚠️ **PROPRIETARY INTELLECTUAL PROPERTY & EVALUATION NOTICE**  
> **Copyright © 2026 Dr. Pierre C. Wepener. All Rights Reserved.**  
> This codebase is published **strictly for view-only inspection, academic peer review, and due diligence evaluation**. Downloading, cloning (`git clone`), copying, reproducing, distributing, modifying, or utilizing this codebase for software development, commercial applications, or training external AI/ML models is **strictly prohibited** without prior written authorization. See [LICENSE.md](LICENSE.md).

> 🌐 **Live Public Showroom**: [https://ongalali.github.io/sentinari/](https://ongalali.github.io/sentinari/)  
> ⚡ **Cloud Run Production Studio**: [https://sentinari-core-250830594433.us-central1.run.app](https://sentinari-core-250830594433.us-central1.run.app)

---

## 🏛️ CORE FLAGSHIP PUBLICATIONS & SOCIETAL FRAMEWORKS

Welcome to the official repository for **Sentinari: The Emergence of Responsible Intelligence**, conceived, researched, and engineered independently by **Dr. Pierre C. Wepener** (University of Johannesburg).

Direct, one-click links to the foundational constitutional documents and mathematical models:

| Flagship Document / Framework | Scope & Description | Direct One-Click Link |
| :--- | :--- | :---: |
| 📄 **The 15-Page Constitutional White Paper** | *A Paradigm Shift from Speculative Fluency to Mathematically Accountable, Constitutional Discovery*. Complete with all 8 Articles, Aristotelian Causality, 7-D Assessment Matrix, Pseudo-Dynamics vector field physics, and empirical oncology/radar proofs. | [**📖 Read White Paper (.md)**](constitution/SENTINARI_CONSTITUTIONAL_WHITEPAPER_15_PAGE.md) |
| ⚖️ **The 7-Dimensional Assessment Matrix for Society** | *A Mathematical Manifesto for a Sustainable Society*. An un-falsifiable coupled Gaussian bell-curve framework ($K, I, D, H, S, E, R$) to measure, balance, and safeguard human agency, knowledge, ethics, and systemic risk. Free for worldwide distribution under Creative Commons CC BY-NC-SA 4.0. | [**⚖️ Read 7-D Matrix (.md)**](constitution/THE_7_DIMENSIONAL_ASSESSMENT_MATRIX_FOR_SOCIETY.md) |
| 🏛️ **Institutional Showcase Portal & Investor Vault** | Public investor gateway containing the Due Diligence Protocol, Mutual NDA template, and executive briefing for Google Cloud, DeepMind, sovereign funds, and research alliances. | [**🏛️ Open Showcase Portal**](showcase_portal/README.md) |
| 📘 **Complete User Guide & Master Help Index** | *Official Operating Field Manual & Technical Reference Index*. Complete 10-chapter manual covering workspaces registry, tour recording, pattern discovery, 7-D matrix, API directory, and full A–Z alphabetical help index. | [**📕 Download Official PDF (with Index)**](docs/SENTINARI_USER_GUIDE_AND_HELP_INDEX.pdf)<br>[**📖 Read Online (.md)**](docs/SENTINARI_USER_GUIDE_AND_HELP_INDEX.md) |
| 📥 **Publication Microsoft Word Documents (.docx)** | Ready-to-print executive Word documents formatted with 1-inch margins, navy typography, and embedded figures. | [**📥 White Paper (.docx)**](showcase_portal/Sentinari_15_Page_Constitutional_Whitepaper.docx)<br>[**📥 7-D Matrix (.docx)**](showcase_portal/The_7_Dimensional_Assessment_Matrix_For_Society.docx) |

---


A sovereign, zero-cloud AI research platform: a grounded knowledge library, a
Qualia state model over the conversation engine, an examiner that grades
applied knowledge, scientific pattern discovery, and an ONNX inference server
for the rig-day cutover.

## Quickstart

```
:: double-click (starts the inference server on :8100 and the core on :8099)
Sentinari-server\launch-all.bat

:: or, core only
launch-sentinari.bat
```

- Core (FastAPI + SQLite): `http://127.0.0.1:8099` — health at `/health`
- Inference server (ONNX): `http://127.0.0.1:8100` — `degraded:true` is the
  correct resting state until the ONNX engine is configured (see
  [docs/RIG_DAY_RUNBOOK.md](docs/RIG_DAY_RUNBOOK.md))
- The chat surface stays dark until a local model engine is present. That is
  the zero-cloud doctrine (§41), not a fault: nothing may call the cloud.

## Layout

| Path | Contents |
| --- | --- |
| `app/` | FastAPI core: conversation, playground, retrieval, ingestion, Qualia, examiner, firewall |
| `sentinel/` | Guardian layer: domains, gateway guardian, relationships, benchmarks |
| `config/` | `settings.yaml` (single source of runtime config), `persona_sentinari.yaml` (canonical persona seed) |
| `templates/` | User consoles (start menu, playground, qualia lab, direct chat, admin, learning, patterns, search, victus, video) |
| `assessments/` | Assessment ladder: HLE + SWE-bench Pro loaders (HF cache in data/), execution harness local-only |
| `Sentinari-server/` | ONNX inference server (:8100), converter kit, `launch-all.bat`, rig-day runbook |
| `scripts/` | One-shot maintenance scripts |
| `docs/` | Continuity log, validation protocol, SENTINEL review, credits, rig-day runbook |
| `tests/` | Self-verifying test modules (run with `python -m tests.<name>`) |
| `data/` | Runtime databases and artifacts (git-ignored; never commit) |

See [docs/architecture.md](docs/architecture.md) for the full tree with
annotations, suitable for the documentation image.

## Doctrine

- **Zero cloud.** All inference and embedding is local. Cloud providers are
  deleted from the code, not merely disabled; the LLM firewall polices the
  provider allowlist in `config/settings.yaml`.
- **The continuity log is the memory.** Every working session appends a `§`
  entry to [docs/CONTINUITY_LOG.md](docs/CONTINUITY_LOG.md) and commits it.
  Agents hold no memory between sessions; the log and git history do.
- **Fail closed.** Victus (the dormant challenger), the escalation queue, and
  every autonomous loop sit behind explicit config gates, all OFF by default.

## Verification

```
.venv\Scripts\python.exe -m app.victus        :: 13/13 self-test
.venv\Scripts\python.exe -m tests.test_sentinel
```

Owned and operated by Inspirari.
