"""Imports, fixed-pair batches and two-stage immutable submissions."""

from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from ..db import lock_scope
from ..domain.contracts import canonical_sha256
from ..domain.profiles import get_profile, list_profiles
from ..domain.sampling import sample_units
from ..models import (
    AnnotationBatch,
    Assignment,
    CalibrationRecord,
    ChangeEvent,
    Exposure,
    Job,
    LateSubmission,
    ProfileRevision,
    Qualification,
    SourceImport,
    Submission,
    User,
    WorkingDraft,
    now,
)
from ..schemas import BatchCreate, DraftInput, ImportUpload, RoundInput, SubmitInput
from ..security import Actor, ApiError, Db, require_role
from ..services.common import (
    audit,
    business_batch,
    current_phase,
    family_keys,
    get_batch,
    mark_batch_exposure,
    own_assignment,
    points,
    prohibit_participant_import,
    safe_material,
    source,
    source_unit,
    submission,
    validate_phase,
    validate_review,
)
from ..services.jobs import enqueue

router = APIRouter()


def import_view(item: SourceImport) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "source_revision": item.source_revision,
        "mode": item.mode,
        "status": item.status,
        "unit_count": len(item.payload["units"]),
        "blocked_reasons": item.blocked_reasons,
        "created_at": item.created_at.isoformat(),
    }


@router.get("/profiles")
async def profiles(actor: Actor) -> list[dict[str, Any]]:
    return list_profiles()


@router.post("/imports", status_code=202)
async def import_source(
    body: dict[str, Any], request: Request, actor: Actor, db: Db
) -> dict[str, str]:
    require_role(actor, "lead")
    import json

    if (
        len(json.dumps(body, ensure_ascii=False).encode())
        > request.app.state.settings.max_import_bytes
    ):
        raise ApiError(413, "IMPORT_TOO_LARGE", "导入材料超过允许大小")
    if not isinstance(body.get("units"), list):
        raise ApiError(422, "INPUT_INVALID", "units须为单元数组")
    key = "import:" + canonical_sha256(body)
    # Uploaders have already seen the raw draft, including unsampled/related units.
    # Register this even when the durable import job was deduplicated for another actor.
    for unit in body.get("units", []):
        if not isinstance(unit, dict) or not isinstance(unit.get("unit_id"), str):
            continue
        keys = {unit["unit_id"]}
        metadata = unit.get("metadata", {})
        for candidates in (
            unit.get("source_case_ids", []),
            metadata.get("source_case_ids", []) if isinstance(metadata, dict) else [],
        ):
            if isinstance(candidates, list):
                keys.update(value for value in candidates if isinstance(value, str))
        db.add(
            Exposure(
                user_id=actor.id,
                unit_id=unit["unit_id"],
                family_keys=sorted(keys),
                batch_id=None,
                reason="IMPORT_UPLOADED",
            )
        )
    job = await enqueue(db, "IMPORT", key, actor.id, body)
    audit(
        db, request, actor.id, "IMPORT_REQUESTED", job.id, {"payload_hash": canonical_sha256(body)}
    )
    return {"job_id": job.id}


