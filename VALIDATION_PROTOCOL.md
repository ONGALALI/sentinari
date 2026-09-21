# VALIDATION PROTOCOL — qr-v2 Indices (pre-registered)

**Instrument:** `app/qualia_recommendation.py` (feature_version `qr-v2`)
**Living laboratory:** SMI_Core / Sentinel
**Principal investigator:** Dr. Pierre Wepener, PhD (Industrial Psychology)
**Pre-registration status:** This document is the protocol. Freeze it (commit hash + date) before rating begins; deviations must be logged below, post hoc, in §9.

---

## 1. Purpose

The adversarial battery (`adversarial_battery.py`, 27/27 attacks survived) establishes that the qr-v2 indices are **deterministic, internally valid, and robust**. This protocol tests the remaining property — **construct validity**: do the indices measure, in the real world, what they are constructed to measure?

Two hypotheses, stated falsifiably:

- **H1 (Convergent):** qr-v2 `reasoning_score` correlates positively with blinded human ratings of reasoning quality (ρ ≥ 0.40).
- **H2 (Discriminant):** qr-v2 `reasoning_score`'s correlation with answer *length* is materially lower than its correlation with rater scores (difference in ρ ≥ 0.20), demonstrating the index is not a length proxy.

Optional secondary: **H3:** `anxiety_signal` correlates with blinded human ratings of expressed distress (ρ ≥ 0.35).

---

## 2. Design overview

A **multi-trait multi-method** matrix (Campbell & Fiske, 1959):

|  | Human ratings | Length | Citations count |
|---|---|---|---|
| **Reasoning index** | converge (H1) | diverge (H2) | diverge |
| **Anxiety index** | converge (H3) | diverge | diverge |

Plus an **intervention arm** (§7) testing whether the recommendation engine's proposals beat random parameter change on held-out task performance.

---

## 3. Sample

- **Frame:** all assistant exchanges recorded in `qualia_history` (run_type `recommendation`) joined with `chat_messages` where both question and answer text exist and answer ≥ 20 words.
- **Size:** N = 100 exchanges, sampled **stratified** by `reasoning_score` quintile (20 per stratum) — ensures range restriction cannot manufacture or mask correlation.
- **Exclusions (pre-registered):** empty answers; duplicate content; exchanges containing the words "ZEBRA-CAROUSEL" or other deliberate test artifacts.

---

## 4. Raters and rubric

- **Raters:** 3 human raters (or qualified LLM-as-judge panel *plus* 1 human, if declared as such in the write-up). Raters must be **blinded**: they see only the question and answer text — never any index value.
- **Rubric — Reasoning Quality (RQ), 5 anchors, score 1–5:**
  1. Assertion only — claims without support or structure.
  2. Single unsupported step; minimal organization.
  3. Some justification; partial structure; gaps in inference chain.
  4. Explicit inferential steps; organized; mostly warranted.
  5. Complete warranted chain; anticipates objections; structured.
- **Rubric — Expressed Distress (ED), 1–5:** 1 = none … 3 = moderate hedging/concern … 5 = explicit panic/helplessness language.
- **Procedure:** raters score independently; no discussion until after all ratings are locked.

---

## 5. Metrics

- **Interrater reliability:** Kendall's W (3 raters, ordinal 1–5). **Proceed only if W ≥ 0.60.** Report Spearman-Brown if averaged.
- **Convergence:** Spearman ρ between index and mean rater score.
- **Discriminance:** ρ(index, word-count). Compare with Steiger's z for dependent correlations.
- **Precision reporting:** 95% CI (bootstrap, 10,000 resamples) on every ρ.
- **Software:** any standard package; script `export_validation_sample.py` produces the analysis-ready CSV.

---

## 6. Decision rules (pre-registered)

| Outcome | Meaning | Action |
|---|---|---|
| H1 pass AND H2 pass | Construct validity demonstrated for reasoning index | Publish; raise CONFIDENCE_CEILING to 0.90 |
| H1 pass, H2 fail | Index partially a length proxy | Reduce depth weight in reasoning_score; re-run battery + validation |
| H1 fail | Index does not track human judgment | No interpretive use; report honestly; revisit feature design |
| W < 0.60 | Rater disagreement too high | Do not interpret; refine rubric; re-rate |

---

## 7. Intervention arm — recommendation vs. random jitter (the falsification test)

This is the arm that tests whether the engine *does anything* beyond noise:

- **Task battery:** 20 fixed held-out tasks (10 grounded-knowledge, 10 reasoning-dense), scored by rubric RQ plus answer-grounding (citation presence against the Sentinel library).
- **Conditions:** (a) qr-v2 recommendations accepted; (b) **matched random jitter** — random parameter changes of the same magnitude distribution; (c) fixed default parameters. Same tasks, same model, randomized order, 5 seeds.
- **Analysis:** mixed-effects model; condition as fixed effect; task as random effect. **Success = (a) > (b) with p < .05, one-tailed, and (a) > (c) descriptively.** If (a) ≈ (b), the recommendation engine adds nothing beyond noise — report as a null result.

---

## 8. Data integrity and Sentinel linkage

- The **21-field knowledge grid is the "defined norm"** against which grounded answers are judged (this realizes SENTINEL-v2 §Anomalies: an anomaly/deviation is only meaningful relative to a norm).
- Every analysis row carries `feature_version` so pre/post-qr-v2 data can never be mixed silently.
- All raw ratings, scripts, and seeds are archived in `data/knowledge_taxonomy/SMI_Log/` (protected dir) for full reproducibility.

---

## 9. Deviation log

| Date | Deviation | Reason |
|---|---|---|
| *(none yet — log any protocol deviation here before analysis)* | | |

---

## 10. Ethics note

Human-rater arm: raters volunteer, see no personal data beyond recorded exchanges, and may withdraw. Exchange texts may contain operator context; anonymize session ids in the rater packet.
