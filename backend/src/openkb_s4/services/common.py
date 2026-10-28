"""Shared access checks and immutable source projections."""

from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.profiles import get_profile
from ..models import (
    AnnotationBatch,
    Assignment,
    AuditEvent,
    Exposure,
    GoldRevision,
    SourceImport,
    Submission,
    UnitRevision,
    User,
)
from ..security import ApiError, require_independent, require_role


def audit(
    db: AsyncSession,
    request: Request | None,
    actor_id: str | None,
    action: str,
    object_id: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_id=actor_id,
            action=action,
            object_id=object_id,
            request_id=getattr(request.state, "request_id", "worker") if request else "worker",
            details=details or {},
        )
    )


async def get_batch(db: AsyncSession, batch_id: str, lock: bool = False) -> AnnotationBatch:
    query = select(AnnotationBatch).where(AnnotationBatch.id == batch_id)
    if lock:
        query = query.with_for_update()
    batch = await db.scalar(query)
    if not batch:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    return batch


async def business_batch(
    db: AsyncSession, user: User, batch_id: str, lock: bool = False
) -> AnnotationBatch:
    require_role(user, "lead", "auditor", "arbitrator")
    batch = await get_batch(db, batch_id, lock)
    require_independent(user, batch)
    if await db.scalar(select(Assignment.id).where(Assignment.batch_id==batch.id,Assignment.user_id==user.id).limit(1)):
        raise ApiError(403,'PARTICIPANT_RESTRICTED','本批历史参标人员仍不能读取或操作受限结果')
    return batch


async def source(db: AsyncSession, import_id: str) -> SourceImport:
    imported = await db.get(SourceImport, import_id)
    if not imported:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    return imported


def source_unit(imported: SourceImport, unit_id: str) -> dict[str, Any]:
    for unit in imported.payload["units"]:
        if unit["unit_id"] == unit_id:
            return dict(unit)
    raise ApiError(409, "CONTENT_MISSING", "冻结原始材料不完整")


def points(unit: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"point_key": f"P{i + 1:03d}", "text": str(value)}
        for i, value in enumerate(unit.get("gold", {}).get("answer_points", []))
    ]


def safe_material(unit: dict[str, Any], phase: str = "BLIND") -> dict[str, Any]:
    visible = (
        "question",
        "payload",
        "acl_context",
        "time_context",
        "scope_context",
        "chunk",
        "access_context",
        "inject_plan",
    )
    result = {key: unit[key] for key in visible if key in unit}
    if phase == "REVIEW":
        for name in ("quality_metrics", "key_facts", "source_case_ids", "evaluation_k"):
            if name in unit:
                result[name] = unit[name]
        if (
            unit.get("dataset") == "QA-D5"
            and "key_facts" not in result
            and "key_facts" in unit.get("gold", {})
        ):
            result["key_facts"] = unit["gold"]["key_facts"]
        specialty_fields = {
            "QA-D1": ("domain", "same_domain"),
            "QA-D2": ("domains", "joint_evidence"),
            "QA-D3": ("reasoning_chain", "missing_links"),
            "QA-D4": ("unanswerable_reason", "validity_scope"),
            "QA-D5": ("key_fact_anchors",),
            "QA-D6": ("embedding_version", "embedding_metrics", "completeness", "expiry"),
            "QA-D7": ("source_composition", "k_rule_ref"),
            "SEC-D1": ("acl_roles", "access_scope"),
            "SEC-D2": ("direct_injection", "indirect_injection"),
            "SEC-D3": ("rollback_evidence", "query_verification"),
            "SEC-D4": ("pair_controls", "language", "length", "style", "topic"),
            "SEC-D5": ("synthetic_pii", "synthetic_pii_provenance"),
        }
        metadata = unit.get("metadata", {})
        result["metadata"] = {
            key: metadata[key]
            for key in ("lang", "domain", *specialty_fields.get(unit.get("dataset", ""), ()))
            if key in metadata
        }
        for name in specialty_fields.get(unit.get("dataset", ""), ()):
            if name in metadata:
                result[name] = metadata[name]
    context_fields = (
        "doc_id",
        "text",
        "title",
        "license",
        "source_url",
        "version",
        "sha256",
        "page",
        "start",
        "end",
        "valid_from",
        "valid_until",
        "acl_context",
    )
    result["contexts"] = [
        {key: doc[key] for key in context_fields if key in doc} for doc in unit.get("contexts", [])
    ]
    return result


def family_keys(unit: dict[str, Any]) -> set[str]:
    return {
        unit["unit_id"],
        *unit.get("source_case_ids", []),
        *unit.get("metadata", {}).get("source_case_ids", []),
    }


async def submission(db: AsyncSession, assignment_id: str, phase: str) -> Submission | None:
    return (
        await db.scalars(
            select(Submission).where(
                Submission.assignment_id == assignment_id, Submission.phase == phase
            )
        )
    ).first()


async def own_assignment(
    db: AsyncSession, actor: User, assignment_id: str
) -> tuple[Assignment, AnnotationBatch, dict[str, Any]]:
    assignment = await db.get(Assignment, assignment_id)
    if not assignment or assignment.user_id != actor.id:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    batch = await get_batch(db, assignment.batch_id, lock=True)
    await db.refresh(assignment)
    if batch.state in {"SUPERSEDED", "CANCELLED"}:
        raise ApiError(409, "ROUND_SUPERSEDED", "原轮次已封存，请使用新轮次任务")
    if not assignment.active:
        raise ApiError(409, "ASSIGNMENT_REPLACED", "分配已取消；历史封存保留")
    material = (
        await db.get(UnitRevision, assignment.unit_revision_id)
        if assignment.unit_revision_id
        else None
    )
    if material is None:
        raise ApiError(409, "REVISION_MISSING", "冻结材料revision缺失，请联系运营")
    unit = dict(material.material)
    if current_phase(batch) == "REVIEW":
        gold = await db.get(GoldRevision, assignment.gold_revision_id)
        if gold is None:
            raise ApiError(409, "REVISION_MISSING", "冻结草案revision缺失")
        unit.update(gold.review_material)
        if gold.gold:
            unit["gold"] = dict(gold.gold)
    return assignment, batch, unit