@router.get("/imports")
async def imports(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    participating = select(AnnotationBatch.import_id).where(
        (AnnotationBatch.annotator_a == actor.id)
        | (AnnotationBatch.annotator_b == actor.id)
        | AnnotationBatch.id.in_(select(Assignment.batch_id).where(Assignment.user_id == actor.id))
    )
    visible = SourceImport.id.notin_(participating)
    rows = (
        await db.scalars(
            select(SourceImport)
            .where(visible)
            .order_by(SourceImport.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {
        "items": [import_view(row) for row in rows],
        "total": await db.scalar(select(func.count()).select_from(SourceImport).where(visible)),
    }


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, actor: Actor, db: Db) -> dict[str, Any]:
    job = await db.get(Job, job_id)
    if not job or (
        job.creator_id != actor.id and not set(actor.roles).intersection({"lead", "auditor"})
    ):
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    if job.payload.get("batch_id") and job.kind == "AGREEMENT":
        await business_batch(db, actor, job.payload["batch_id"])
    import_id = job.payload.get("import_id") or (job.result or {}).get("import_id")
    if import_id:
        await prohibit_participant_import(db, actor, import_id)
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "attempts": job.attempts,
        "result": job.result,
        "error_code": job.error_code,
        "error_message": job.error_message,
    }


async def batch_view(db: Db, batch: AnnotationBatch, details: bool = False) -> dict[str, Any]:
    assignments = (
        await db.scalars(
            select(Assignment).where(Assignment.batch_id == batch.id, Assignment.active.is_(True))
        )
    ).all()
    assignment_ids = [a.id for a in assignments]
    submissions = (
        await db.scalars(select(Submission).where(Submission.assignment_id.in_(assignment_ids)))
    ).all()
    result: dict[str, Any] = {
        "id": batch.id,
        "import_id": batch.import_id,
        "dataset": batch.dataset,
        "state": batch.state,
        "round": batch.round,
        "seed": batch.seed,
        "relabel_mode": "FULL_POPULATION_RESAMPLE" if batch.parent_id else None,
        "parent_id": batch.parent_id,
        "reason": batch.reason,
        "annotator_a": batch.annotator_a,
        "annotator_b": batch.annotator_b,
        "selected_ids": batch.selected_ids,
        "sample_count": len(batch.selected_ids),
        "blocked_reasons": batch.blocked_reasons,
        "profile_version": batch.profile_version,
        "review_version": batch.review_version,
        "legacy": batch.review_version != "openkb.s4-review.v2",
        "profile_revision_id": batch.profile_revision_id,
        "profile_snapshot": batch.profile_snapshot,
        "profile_hash": batch.profile_hash,
        "manual_version": batch.manual_version,
        "version": batch.version,
        "due_at": batch.due_at.isoformat() if batch.due_at else None,
        "reminder_interval_minutes": batch.reminder_interval_minutes,
        "calibration_id": batch.calibration_id,
        "blind_submitted": sum(s.phase == "BLIND" for s in submissions),
        "review_submitted": sum(s.phase == "REVIEW" for s in submissions),
        "finalized": batch.state == "S4_READY",
    }
    if details:
        imported = await source(db, batch.import_id)
        result["sample_ledger"] = batch.sample_ledger
        result["units"] = [source_unit(imported, unit_id) for unit_id in batch.selected_ids]
        result["assignments"] = [
            {"id": a.id, "unit_id": a.unit_id, "user_id": a.user_id, "seat": a.seat}
            for a in assignments
        ]
        result["submissions"] = [
            {
                "id": s.id,
                "assignment_id": s.assignment_id,
                "phase": s.phase,
                "payload": s.payload,
                "payload_hash": s.payload_hash,
            }
            for s in submissions
        ]
    return result


async def check_pair(db: Db, a_id: str, b_id: str, units: list[dict[str, Any]]) -> None:
    a, b = await db.get(User, a_id), await db.get(User, b_id)
    if (
        not a
        or not b
        or not a.active
        or not b.active
        or "annotator" not in a.roles
        or "annotator" not in b.roles
    ):
        raise ApiError(422, "ANNOTATOR_INVALID", "两位人员均须为有效标注员")
    if a.id == b.id or a.person_id == b.person_id:
        raise ApiError(422, "DIFFERENT_PEOPLE_REQUIRED", "A/B必须为两位不同实际人员")
    keys = set().union(*(family_keys(unit) for unit in units))
    exposures = (await db.scalars(select(Exposure).where(Exposure.user_id.in_([a_id, b_id])))).all()
    if any(keys.intersection(exposure.family_keys) for exposure in exposures):
        raise ApiError(409, "PREVIOUS_EXPOSURE", "人员已见本批或同源草案，请安排未暴露人员")


async def add_batch(
    db: Db,
    imported: SourceImport,
    body: BatchCreate,
    round_no: int = 1,
    parent: AnnotationBatch | None = None,
    reason: str | None = None,
) -> AnnotationBatch:
    from ..services.revisions import ensure_revisions

    get_profile(body.dataset)
    profile_revision = (
        await db.get(ProfileRevision, body.profile_revision_id)
        if body.profile_revision_id
        else await db.scalar(
            select(ProfileRevision)
            .where(ProfileRevision.dataset == body.dataset, ProfileRevision.state == "APPROVED")
            .order_by(ProfileRevision.created_at.desc())
        )
    )
    if (
        not profile_revision
        or profile_revision.dataset != body.dataset
        or profile_revision.state != "APPROVED"
    ):
        raise ApiError(409, "PROFILE_NOT_APPROVED", "批次须绑定已批准的完整profile revision")
    profile = profile_revision.snapshot
    if canonical_sha256(profile) != profile_revision.canonical_hash:
        raise ApiError(409, "PROFILE_DIGEST_CONFLICT", "冻结profile摘要不一致")
    revisions = await ensure_revisions(db, imported)
    units = [u for u in imported.payload["units"] if u["dataset"] == body.dataset]
    if not units:
        raise ApiError(422, "DATASET_EMPTY", "导入中不存在该数据集")
    if imported.mode == "formal" and not profile["formal_enabled"]:
        raise ApiError(409, "PROFILE_NOT_CONFIRMED", "专项统计量表尚未确认，不可正式开标")
    ledger = sample_units(units, body.seed)
    chosen = [u for u in units if u["unit_id"] in ledger["selected_ids"]]
    await check_pair(db, body.annotator_a, body.annotator_b, chosen)
    for user_id in (body.annotator_a, body.annotator_b):
        qualification = await db.scalar(
            select(Qualification)
            .where(Qualification.user_id == user_id, Qualification.dataset == body.dataset)
            .order_by(Qualification.created_at.desc())
        )
        if qualification and (not qualification.available or qualification.valid_until <= now()):
            raise ApiError(409, "ANNOTATOR_UNAVAILABLE", "标注员资格已过期或当前不可用")
        if not qualification and imported.mode == "formal" and body.dataset.startswith("SEC"):
            raise ApiError(409, "QUALIFICATION_REQUIRED", "专项排班需要独立批准的有效资格依据")
    batch = AnnotationBatch(
        import_id=imported.id,
        dataset=body.dataset,
        annotator_a=body.annotator_a,
        annotator_b=body.annotator_b,
        profile_version=profile_revision.version,
        review_version="openkb.s4-review.v2",
        profile_revision_id=profile_revision.id,
        profile_snapshot=profile,
        profile_hash=profile_revision.canonical_hash,
        manual_version=profile_revision.manual_version,
        due_at=body.due_at,
        reminder_interval_minutes=body.reminder_interval_minutes,
        selected_ids=ledger["selected_ids"],
        sample_ledger=ledger,
        blocked_reasons=ledger["blocked_reasons"],
        seed=body.seed,
        round=round_no,
        parent_id=parent.id if parent else None,
        reason=reason,
    )
    db.add(batch)
    await db.flush()
    for unit in chosen:
        for seat, user_id in (("A", body.annotator_a), ("B", body.annotator_b)):
            db.add(
                Assignment(
                    batch_id=batch.id,
                    unit_id=unit["unit_id"],
                    user_id=user_id,
                    seat=seat,
                    content_revision=canonical_sha256(unit),
                    unit_revision_id=revisions[unit["unit_id"]][0].id,
                    gold_revision_id=revisions[unit["unit_id"]][1].id,
                )
            )
    await db.flush()
    return batch


@router.post("/annotation-batches", status_code=201)
async def create_batch(body: BatchCreate, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    imported = await source(db, body.import_id)
    # Source imports are immutable and the application has no UPDATE privilege.
    await lock_scope(db, "annotation-scope:" + imported.id)
    existing = await db.scalar(
        select(AnnotationBatch).where(
            AnnotationBatch.import_id == imported.id,
            AnnotationBatch.dataset == body.dataset,
            AnnotationBatch.state != "SUPERSEDED",
        )
    )
    if existing:
        raise ApiError(409, "SCOPE_ALREADY_PLANNED", "该数据集已有冻结统计范围，请通过新轮次处理")
    batch = await add_batch(db, imported, body)
    audit(
        db,
        request,
        actor.id,
        "BATCH_CREATED",
        batch.id,
        {"sample_count": len(batch.selected_ids), "seed": body.seed},
    )
    return await batch_view(db, batch)


@router.get("/annotation-batches")
async def batches(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=500)
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor", "arbitrator")
    query = select(AnnotationBatch).where(
        AnnotationBatch.annotator_a != actor.id,
        AnnotationBatch.annotator_b != actor.id,
        AnnotationBatch.id.notin_(
            select(Assignment.batch_id).where(Assignment.user_id == actor.id)
        ),
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(
            query.order_by(AnnotationBatch.created_at.desc(), AnnotationBatch.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {
        "items": [await batch_view(db, row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/annotation-batches/{batch_id}")
async def batch_detail(batch_id: str, actor: Actor, db: Db) -> dict[str, Any]:
    batch = await business_batch(db, actor, batch_id)
    if "arbitrator" in actor.roles and "lead" not in actor.roles and "auditor" not in actor.roles:
        from ..models import Agreement

        agreement = await db.scalar(select(Agreement).where(Agreement.batch_id == batch.id))
        if not agreement or agreement.result["verdict"] != "ARBITRATE":
            raise ApiError(403, "ARBITRATION_NOT_OPEN", "本批尚未进入仲裁")
    await mark_batch_exposure(db, actor, batch, "BUSINESS_DETAIL_READ")
    return await batch_view(db, batch, details=True)


@router.post("/annotation-batches/{batch_id}/release-review")
async def release(batch_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await business_batch(db, actor, batch_id, lock=True)
    if batch.state in {"REVIEW_OPEN", "PAIR_COMPLETE", "S4_READY"}:
        return await batch_view(db, batch)
    if batch.state not in {"BLIND_OPEN", "BLIND_SEALED"} or batch.blocked_reasons:
        raise ApiError(409, "BATCH_BLOCKED", "批次存在阻塞或当前不可解锁")
    assignments = (
        await db.scalars(
            select(Assignment).where(Assignment.batch_id == batch.id, Assignment.active.is_(True))
        )
    ).all()
    for assignment in assignments:
        if not await submission(db, assignment.id, "BLIND"):
            raise ApiError(409, "BLIND_INCOMPLETE", "本批全部A/B独立作答封存后才能统一解锁")
    imported = await source(db, batch.import_id)
    units = [source_unit(imported, unit_id) for unit_id in batch.selected_ids]
    await check_pair(db, batch.annotator_a, batch.annotator_b, units)
    batch.state = "REVIEW_OPEN"
    for assignment in assignments:
        unit = source_unit(imported, assignment.unit_id)
        db.add(
            Exposure(
                user_id=assignment.user_id,
                unit_id=assignment.unit_id,
                family_keys=sorted(family_keys(unit)),
                batch_id=batch.id,
                reason="REVIEW_RELEASED",
            )
        )
    audit(db, request, actor.id, "REVIEW_RELEASED", batch.id)
    return await batch_view(db, batch)


@router.get("/me/tasks")
async def my_tasks(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000)
) -> dict[str, Any]:
    require_role(actor, "annotator")
    query = (
        select(Assignment, AnnotationBatch)
        .join(AnnotationBatch, Assignment.batch_id == AnnotationBatch.id)
        .where(
            Assignment.user_id == actor.id,
            Assignment.active.is_(True),
            AnnotationBatch.state.notin_(["SUPERSEDED", "CANCELLED"]),
        )
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(Assignment.created_at, Assignment.id).offset(offset).limit(limit)
        )
    ).all()
    items = []
    for assignment, batch in rows:
        phase = current_phase(batch)
        sealed = await submission(db, assignment.id, phase)
        items.append(
            {
                "id": assignment.id,
                "batch_id": batch.id,
                "unit_id": assignment.unit_id,
                "dataset": batch.dataset,
                "phase": phase,
                "status": "SEALED" if sealed else "PENDING",
                "content_revision": assignment.content_revision,
                "profile_version": batch.profile_version,
                "profile_hash": batch.profile_hash,
                "review_version": batch.review_version,
                "batch_version": batch.version,
                "paused": batch.state == "PAUSED",
            }
        )
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/assignments/{assignment_id}")
async def assignment_detail(assignment_id: str, actor: Actor, db: Db) -> dict[str, Any]:
    assignment, batch, unit = await own_assignment(db, actor, assignment_id)
    phase = current_phase(batch)
    saved = await submission(db, assignment.id, phase)
    draft = await db.scalar(
        select(WorkingDraft).where(
            WorkingDraft.assignment_id == assignment.id, WorkingDraft.phase == phase
        )
    )
    result: dict[str, Any] = {
        "id": assignment.id,
        "batch_id": batch.id,
        "unit_id": assignment.unit_id,
        "dataset": batch.dataset,
        "phase": phase,
        "status": "SEALED" if saved else "PENDING",
        "content_revision": assignment.content_revision,
        "profile_version": batch.profile_version,
        "profile_hash": batch.profile_hash,
        "review_version": batch.review_version,
        "batch_version": batch.version,
        "specialized_fields": (batch.profile_snapshot or {}).get("specialized_fields", []),
        "manual_version": batch.manual_version,
        "instructions": (batch.profile_snapshot or {}).get(
            "instructions", "旧版演示记录，仅供只读核对"
        ),
        "label_dictionaries": (batch.profile_snapshot or {}).get("label_dictionaries", {}),
        "paused": batch.state == "PAUSED",
        "legacy": batch.review_version != "openkb.s4-review.v2",
        "material": safe_material(unit, phase),
        "draft": {"version": draft.version, "payload": draft.payload} if draft else None,
        "own_submission": saved.payload if saved else None,
    }
    if phase == "REVIEW" and batch.dataset == "QA-D7":
        from ..services.revisions import resolve_source_cases

        result["material"].update(await resolve_source_cases(db, batch.import_id, unit))
    if phase == "REVIEW":
        blind = await submission(db, assignment.id, "BLIND")
        result.update(
            {
                "gold": unit.get("gold", {}),
                "points": points(unit),
                "own_blind": blind.payload if blind else None,
            }
        )
        if "expected_behavior" in unit:
            result["expected_behavior"] = unit["expected_behavior"]
    return result


@router.patch("/assignments/{assignment_id}/draft")
async def save_draft(assignment_id: str, body: DraftInput, actor: Actor, db: Db) -> dict[str, Any]:
    assignment, batch, _ = await own_assignment(db, actor, assignment_id)
    validate_phase(batch, body.phase)
    if await submission(db, assignment.id, body.phase):
        raise ApiError(409, "SUBMISSION_SEALED", "正式提交已封存，不能覆盖")
    draft = await db.scalar(
        select(WorkingDraft)
        .where(WorkingDraft.assignment_id == assignment.id, WorkingDraft.phase == body.phase)
        .with_for_update()
    )
    if (draft.version if draft else 0) != body.version:
        raise ApiError(409, "DRAFT_VERSION_CONFLICT", "其他窗口已更新草稿，请刷新后再试")
    if draft:
        draft.payload, draft.version = body.payload, draft.version + 1
    else:
        draft = WorkingDraft(
            assignment_id=assignment.id, phase=body.phase, payload=body.payload, version=1
        )
        db.add(draft)
    return {"version": draft.version, "payload": draft.payload}


@router.post("/assignments/{assignment_id}/submit")
async def submit(
    assignment_id: str,
    body: SubmitInput,
    request: Request,
    actor: Actor,
    db: Db,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=160),
) -> Any:
    old = await db.get(Assignment, assignment_id)
    if old and old.user_id == actor.id:
        await get_batch(db, old.batch_id, lock=True)
        await db.refresh(old)
    if old and old.user_id == actor.id and not old.active:
        await db.scalar(
            select(AnnotationBatch).where(AnnotationBatch.id == old.batch_id).with_for_update()
        )
        late = await db.scalar(
            select(LateSubmission).where(
                LateSubmission.assignment_id == old.id,
                LateSubmission.idempotency_key == idempotency_key,
            )
        )
        digest = canonical_sha256(body.model_dump())
        if late and late.payload_hash != digest:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "迟到历史幂等键内容不一致")
        if late is None:
            late = LateSubmission(
                assignment_id=old.id,
                phase=body.phase,
                payload=body.payload,
                payload_hash=digest,
                idempotency_key=idempotency_key,
            )
            db.add(late)
            await db.flush()
            audit(db, request, actor.id, "INVALID_LATE_SUBMISSION", old.id, {"history_id": late.id})
        # Return a response instead of raising so the transaction retains the append-only history.
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "INVALID_LATE",
                "message": "旧分配提交只保存历史，不计入统计",
                "request_id": request.state.request_id,
                "history_id": late.id,
            },
        )
    assignment, batch, unit = await own_assignment(db, actor, assignment_id)
    body_hash = canonical_sha256(body.model_dump())
    previous = await submission(db, assignment.id, body.phase)
    if previous:
        if previous.idempotency_key == idempotency_key and previous.payload_hash == body_hash:
            return {"id": previous.id, "status": "SEALED", "payload_hash": previous.payload_hash}
        raise ApiError(409, "SUBMISSION_SEALED", "正式提交已封存；更正须保留原因并进入新轮次")
    validate_phase(batch, body.phase)
    if (
        body.content_revision != assignment.content_revision
        or body.profile_version != batch.profile_version
    ):
        raise ApiError(409, "REVISION_CONFLICT", "内容或规则版本已变化，请重新获取任务")
    if body.phase == "BLIND":
        if any(
            not isinstance(body.payload.get(key), str) or not body.payload[key].strip()
            for key in ("answer", "reason")
        ):
            raise ApiError(422, "BLIND_ANSWER_REQUIRED", "须填写独立答案/行为判断及依据")
    else:
        if (
            batch.review_version == "openkb.s4-review.v2"
            and body.payload.get("review_version") != batch.review_version
        ):
            raise ApiError(422, "REVIEW_VERSION_REQUIRED", "新批次须使用逐对象依据v2审核协议")
        if body.profile_hash is not None and body.profile_hash != batch.profile_hash:
            raise ApiError(409, "PROFILE_REVISION_CONFLICT", "profile冻结版本冲突")
        validate_review(unit, body.payload)
    sealed = Submission(
        assignment_id=assignment.id,
        phase=body.phase,
        payload=body.payload,
        payload_hash=body_hash,
        idempotency_key=idempotency_key,
    )
    db.add(sealed)
    await db.flush()
    assignments = (
        await db.scalars(
            select(Assignment).where(Assignment.batch_id == batch.id, Assignment.active.is_(True))
        )
    ).all()
    completed = await db.scalar(
        select(func.count())
        .select_from(Submission)
        .where(
            Submission.assignment_id.in_([a.id for a in assignments]),
            Submission.phase == body.phase,
        )
    )
    if completed == len(assignments):
        batch.state = "BLIND_SEALED" if body.phase == "BLIND" else "PAIR_COMPLETE"
    audit(
        db,
        request,
        actor.id,
        "SUBMISSION_SEALED",
        assignment.id,
        {"phase": body.phase, "payload_hash": body_hash},
    )
    return {"id": sealed.id, "status": "SEALED", "payload_hash": body_hash}


@router.post("/rounds", status_code=201)
async def new_round(body: RoundInput, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    old = await business_batch(db, actor, body.batch_id, lock=True)
    if old.state in {"S4_READY", "SUPERSEDED"}:
        raise ApiError(409, "ROUND_CLOSED", "该轮已封存或交接，修订须另建来源版本")
    if old.review_version == "openkb.s4-review.v2":
        calibration = (
            await db.get(CalibrationRecord, body.calibration_id) if body.calibration_id else None
        )
        if not calibration or calibration.batch_id != old.id:
            raise ApiError(409, "CALIBRATION_REQUIRED", "v2全批新轮须关联本批校准会议和培训记录")
        if body.manual_version and body.manual_version != calibration.manual_version:
            raise ApiError(409, "MANUAL_VERSION_CONFLICT", "新轮手册须与校准决定一致")
    changes = (
        await db.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.batch_id == old.id)
            .order_by(ChangeEvent.created_at.desc())
        )
    ).all()
    linked_sources = []
    linked_profiles = []
    for event in changes:
        imported_change = await db.get(SourceImport, event.revision_ref)
        profile_change = await db.get(ProfileRevision, event.revision_ref)
        if imported_change and imported_change.id != old.import_id:
            linked_sources.append(imported_change.id)
        if profile_change and profile_change.dataset == old.dataset:
            linked_profiles.append(profile_change.id)
    source_id = body.source_import_id or (linked_sources[0] if linked_sources else old.import_id)
    if source_id != old.import_id and source_id not in linked_sources:
        raise ApiError(
            409, "SOURCE_REVISION_NOT_LINKED", "新来源须先通过本批材料问题登记关联，不能静默换源"
        )
    if linked_sources and source_id != linked_sources[0]:
        raise ApiError(409, "SOURCE_REVISION_CONFLICT", "须使用本批处置关联的新来源revision")
    profile_id = body.profile_revision_id or (
        linked_profiles[0] if linked_profiles else old.profile_revision_id
    )
    profile = (
        await db.get(ProfileRevision, profile_id)
        if profile_id
        else await db.scalar(
            select(ProfileRevision)
            .where(ProfileRevision.dataset == old.dataset, ProfileRevision.state == "APPROVED")
            .order_by(ProfileRevision.created_at.desc())
        )
    )
    if not profile or profile.dataset != old.dataset or profile.state != "APPROVED":
        raise ApiError(409, "PROFILE_NOT_APPROVED", "新轮须绑定本数据集已批准profile")
    if old.review_version == "openkb.s4-review.v2":
        assert calibration is not None
        if profile.manual_version != calibration.manual_version or (
            body.manual_version is not None and body.manual_version != profile.manual_version
        ):
            raise ApiError(
                409, "MANUAL_VERSION_CONFLICT", "新轮手册须与已批准profile及校准决定完全一致"
            )
    imported = await source(db, source_id)
    await lock_scope(db, "annotation-scope:" + source_id)
    conflict = await db.scalar(
        select(AnnotationBatch.id).where(
            AnnotationBatch.import_id == source_id,
            AnnotationBatch.dataset == old.dataset,
            AnnotationBatch.id != old.id,
            AnnotationBatch.state != "SUPERSEDED",
        )
    )
    if conflict:
        raise ApiError(409, "SCOPE_ALREADY_PLANNED", "新来源的数据集已有活动轮次")
    new = await add_batch(
        db,
        imported,
        BatchCreate(
            import_id=source_id,
            dataset=old.dataset,
            annotator_a=body.annotator_a,
            annotator_b=body.annotator_b,
            seed=body.seed,
            profile_revision_id=profile.id,
        ),
        round_no=old.round + 1,
        parent=old,
        reason=body.reason,
    )
    if source_id != old.import_id or profile.id != old.profile_revision_id:
        db.add(
            ChangeEvent(
                batch_id=old.id,
                change_type="NEW_ROUND_REVISION_BOUND",
                revision_ref=new.id,
                previous_hash=old.profile_hash,
                next_hash=new.profile_hash or "",
                actor_id=actor.id,
                reason=body.reason,
            )
        )
    new.calibration_id = body.calibration_id
    old.state = "SUPERSEDED"
    old.version += 1
    audit(
        db,
        request,
        actor.id,
        "NEW_ROUND_CREATED",
        new.id,
        {"parent_id": old.id, "reason_hash": canonical_sha256(body.reason)},
    )
    return await batch_view(db, new)


@router.post("/imports/upload", status_code=202)
async def import_upload(body: ImportUpload, request: Request, actor: Actor, db: Db) -> Any:
    import json
    from hashlib import sha256

    from ..services.import_validation import validate_import_report

    require_role(actor, "lead")
    raw_bytes = body.units_jsonl.encode("utf-8")
    if (
        len(raw_bytes)
        + len(json.dumps(body.envelope, ensure_ascii=False).encode("utf-8"))
        + len(json.dumps(body.source_index, ensure_ascii=False).encode("utf-8"))
        > request.app.state.settings.max_import_bytes
    ):
        raise ApiError(413, "IMPORT_TOO_LARGE", "上传材料超过允许大小")
    if "units" in body.envelope:
        raise ApiError(422, "UPLOAD_ENVELOPE_INVALID", "envelope不能重复提供units")
    errors = []
    units = []
    for row, line in enumerate(body.units_jsonl.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            unit = json.loads(line.lstrip("\ufeff") if row == 1 else line)
        except (ValueError, RecursionError):
            errors.append(
                {
                    "row": row,
                    "field_path": "units",
                    "error_code": "JSONL_PARSE_ERROR",
                    "message": "该行不是合法JSON对象",
                }
            )
            continue
        if not isinstance(unit, dict):
            errors.append(
                {
                    "row": row,
                    "field_path": "units",
                    "error_code": "INVALID_OBJECT",
                    "message": "该行须为单元对象",
                }
            )
            continue
        if (
            not unit.get("contexts")
            and isinstance(unit.get("metadata"), dict)
            and "context_doc_ids" in unit["metadata"]
        ):
            refs = unit["metadata"]["context_doc_ids"]
            if not isinstance(refs, list) or any(
                not isinstance(ref, str)
                or ref not in body.source_index
                or body.source_index[ref].get("doc_id") != ref
                for ref in refs
            ):
                errors.append(
                    {
                        "row": row,
                        "field_path": "metadata.context_doc_ids",
                        "error_code": "UPLOAD_INDEX_REFERENCE_INVALID",
                        "message": "原文引用须来自本次受控索引",
                    }
                )
                continue
            unit["contexts"] = [body.source_index[ref] for ref in refs]
        units.append(unit)
        if len(units) > 2200:
            raise ApiError(413, "IMPORT_TOO_LARGE", "上传单元数量超过2200")
    raw_hash = sha256(raw_bytes).hexdigest()
    if errors:
        report = {
            "valid": False,
            "total_rows": len(body.units_jsonl.splitlines()),
            "error_count": len(errors),
            "errors": errors[:100],
            "truncated": len(errors) > 100,
        }
        audit(
            db,
            request,
            actor.id,
            "IMPORT_UPLOAD_REJECTED",
            None,
            {"raw_file_sha256": raw_hash, "error_count": len(errors)},
        )
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "UPLOAD_INVALID",
                "message": "JSONL行或原文索引无效",
                "request_id": request.state.request_id,
                "details": {"validation_report": report},
            },
        )
    payload = {**body.envelope, "units": units}
    report = validate_import_report(payload)
    if not report["valid"]:
        audit(
            db,
            request,
            actor.id,
            "IMPORT_UPLOAD_REJECTED",
            None,
            {"raw_file_sha256": raw_hash, "error_count": report["error_count"]},
        )
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "IMPORT_VALIDATION_FAILED",
                "message": "上传材料未通过统一契约校验",
                "request_id": request.state.request_id,
                "details": {"validation_report": report},
            },
        )
    normalized_hash = canonical_sha256(payload)
    upload_dir = request.app.state.settings.data_dir / "imports"
    upload_dir.mkdir(parents=True, exist_ok=True)
    controlled_path = upload_dir / (raw_hash + ".jsonl")
    if not controlled_path.exists():
        import os
        from uuid import uuid4

        temporary = controlled_path.with_name(raw_hash + "." + str(uuid4()) + ".partial")
        with temporary.open("wb") as handle:
            handle.write(raw_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, controlled_path)
    response = await import_source(payload, request, actor, db)
    audit(
        db,
        request,
        actor.id,
        "IMPORT_FILE_UPLOADED",
        response["job_id"],
        {
            "raw_file_sha256": raw_hash,
            "normalized_sha256": normalized_hash,
            "file_ref": raw_hash + ".jsonl",
        },
    )
    return {
        **response,
        "raw_file_sha256": raw_hash,
        "normalized_sha256": normalized_hash,
        "validation_report": {key: value for key, value in report.items() if key != "normalized"},
    }


@router.post("/service/imports", status_code=202)
async def service_import(
    body: dict[str, Any], request: Request, db: Db, authorization: str = Header(default="")
) -> dict[str, str]:
    import hmac

    token = request.app.state.settings.import_token
    presented = authorization.removeprefix("Bearer ")
    if (
        not token
        or not authorization.startswith("Bearer ")
        or not hmac.compare_digest(token, presented)
    ):
        raise ApiError(401, "SERVICE_SCOPE_REQUIRED", "需要独立S3导入服务凭据")
    actor_id = request.app.state.settings.import_service_user_id
    service = await db.get(User, actor_id) if actor_id else None
    if (
        not service
        or not service.active
        or "lead" not in service.roles
        or "annotator" in service.roles
    ):
        raise ApiError(
            503, "SERVICE_IDENTITY_NOT_CONFIGURED", "S3导入凭据须绑定有效且不参标的服务账号"
        )
    request.state.actor_id = service.id
    response = await import_source(body, request, service, db)
    audit(
        db,
        request,
        service.id,
        "S3_SERVICE_IMPORT_REQUESTED",
        response["job_id"],
        {"scope": "s3:import"},
    )
    return {**response, "scope": "s3:import", "external_alignment": "NOT_ALIGNED"}
