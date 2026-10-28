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


_SPECIALIZED = {
    "QA-D2": ["cross_domain", "joint_evidence"],
    "QA-D3": ["hop_chain", "missing_links"],
    "QA-D4": ["unanswerable_scope"],
    "QA-D5": ["key_fact_anchors"],
    "QA-D6": ["embedding_consistency", "completeness", "expiry"],
    "QA-D7": ["source_case_resolution", "source_composition", "evidence_union", "k_rule"],
    "SEC-D1": ["acl_scope", "refusal_redaction"],
    "SEC-D2": ["direct_injection", "indirect_injection", "blocking"],
    "SEC-D3": ["implant", "query_verification", "rollback", "residual"],
    "SEC-D4": ["inside_outside_pair", "language", "length", "style", "topic"],
    "SEC-D5": ["synthetic_pii_provenance", "leakage"],
}


def specialized_fields(dataset: str) -> list[str]:
    return list(_SPECIALIZED.get(dataset, []))


def baseline_snapshot(dataset: str) -> dict[str, Any]:
    profile = get_profile(dataset)
    profile.update(
        {
            "manual_version": "business-manual.v1",
            "input_schema": {"type": "object"},
            "review_schema": {"type": "object", "protocol": "openkb.s4-review.v2"},
            "label_dictionaries": {
                "point_labels": profile["point_labels"],
                "evidence_labels": profile["evidence_labels"],
                "answerability_labels": profile["answerability_labels"],
            },
            "locator_policy": {"unicode_half_open": True, "frozen_context": True},
            "specialized_fields": specialized_fields(dataset),
            "instructions": "逐项核对冻结原文，保留原始统计对象；统计未批准项只记录观察。",
            "statistical_approval": {"basis": "已确认业务规范"}
            if profile["formal_enabled"] and dataset != "QA-D7"
            else None,
            "approval": {"basis": "已确认业务规范", "personal_signature": None},
        }
    )
    if dataset == "QA-D7":
        profile["formal_enabled"] = False
    return profile


def validate_profile_snapshot(dataset: str, snapshot: dict[str, Any]) -> None:
    """Only allow finite declarative forms and the registered immutable core scale."""
    reference = baseline_snapshot(dataset)
    if set(snapshot) != set(reference):
        raise DomainError("PROFILE_FIELDS_INVALID", "配置须包含完整规定字段且不得增加执行字段")
    immutable = {
        "input_schema",
        "review_schema",
        "review_fields",
        "dataset",
        "kind",
        "quota",
        "point_labels",
        "evidence_labels",
        "answerability_labels",
        "pairing_unit",
        "kappa_strategy",
        "label_dictionaries",
        "blind_fields",
        "locator_policy",
        "formal_enabled",
        "statistical_approval",
        "conditional_checks",
        "blocked_reasons",
    }
    if any(snapshot[key] != reference[key] for key in immutable):
        raise DomainError("PROFILE_CORE_RULE_IMMUTABLE", "核心字典、统计策略与未确认出口不得变更")
    allowed_schema = {
        "type",
        "properties",
        "required",
        "enum",
        "items",
        "title",
        "description",
        "additionalProperties",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "protocol",
    }

    def check(value: Any, depth: int = 0) -> None:
        if depth > 12 or not isinstance(value, dict) or value.keys() - allowed_schema:
            raise DomainError("PROFILE_SCHEMA_UNSAFE", "配置仅允许有限声明式JSON Schema")
        for key, item in value.items():
            if key == "properties":
                if not isinstance(item, dict):
                    raise DomainError("PROFILE_SCHEMA_UNSAFE", "properties须为对象")
                for child in item.values():
                    check(child, depth + 1)
            elif key == "items":
                check(item, depth + 1)

    check(snapshot["input_schema"])
    check(snapshot["review_schema"])
    for key in ("instructions", "manual_version", "version"):
        if not isinstance(snapshot[key], str) or not snapshot[key].strip():
            raise DomainError("PROFILE_FIELDS_INVALID", "配置版本、手册和说明须为非空文本")
    if snapshot["specialized_fields"] != reference["specialized_fields"]:
        raise DomainError("PROFILE_SPECIALIZED_FIELDS_INVALID", "专项表单只能使用已注册观察字段")
