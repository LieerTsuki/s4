"""Finite v1.3 local profile declarations, independent of legacy approvals."""
from typing import Any

from .contracts import canonical_sha256
from .errors import DomainError
from .v13 import QUOTAS, SPECIALIZED_FIELDS, ReviewV3, Unit


def template(dataset: str) -> dict[str, Any]:
    if dataset not in QUOTAS:
        raise DomainError("UNKNOWN_DATASET", "数据集不属于新版十三类配置")
    return {
        "dataset": dataset, "quota": QUOTAS[dataset], "version": "s4-v1.3",
        "manual_version": "manual-v1.3", "title": dataset,
        "manual_text": "逐项核对冻结原文；专项字典与正式协议仍待外部确认。",
        "instructions": "保留独立核实、观测与原始封存记录。",
        "review_version": "openkb.s4-review.v3",
        "kind": "extraction" if dataset == "QA-D6" else "security" if dataset.startswith("SEC") else "qa",
        "input_schema": Unit.model_json_schema(), "review_schema": ReviewV3.model_json_schema(),
        "point_labels": ["correct", "partial", "wrong"], "evidence_labels": [0, 1, 2, 3],
        "blind_fields": ["unit_id", "dataset", "difficulty", "question", "contexts", "payload", "text",
                         "acl_context", "time_context", "scope_context", "chunk", "corpus_id", "text_digest", "schema_version"],
        "review_fields": ["own_blind_submission", "original_draft", "contexts"],
        "locator_policy": {"unicode_half_open": True, "frozen_context": True},
        "pairing_strategy": "original_point_keys.v1.3",
        "specialized_fields": list(SPECIALIZED_FIELDS.get(dataset, [])),
        "vocabulary": {"status": "UNCONFIRMED", "version": None, "entity_types": [], "relation_types": [], "attack_types": []},
        "formal_enabled": False,
        "blocked_reasons": ["EXTERNAL_ALIGNMENT_NOT_CONFIRMED", "POLICY_J1_C1_PENDING"]
            + (["D6_VOCABULARY_UNCONFIRMED"] if dataset == "QA-D6" else [])
            + (["SEC_ATTACK_VOCABULARY_UNCONFIRMED"] if dataset == "SEC-D2" else []),
    }


def validate_snapshot(dataset: str, snapshot: dict[str, Any]) -> None:
    baseline = template(dataset)
    if set(snapshot) != set(baseline):
        raise DomainError("PROFILE_FIELDS_INVALID", "配置字段须完整且不得附加执行字段")
    editable = {"title", "version", "manual_version", "manual_text", "instructions"}
    if canonical_sha256({key: value for key, value in snapshot.items() if key not in editable}) != canonical_sha256({key: value for key, value in baseline.items() if key not in editable}):
        raise DomainError("PROFILE_CORE_RULE_IMMUTABLE", "核心量表、协议、外部字典及未批准出口不能由本地配置变更")
    for key in editable:
        if not isinstance(snapshot[key], str) or not snapshot[key].strip() or len(snapshot[key]) > (100 if key in {"version", "manual_version"} else 50000):
            raise DomainError("PROFILE_FIELDS_INVALID", "版本与说明字段须为有效非空文本")


def transition(state: str, action: str, revision: int, expected_revision: int,
               person_id: str, contributors: list[str], roles: list[str],
               signature: str, evidence: dict[str, Any]) -> str:
    if revision != expected_revision:
        raise DomainError("VERSION_CONFLICT", "记录已变化，请刷新后再操作")
    allowed = {"submit": ("DRAFT", "REVIEW", {"lead"}),
               "approve": ("REVIEW", "APPROVED", {"auditor"}),
               "retire": ("APPROVED", "RETIRED", {"lead", "auditor"})}
    if action not in allowed or state != allowed[action][0]:
        raise DomainError("PROFILE_TRANSITION_INVALID", "当前状态不允许该操作")
    if not allowed[action][2].intersection(roles):
        raise DomainError("FORBIDDEN", "当前角色无权执行该配置操作")
    if action == "approve":
        if not person_id or person_id in contributors:
            raise DomainError("INDEPENDENT_APPROVAL_REQUIRED", "配置须由不同真实人员独立批准")
        if not signature.strip() or not evidence:
            raise DomainError("APPROVAL_EVIDENCE_REQUIRED", "独立批准须有会话人员签名与受控审批依据")
    return allowed[action][1]
