from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _pearson(x_values: list[float], y_values: list[float]) -> float | None:
    if len(x_values) != len(y_values) or len(x_values) < 3:
        return None
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    x_scale = math.sqrt(sum((x - x_mean) ** 2 for x in x_values))
    y_scale = math.sqrt(sum((y - y_mean) ** 2 for y in y_values))
    denominator = x_scale * y_scale
    return None if denominator <= 1e-12 else numerator / denominator


def _average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][1] == ordered[position][1]:
            end += 1
        average_rank = ((position + 1) + end) / 2.0
        for idx in range(position, end):
            ranks[ordered[idx][0]] = average_rank
        position = end
    return ranks


def _krippendorff_alpha_interval(item_ratings: dict[str, list[float]]) -> float | None:
    usable = [ratings for ratings in item_ratings.values() if len(ratings) >= 2]
    all_values = [value for ratings in usable for value in ratings]
    total = len(all_values)
    if total < 3:
        return None

    observed_sum = 0.0
    for ratings in usable:
        pair_sum = sum(
            (ratings[left] - ratings[right]) ** 2
            for left in range(len(ratings))
            for right in range(left + 1, len(ratings))
        )
        observed_sum += (2.0 * pair_sum) / (len(ratings) - 1)
    observed_disagreement = observed_sum / total

    expected_pair_sum = sum(
        (all_values[left] - all_values[right]) ** 2
        for left in range(total)
        for right in range(left + 1, total)
    )
    expected_disagreement = (2.0 * expected_pair_sum) / (total * (total - 1))
    if expected_disagreement <= 1e-12:
        return 1.0 if observed_disagreement <= 1e-12 else None
    return 1.0 - (observed_disagreement / expected_disagreement)


def analyze_external_validation(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compare a heuristic index with ratings that were produced independently.

    Required row keys: item_id, rater_id, human_score, index_score. The
    index_score must be identical across rows for the same item.
    """

    ratings_by_item: dict[str, list[float]] = defaultdict(list)
    index_by_item: dict[str, float] = {}
    raters: set[str] = set()
    rejected_rows = 0

    for row in rows:
        item_id = str(row.get("item_id") or "").strip()
        rater_id = str(row.get("rater_id") or "").strip()
        human_score = _finite_float(row.get("human_score"))
        index_score = _finite_float(row.get("index_score"))
        if not item_id or not rater_id or human_score is None or index_score is None:
            rejected_rows += 1
            continue
        if item_id in index_by_item and abs(index_by_item[item_id] - index_score) > 1e-9:
            raise ValueError(f"index_score is inconsistent for item_id={item_id!r}")
        index_by_item[item_id] = index_score
        ratings_by_item[item_id].append(human_score)
        raters.add(rater_id)

    item_ids = sorted(item for item in ratings_by_item if ratings_by_item[item])
    human_means = [sum(ratings_by_item[item]) / len(ratings_by_item[item]) for item in item_ids]
    index_scores = [index_by_item[item] for item in item_ids]
    pearson = _pearson(index_scores, human_means)
    spearman = _pearson(_average_ranks(index_scores), _average_ranks(human_means))
    alpha = _krippendorff_alpha_interval(ratings_by_item)

    sufficiently_rated = len(item_ids) >= 20 and len(raters) >= 3
    reliable_ratings = alpha is not None and alpha >= 0.67
    claim_status = (
        "preliminary_external_association_only"
        if sufficiently_rated and reliable_ratings and pearson is not None and spearman is not None
        else "insufficient_for_validity_claim"
    )

    return {
        "measurement_status": claim_status,
        "items": len(item_ids),
        "raters": len(raters),
        "accepted_rows": sum(len(values) for values in ratings_by_item.values()),
        "rejected_rows": rejected_rows,
        "krippendorff_alpha_interval": alpha,
        "pearson_r": pearson,
        "spearman_rho": spearman,
        "human_mean_by_item": dict(zip(item_ids, human_means)),
        "index_score_by_item": dict(zip(item_ids, index_scores)),
        "limitations": [
            "Correlation does not establish construct validity or phenomenal consciousness.",
            "Ratings must be collected blind to the index outputs.",
            "A held-out confirmatory sample is required after any coefficient tuning.",
        ],
    }
