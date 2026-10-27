"""Original-label Cohen's kappa, with exact arithmetic for gate boundaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from .errors import DomainError
from .profiles import POINT_LABELS


def calculate_agreement(left: Sequence[str], right: Sequence[str]) -> dict[str, Any]:
    """Compute unrounded nominal kappa; undefined statistics never become a pass.

    Only frozen original point labels belong here. Dataset, round, person-pair,
    revision and point-key alignment are validated by the workflow before call.
    Fractions avoid a floating-point 0.6 boundary slipping into REJECT_BATCH.
    See approved design section 5 and source 07 section 10.
    """
    if any(not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)) for vector in (left, right)):
        raise DomainError("INVALID_POINT_VECTOR", "标签向量必须为分类标签序列。")
    for label in (*left, *right):
        if not isinstance(label, str) or label not in POINT_LABELS:
            raise DomainError("INVALID_POINT_LABEL", "要点标签仅允许correct/partial/wrong。")
    result: dict[str, Any] = {
        "kappa": None,
        "po": None,
        "pe": None,
        "n": len(left),
        "verdict": "BLOCKED",
        "blocked_reasons": [],
        "algorithm_version": "cohen_nominal_original_points.v1",
    }
    if len(left) != len(right):
        result["blocked_reasons"] = ["MISSING_LABEL_PAIRS"]
        return result
    count = len(left)
    if count == 0:
        result["blocked_reasons"] = ["EMPTY_LABEL_VECTOR"]
        return result
    counts_a, counts_b = Counter(left), Counter(right)
    po = Fraction(sum(a == b for a, b in zip(left, right, strict=True)), count)
    pe = sum(
        (Fraction(counts_a[label] * counts_b[label], count * count) for label in POINT_LABELS),
        Fraction(),
    )
    result.update(po=float(po), pe=float(pe))
    if pe == 1:
        result["blocked_reasons"] = ["UNDEFINED_KAPPA_PE_ONE"]
        return result
    kappa = (po - pe) / (1 - pe)
    verdict = (
        "ACCEPT"
        if kappa >= Fraction(7, 10)
        else "ARBITRATE"
        if kappa >= Fraction(3, 5)
        else "REJECT_BATCH"
    )
    result.update(kappa=float(kappa), verdict=verdict)
    return result
