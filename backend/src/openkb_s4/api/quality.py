"""Original agreement statistics and accountable human content decisions."""

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from ..domain.contracts import canonical_sha256
from ..models import (
    Agreement,
    AnnotationBatch,
    Arbitration,
    Assignment,
    FinalDecision,
    ValidationRevision,
    now,
)
from ..schemas import ArbitrationInput, FinalizeInput, ReasonInput
from ..security import Actor, ApiError, Db, require_role
from ..services.common import (
    audit,
    business_batch,
    get_batch,
    mark_batch_exposure,
    source,
    source_unit,
    validate_final_gold,
)
from ..services.jobs import enqueue
from ..services.revisions import change_kind, final_candidate

router = APIRouter()


def agreement_view(item: Agreement) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        **item.result,
        "input_hash": item.input_hash,
        "created_at": item.created_at.isoformat(),
    }


def arbitration_view(item: Arbitration) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "unit_id": item.unit_id,
        "arbitrator_id": item.arbitrator_id,
        "final_gold": item.final_gold,
        "reason": item.reason,
        "confirmed": item.confirmed,
        "confirmed_by": item.confirmed_by,
        "confirmation_reason": item.confirmation_reason,
        "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
    }


@router.post("/annotation-batches/{batch_id}/agreement", status_code=202)
async def calculate(batch_id: str, request: Request, actor: Actor, db: Db) -> dict[str, str]:
    require_role(actor, "lead")
    batch = await business_batch(db, actor, batch_id, lock=True)
    if batch.state not in {"PAIR_COMPLETE", "S4_READY"}:
        raise ApiError(409, "PAIR_INCOMPLETE", "双方本轮全部复核封存后才能计算正式批次统计")
    job = await enqueue(db, "AGREEMENT", f"agreement:{batch.id}", actor.id, {"batch_id": batch.id})
    audit(db, request, actor.id, "AGREEMENT_REQUESTED", batch.id)
    return {"job_id": job.id}