def current_phase(batch: AnnotationBatch) -> str:
    return (
        "BLIND"
        if (batch.resume_state if batch.state == "PAUSED" else batch.state)
        in {"BLIND_OPEN", "BLIND_SEALED"}
        else "REVIEW"
    )


def validate_phase(batch: AnnotationBatch, phase: str) -> None:
    if batch.review_version != 'openkb.s4-review.v2':
        raise ApiError(409,'LEGACY_ROUND_UPGRADE_REQUIRED','旧v1轮只读；须保留原因升级完整v2新轮')
    allowed = batch.state == "BLIND_OPEN" if phase == "BLIND" else batch.state == "REVIEW_OPEN"
    if not allowed:
        raise ApiError(409, "PHASE_CONFLICT", "当前阶段不允许此操作")


def validate_review(unit: dict[str, Any], payload: dict[str, Any]) -> None:
    from ..domain.review import validate_review_v2

    if payload.get("review_version") == "openkb.s4-review.v2":
        validate_review_v2(unit, payload)
    kind = get_profile(unit["dataset"])["kind"]
    if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
        raise ApiError(422, "REASON_REQUIRED", "请填写审核理由")
    if kind in {"qa_points", "qa_unanswerable"}:
        expected = {point["point_key"] for point in points(unit)}
        labels = payload.get("point_labels", {})
        if (
            not isinstance(labels, dict)
            or set(labels) != expected
            or any(
                not isinstance(value, str) or value not in {"correct", "partial", "wrong"}
                for value in labels.values()
            )
        ):
            raise ApiError(
                422, "POINT_LABELS_INVALID", "必须逐一标注全部原始要点，标签为正确/部分正确/错误"
            )
        docs = set(unit.get("gold", {}).get("gold_doc_ids", []))
        evidence = payload.get("evidence_labels", {})
        if (
            not isinstance(evidence, dict)
            or set(evidence) != docs
            or any(type(value) is not int or value not in {0, 1, 2} for value in evidence.values())
        ):
            raise ApiError(422, "EVIDENCE_LABELS_INVALID", "必须逐文档填写2/1/0，保留原始对象")
    elif kind in {"chunk_quality", "security"}:
        if payload.get("point_labels") or payload.get("evidence_labels"):
            raise ApiError(422, "SPECIALIZED_PROFILE", "专项任务不能伪造QA要点或证据标签")
        from ..domain.review import validate_specialized

        validate_specialized(
            unit,
            payload.get("specialized_review"),
            payload.get("review_version") == "openkb.s4-review.v2",
        )
    if kind not in {"chunk_quality", "security"} and (
        not isinstance(payload.get("answerable"), str)
        or payload["answerable"] not in {"answerable", "no_answer", "expired", "out_of_scope"}
    ):
        raise ApiError(422, "ANSWERABILITY_INVALID", "可答性必须为四种规定枚举之一")


def validate_final_gold(unit: dict[str, Any], gold: dict[str, Any]) -> None:
    from copy import deepcopy

    from ..domain.contracts import validate_candidate
    from ..domain.errors import DomainError

    candidate = deepcopy(unit)
    if get_profile(unit["dataset"])["kind"].startswith("qa_"):
        candidate["gold"] = gold
    elif gold:
        raise ApiError(422, "FINAL_GOLD_INVALID", "专项不能添加QA金标")
    try:
        validate_candidate(candidate)
    except DomainError as exc:
        raise ApiError(422, exc.code, exc.message) from exc


async def prohibit_participant_import(db: AsyncSession, actor: User, import_id: str) -> None:
    historical=await db.scalar(select(Assignment.id).join(AnnotationBatch,Assignment.batch_id==AnnotationBatch.id).where(AnnotationBatch.import_id==import_id,Assignment.user_id==actor.id).limit(1))
    if historical:
        raise ApiError(403,'PARTICIPANT_RESTRICTED','本来源历史参标人员不能读取受限完整资料')
    batches = (
        await db.scalars(select(AnnotationBatch).where(AnnotationBatch.import_id == import_id))
    ).all()
    for batch in batches:
        require_independent(actor, batch)


async def mark_batch_exposure(
    db: AsyncSession, actor: User, batch: AnnotationBatch, reason: str
) -> None:
    """Sensitive business reads disqualify future first-blind work on this source family."""
    imported = await source(db, batch.import_id)
    for unit_id in batch.selected_ids:
        unit = source_unit(imported, unit_id)
        db.add(
            Exposure(
                user_id=actor.id,
                unit_id=unit_id,
                family_keys=sorted(family_keys(unit)),
                batch_id=batch.id,
                reason=reason,
            )
        )


async def mark_import_exposure(db: AsyncSession, actor: User, import_id: str, reason: str) -> None:
    imported = await source(db, import_id)
    for unit in imported.payload["units"]:
        db.add(
            Exposure(
                user_id=actor.id,
                unit_id=unit["unit_id"],
                family_keys=sorted(family_keys(unit)),
                batch_id=None,
                reason=reason,
            )
        )
