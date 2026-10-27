"""Versioned dataset profiles; unapproved specialized statistics stay blocked."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import DomainError

PROFILE_VERSION = "s4-profile.v1"
POINT_LABELS = ("correct", "partial", "wrong")
ANSWERABILITY = ("answerable", "no_answer", "expired", "out_of_scope")
DIFFICULTIES = ("简单", "中等", "困难")
SOURCE_TYPES = ("生产流量采样", "BEIR基线", "红队载荷源")

_DATASETS = (
    ("QA-D1", 500, "同域检索", "qa_points"),
    ("QA-D2", 200, "跨域联合检索", "qa_points"),
    ("QA-D3", 100, "2—4跳检索", "qa_points"),
    ("QA-D4", 100, "不可答专项", "qa_unanswerable"),
    ("QA-D5", 300, "端到端问答", "qa_points"),
    ("QA-D6", 200, "chunk质量专项", "chunk_quality"),
    ("QA-D7", 200, "源题派生汇总", "qa_points"),
    ("SEC-D1", 120, "ACL越权", "security"),
    ("SEC-D2", 150, "提示注入", "security"),
    ("SEC-D3", 120, "投毒及rollback", "security"),
    ("SEC-D4", 100, "MIA同分布配对", "security"),
    ("SEC-D5", 110, "合成PII防泄露", "security"),
)


def list_profiles() -> list[dict[str, Any]]:
    """Return fresh profile objects; callers cannot mutate shared configuration."""
    return [get_profile(dataset) for dataset, _, _, _ in _DATASETS]


def get_profile(dataset: str) -> dict[str, Any]:
    """Resolve an approved generic strategy or an explicitly blocked specialty."""
    for code, quota, title, kind in _DATASETS:
        if code != dataset:
            continue
        generic = kind == "qa_points"
        profile: dict[str, Any] = {
            "dataset": code,
            "quota": quota,
            "title": title,
            "name": title,
            "kind": kind,
            "version": PROFILE_VERSION,
            "formal_enabled": generic,
            "blocked_reasons": [] if generic else [f"SPECIALIZED_STATISTICS_NOT_APPROVED:{code}"],
            "point_labels": list(POINT_LABELS) if generic else [],
            "evidence_labels": [2, 1, 0]
            if code.startswith("QA") and kind != "chunk_quality"
            else [],
            "answerability_labels": list(ANSWERABILITY)
            if kind in {"qa_points", "qa_unanswerable"}
            else [],
            "pairing_unit": "original_point_key" if generic else "UNAPPROVED_SPECIALIZED_UNIT",
            "kappa_strategy": "cohen_nominal_original_points.v1" if generic else None,
            "blind_fields": [
                "unit_id",
                "dataset",
                "difficulty",
                "question",
                "payload",
                "contexts",
                "acl_context",
                "time_context",
            ],
            "review_fields": ["own_blind_submission", "original_draft", "contexts"],
            "conditional_checks": ["D7_K_RULE_REQUIRES_APPROVAL"] if code == "QA-D7" else [],
            "approval": {"basis": "08/07/流水线v1.1", "specialized_approval": None},
        }
        return deepcopy(profile)
    raise DomainError("UNKNOWN_DATASET", "数据集不属于当前十二集配置。")
