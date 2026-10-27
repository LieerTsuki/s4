"""Seeded, order-independent stratified sample with an auditable allocation."""

from __future__ import annotations

import random
from collections import defaultdict
from fractions import Fraction
from typing import Any

from .errors import DomainError
from .profiles import DIFFICULTIES, get_profile


def sample_units(units: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    """Sample max(8, ceil(N/10)) per dataset, recording insufficient populations.

    Largest remainder supplies the initial proportional counts. A deterministic
    transfer from a stratum with more than one sample preserves existing small
    difficulty strata. No duplicate units or hidden post-label range changes.
    """
    if type(seed) is not int:
        raise DomainError("INVALID_SEED", "抽样种子必须为整数。")
    if not isinstance(units, list):
        raise DomainError("INVALID_POPULATION", "抽样总体必须为单元数组。")
    if not units:
        raise DomainError("EMPTY_POPULATION", "抽样总体不能为空。")
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    seen: set[str] = set()
    for unit in units:
        if not isinstance(unit, dict):
            raise DomainError("INVALID_POPULATION", "抽样单元必须为对象。")
        unit_id, dataset, difficulty = (
            unit.get("unit_id"),
            unit.get("dataset"),
            unit.get("difficulty"),
        )
        if not isinstance(unit_id, str) or not unit_id or unit_id in seen:
            raise DomainError("DUPLICATE_OR_INVALID_UNIT", "抽样总体包含重复或无效unit_id。")
        if not isinstance(dataset, str):
            raise DomainError("UNKNOWN_DATASET", "抽样总体缺少数据集。")
        get_profile(dataset)
        if difficulty not in DIFFICULTIES:
            raise DomainError("INVALID_DIFFICULTY", "难度仅允许简单/中等/困难。")
        seen.add(unit_id)
        grouped[dataset][difficulty].append(unit_id)

    selected: list[str] = []
    strata: list[dict[str, Any]] = []
    blockers: list[str] = []
    for dataset in sorted(grouped):
        groups = grouped[dataset]
        population = sum(map(len, groups.values()))
        required = max(8, (population + 9) // 10)
        actual = min(required, population)
        ideals = {level: Fraction(actual * len(groups[level]), population) for level in groups}
        allocated = {level: ideal.numerator // ideal.denominator for level, ideal in ideals.items()}
        order = sorted(
            groups,
            key=lambda level: (-(ideals[level] - allocated[level]), DIFFICULTIES.index(level)),
        )
        for level in order[: actual - sum(allocated.values())]:
            allocated[level] += 1
        adjustments = {level: 0 for level in groups}
        for level in DIFFICULTIES:
            if level not in groups or allocated[level] > 0:
                continue
            donors = [other for other in groups if allocated[other] > 1]
            if not donors:
                raise DomainError("STRATIFICATION_IMPOSSIBLE", "抽样量不能覆盖已有难度层。")
            donor = max(
                donors,
                key=lambda other: (
                    allocated[other] - ideals[other],
                    allocated[other],
                    -DIFFICULTIES.index(other),
                ),
            )
            allocated[donor] -= 1
            allocated[level] += 1
            adjustments[donor] -= 1
            adjustments[level] += 1
        for level in DIFFICULTIES:
            if level not in groups:
                continue
            candidates = sorted(groups[level])
            rng = random.Random(f"openkb.s4.sample.v1:{seed}:{dataset}:{level}")
            chosen = sorted(rng.sample(candidates, allocated[level]))
            selected.extend(chosen)
            strata.append(
                {
                    "dataset": dataset,
                    "difficulty": level,
                    "population_count": len(candidates),
                    "dataset_population_count": population,
                    "required_count": required,
                    "selected_count": len(chosen),
                    "selected_ids": chosen,
                    "seed": seed,
                    "coverage_adjustment": adjustments[level],
                    "algorithm_version": "largest_remainder_coverage.v1",
                }
            )
        if population < required:
            blockers.append(f"MINIMUM_SAMPLE_NOT_MET:{dataset}:{population}/{required}")
    return {"selected_ids": selected, "strata": strata, "blocked_reasons": blockers}