@router.get("/agreements")
async def agreements(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=500)
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor", "arbitrator")
    query = (
        select(Agreement)
        .join(AnnotationBatch, Agreement.batch_id == AnnotationBatch.id)
        .where(
            AnnotationBatch.annotator_a != actor.id,
            AnnotationBatch.annotator_b != actor.id,
            AnnotationBatch.id.notin_(
                select(Assignment.batch_id).where(Assignment.user_id == actor.id)
            ),
        )
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(
            query.order_by(Agreement.created_at.desc(), Agreement.id).offset(offset).limit(limit)
        )
    ).all()
    for row in rows:
        await mark_batch_exposure(db, actor, await get_batch(db, row.batch_id), "AGREEMENT_READ")
    return {
        "items": [agreement_view(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/arbitrations")
async def arbitrations(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=500)
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor", "arbitrator")
    query = (
        select(Arbitration)
        .join(AnnotationBatch, Arbitration.batch_id == AnnotationBatch.id)
        .where(
            AnnotationBatch.annotator_a != actor.id,
            AnnotationBatch.annotator_b != actor.id,
            AnnotationBatch.id.notin_(
                select(Assignment.batch_id).where(Assignment.user_id == actor.id)
            ),
        )
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(
            query.order_by(Arbitration.created_at.desc(), Arbitration.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    for row in rows:
        await mark_batch_exposure(db, actor, await get_batch(db, row.batch_id), "ARBITRATION_READ")
    return {
        "items": [arbitration_view(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/arbitrations", status_code=201)
async def arbitrate(
    body: ArbitrationInput, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "arbitrator")
    batch = await business_batch(db, actor, body.batch_id, lock=True)
    agreement = await db.scalar(select(Agreement).where(Agreement.batch_id == batch.id))
    if (
        not agreement
        or agreement.result["verdict"] != "ARBITRATE"
        or batch.state != "PAIR_COMPLETE"
    ):
        raise ApiError(409, "ARBITRATION_NOT_OPEN", "本批未进入可仲裁状态")
    if body.unit_id not in agreement.result.get("disagreement_unit_ids", []):
        raise ApiError(422, "NOT_DISAGREEMENT", "该单元不在原始分歧范围")
    imported = await source(db, batch.import_id)
    validate_final_gold(source_unit(imported, body.unit_id), body.final_gold)
    item = Arbitration(
        batch_id=batch.id,
        unit_id=body.unit_id,
        arbitrator_id=actor.id,
        final_gold=body.final_gold,
        reason=body.reason,
    )
    db.add(item)
    await db.flush()
    audit(
        db,
        request,
        actor.id,
        "ARBITRATION_RECORDED",
        item.id,
        {"batch_id": batch.id, "unit_id": body.unit_id},
    )
    return arbitration_view(item)


@router.post("/arbitrations/{arbitration_id}/confirm")
async def confirm(
    arbitration_id: str, body: ReasonInput, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    item = await db.scalar(
        select(Arbitration).where(Arbitration.id == arbitration_id).with_for_update()
    )
    if not item:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    batch = await business_batch(db, actor, item.batch_id, lock=True)
    if item.arbitrator_id == actor.id:
        raise ApiError(403, "INDEPENDENT_CONFIRMATION_REQUIRED", "裁决人与负责人复核须为不同人员")
    if batch.state != "PAIR_COMPLETE":
        raise ApiError(409, "ROUND_CLOSED", "原轮已封存")
    if not item.confirmed:
        item.confirmed, item.confirmed_by, item.confirmation_reason = True, actor.id, body.reason
        item.confirmed_at = now()
        audit(db, request, actor.id, "ARBITRATION_CONFIRMED", item.id)
    return arbitration_view(item)


@router.post("/annotation-batches/{batch_id}/finalize")
async def finalize(
    batch_id: str, body: FinalizeInput, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await business_batch(db, actor, batch_id, lock=True)
    agreement = await db.scalar(select(Agreement).where(Agreement.batch_id == batch.id))
    if (
        batch.state != "PAIR_COMPLETE"
        or not agreement
        or agreement.result["verdict"] not in {"ACCEPT", "ARBITRATE"}
    ):
        raise ApiError(409, "QUALITY_GATE_CLOSED", "批次尚未通过有效质量门或已封存")
    if batch.blocked_reasons:
        raise ApiError(409, "BATCH_BLOCKED", "批次存在未处理阻塞")
    expected = set(batch.selected_ids)
    if {decision.unit_id for decision in body.decisions} != expected or len(body.decisions) != len(
        expected
    ):
        raise ApiError(422, "FINAL_SCOPE_MISMATCH", "须逐一确认全部抽检单元，不能漏题或重复")
    arbitrations = (
        await db.scalars(select(Arbitration).where(Arbitration.batch_id == batch.id))
    ).all()
    by_unit = {item.unit_id: item for item in arbitrations}
    if agreement.result["verdict"] == "ARBITRATE":
        for unit_id in agreement.result.get("disagreement_unit_ids", []):
            if unit_id not in by_unit or not by_unit[unit_id].confirmed:
                raise ApiError(
                    409, "ARBITRATION_INCOMPLETE", "所有原始分歧须第三人裁决及负责人复核闭环"
                )
    imported = await source(db, batch.import_id)
    for decision in body.decisions:
        unit = source_unit(imported, decision.unit_id)
        validate_final_gold(unit, decision.final_gold)
        if batch.review_version == "openkb.s4-review.v2":
            digest = canonical_sha256(final_candidate(unit, decision.final_gold))
            kind = change_kind(unit, decision.final_gold)
            if kind != "UNCHANGED":
                evidence = await db.scalar(
                    select(ValidationRevision)
                    .where(
                        ValidationRevision.batch_id == batch.id,
                        ValidationRevision.unit_id == decision.unit_id,
                        ValidationRevision.content_hash == digest,
                        ValidationRevision.profile_hash == batch.profile_hash,
                    )
                    .order_by(ValidationRevision.created_at.desc())
                )
                arbitration_author = by_unit.get(decision.unit_id)
                if (
                    evidence
                    and arbitration_author
                    and evidence.verifier_id == arbitration_author.arbitrator_id
                ):
                    raise ApiError(
                        409, "INDEPENDENT_VERIFIER_REQUIRED", "仲裁内容作者不能复验本人修订"
                    )
                if (
                    not evidence
                    or evidence.status != "PASS"
                    or evidence.verifier_id
                    in {actor.id, batch.annotator_a, batch.annotator_b, None}
                ):
                    raise ApiError(
                        409,
                        "VALIDATION_REQUIRED",
                        "实质修订或定位修正须独立复验闭环，摘要与profile须一致",
                    )
            else:
                db.add(
                    ValidationRevision(
                        batch_id=batch.id,
                        unit_id=decision.unit_id,
                        content_hash=digest,
                        profile_hash=batch.profile_hash or "",
                        final_gold=decision.final_gold,
                        validation_revision="unchanged:" + digest,
                        status="NOT_REQUIRED",
                        change_kind="UNCHANGED",
                        editor_id=actor.id,
                        evidence={"basis": "UNCHANGED_FROZEN_CONTENT"},
                        evidence_hash=canonical_sha256({"basis": "UNCHANGED_FROZEN_CONTENT"}),
                        reason="定稿内容与冻结来源一致",
                    )
                )
        if decision.unit_id in by_unit and canonical_sha256(
            decision.final_gold
        ) != canonical_sha256(by_unit[decision.unit_id].final_gold):
            raise ApiError(409, "ARBITRATION_CONTENT_MISMATCH", "最终内容须与已确认裁决一致")
        db.add(
            FinalDecision(
                batch_id=batch.id,
                unit_id=decision.unit_id,
                final_gold=decision.final_gold,
                reason=decision.reason,
                actor_id=actor.id,
            )
        )
    batch.state = "S4_READY"
    audit(
        db,
        request,
        actor.id,
        "CONTENT_FINALIZED",
        batch.id,
        {"count": len(body.decisions), "verdict": agreement.result["verdict"]},
    )
    return {"id": batch.id, "state": batch.state, "verdict": agreement.result["verdict"]}
