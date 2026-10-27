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
    SourceImport,
    Submission,
    User,
)
from ..security import ApiError, require_independent, require_role


def audit(db: AsyncSession, request: Request | None, actor_id: str | None, action: str,
          object_id: str | None, details: dict[str, Any] | None = None) -> None:
    db.add(AuditEvent(actor_id=actor_id, action=action, object_id=object_id,
                      request_id=getattr(request.state, "request_id", "worker") if request else "worker",
                      details=details or {}))


async def get_batch(db: AsyncSession, batch_id: str, lock: bool = False) -> AnnotationBatch:
    query = select(AnnotationBatch).where(AnnotationBatch.id == batch_id)
    if lock:
        query = query.with_for_update()
    batch = await db.scalar(query)
    if not batch:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    return batch


async def business_batch(db: AsyncSession, user: User, batch_id: str, lock: bool = False) -> AnnotationBatch:
    require_role(user, "lead", "auditor", "arbitrator")
    batch = await get_batch(db, batch_id, lock)
    require_independent(user, batch)
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
    return [{"point_key": f"P{i + 1:03d}", "text": str(value)}
            for i, value in enumerate(unit.get("gold", {}).get("answer_points", []))]


def safe_material(unit: dict[str, Any], phase: str = "BLIND") -> dict[str, Any]:
    visible = ("question", "payload", "acl_context", "time_context", "scope_context", "chunk", "access_context", "inject_plan")
    result = {key: unit[key] for key in visible if key in unit}
    if phase == "REVIEW" and "quality_metrics" in unit:
        result["quality_metrics"] = unit["quality_metrics"]
    context_fields = ("doc_id", "text", "title", "license", "source_url", "version", "sha256", "page", "start", "end", "valid_from", "valid_until", "acl_context")
    result["contexts"] = [{key: doc[key] for key in context_fields if key in doc}
                          for doc in unit.get("contexts", [])]
    return result


def family_keys(unit: dict[str, Any]) -> set[str]:
    return {unit["unit_id"], *unit.get("source_case_ids", []),
            *unit.get("metadata", {}).get("source_case_ids", [])}


async def submission(db: AsyncSession, assignment_id: str, phase: str) -> Submission | None:
    return (await db.scalars(select(Submission).where(Submission.assignment_id == assignment_id, Submission.phase == phase))).first()


async def own_assignment(db: AsyncSession, actor: User, assignment_id: str) -> tuple[Assignment, AnnotationBatch, dict[str, Any]]:
    assignment = await db.get(Assignment, assignment_id)
    if not assignment or assignment.user_id != actor.id:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    batch = await get_batch(db, assignment.batch_id, lock=True)
    if batch.state in {"SUPERSEDED", "CANCELLED"}:
        raise ApiError(409, "ROUND_SUPERSEDED", "原轮次已封存，请使用新轮次任务")
    imported = await source(db, batch.import_id)
    return assignment, batch, source_unit(imported, assignment.unit_id)


def current_phase(batch: AnnotationBatch) -> str:
    return "BLIND" if batch.state in {"BLIND_OPEN", "BLIND_SEALED"} else "REVIEW"


def validate_phase(batch: AnnotationBatch, phase: str) -> None:
    allowed = batch.state == "BLIND_OPEN" if phase == "BLIND" else batch.state == "REVIEW_OPEN"
    if not allowed:
        raise ApiError(409, "PHASE_CONFLICT", "当前阶段不允许此操作")


def validate_review(unit: dict[str, Any], payload: dict[str, Any]) -> None:
    kind = get_profile(unit["dataset"])["kind"]
    if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
        raise ApiError(422, "REASON_REQUIRED", "请填写审核理由")
    if kind == "qa_points":
        expected = {point["point_key"] for point in points(unit)}
        labels = payload.get("point_labels", {})
        if not isinstance(labels, dict) or set(labels) != expected or any(not isinstance(value, str) or value not in {"correct", "partial", "wrong"} for value in labels.values()):
            raise ApiError(422, "POINT_LABELS_INVALID", "必须逐一标注全部原始要点，标签为正确/部分正确/错误")
        docs = set(unit.get("gold", {}).get("gold_doc_ids", []))
        evidence = payload.get("evidence_labels", {})
        if not isinstance(evidence, dict) or set(evidence) != docs or any(type(value) is not int or value not in {0, 1, 2} for value in evidence.values()):
            raise ApiError(422, "EVIDENCE_LABELS_INVALID", "必须逐文档填写2/1/0，保留原始对象")
    elif kind in {"chunk_quality", "security"}:
        if payload.get("point_labels") or payload.get("evidence_labels"):
            raise ApiError(422, "SPECIALIZED_PROFILE", "专项任务不能伪造QA要点或证据标签")
        if not payload.get("specialized_review"):
            raise ApiError(422, "SPECIALIZED_REVIEW_REQUIRED", "请填写专项审核记录")
    if kind not in {"chunk_quality", "security"} and (not isinstance(payload.get("answerable"), str) or payload["answerable"] not in {"answerable", "no_answer", "expired", "out_of_scope"}):
        raise ApiError(422, "ANSWERABILITY_INVALID", "可答性必须为四种规定枚举之一")


def validate_final_gold(unit: dict[str, Any], gold: dict[str, Any]) -> None:
    kind = get_profile(unit["dataset"])["kind"]
    if kind.startswith("qa_"):
        if not isinstance(gold.get("answerable"), str) or gold["answerable"] not in {"answerable", "no_answer", "expired", "out_of_scope"}:
            raise ApiError(422, "FINAL_GOLD_INVALID", "定稿须保留合法可答性")
        if not isinstance(gold.get("answer_points"), list) or not isinstance(gold.get("gold_doc_ids"), list):
            raise ApiError(422, "FINAL_GOLD_INVALID", "定稿须包含答案要点和证据文档列表")
        if any(not isinstance(point, str) or not point.strip() for point in gold["answer_points"]):
            raise ApiError(422, "FINAL_GOLD_INVALID", "答案要点须为非空文本")
        docs = gold["gold_doc_ids"]
        source_docs = {doc["doc_id"] for doc in unit.get("contexts", [])}
        if any(not isinstance(doc, str) or doc not in source_docs for doc in docs) or len(docs) != len(set(docs)):
            raise ApiError(422, "FINAL_GOLD_INVALID", "证据须引用当前冻结原文文档，不能虚构或重复")
        if kind == "qa_unanswerable" and gold["answer_points"]:
            raise ApiError(422, "FINAL_GOLD_INVALID", "D4不能添加虚构答案要点")


async def prohibit_participant_import(db: AsyncSession, actor: User, import_id: str) -> None:
    batches = (await db.scalars(select(AnnotationBatch).where(AnnotationBatch.import_id == import_id))).all()
    for batch in batches:
        require_independent(actor, batch)


async def mark_batch_exposure(db: AsyncSession, actor: User, batch: AnnotationBatch, reason: str) -> None:
    """Sensitive business reads disqualify future first-blind work on this source family."""
    imported = await source(db, batch.import_id)
    for unit_id in batch.selected_ids:
        unit = source_unit(imported, unit_id)
        db.add(Exposure(user_id=actor.id, unit_id=unit_id, family_keys=sorted(family_keys(unit)),
                        batch_id=batch.id, reason=reason))


async def mark_import_exposure(db: AsyncSession, actor: User, import_id: str, reason: str) -> None:
    imported = await source(db, import_id)
    for unit in imported.payload["units"]:
        db.add(Exposure(user_id=actor.id, unit_id=unit["unit_id"], family_keys=sorted(family_keys(unit)),
                        batch_id=None, reason=reason))
