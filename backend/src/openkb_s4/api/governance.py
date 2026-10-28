"""Finite profile approvals, independent issue handling, staffing and validation evidence."""

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select, true
from sqlalchemy.sql.elements import ColumnElement

from ..domain.contracts import canonical_sha256
from ..domain.profiles import get_profile, validate_profile_snapshot
from ..domain.review import validate_locator
from ..models import (
    Agreement,
    AnnotationBatch,
    Arbitration,
    Assignment,
    CalibrationRecord,
    ChangeEvent,
    Exposure,
    FinalDecision,
    ProfileRevision,
    Qualification,
    SeatReplacement,
    User,
    ValidationRevision,
    WorkIssue,
    now,
)
from ..schemas import (
    CalibrationInput,
    IssueInput,
    ProfileInput,
    ProfilePatch,
    ProfileReview,
    QualificationInput,
    ResolveIssue,
    SeatReplace,
    ValidationCandidateInput,
    ValidationInput,
    VersionReason,
)
from ..security import Actor, ApiError, Db, require_independent, require_role
from ..services.common import (
    audit,
    business_batch,
    family_keys,
    get_batch,
    own_assignment,
    source,
    source_unit,
    validate_final_gold,
)
from ..services.revisions import change_kind, final_candidate

router = APIRouter()


def view(item: Any) -> dict[str, Any]:
    result = {column.name: getattr(item, column.name) for column in item.__table__.columns}
    for key, value in result.items():
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def version_matches(actual: int, requested: int) -> None:
    if actual != requested:
        raise ApiError(409, "VERSION_CONFLICT", "记录已变化，请刷新后再操作")


async def profile_record(db: Db, profile_id: str, lock: bool = False) -> ProfileRevision:
    query = select(ProfileRevision).where(ProfileRevision.id == profile_id)
    item = await db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    return item


@router.get("/profile-revisions")
async def profiles(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    rows = (
        await db.scalars(
            select(ProfileRevision)
            .order_by(ProfileRevision.dataset, ProfileRevision.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {
        "items": [view(row) for row in rows],
        "total": await db.scalar(select(func.count()).select_from(ProfileRevision)),
    }


@router.get("/profile-revisions/{profile_id}")
async def profile_detail(profile_id: str, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    return view(await profile_record(db, profile_id))


@router.post("/profile-revisions", status_code=201)
async def create_profile(
    body: ProfileInput, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    validate_profile_snapshot(body.dataset, body.snapshot)
    if (
        body.version != body.snapshot["version"]
        or body.manual_version != body.snapshot["manual_version"]
    ):
        raise ApiError(422, "PROFILE_VERSION_MISMATCH", "快照与声明的版本须一致")
    item = ProfileRevision(
        dataset=body.dataset,
        version=body.version,
        manual_version=body.manual_version,
        snapshot=body.snapshot,
        canonical_hash=canonical_sha256(body.snapshot),
        creator_id=actor.id,
    )
    db.add(item)
    await db.flush()
    audit(
        db,
        request,
        actor.id,
        "PROFILE_DRAFT_CREATED",
        item.id,
        {"reason_hash": canonical_sha256(body.reason)},
    )
    return view(item)


@router.patch("/profile-revisions/{profile_id}")
async def update_profile(
    profile_id: str, body: ProfilePatch, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    item = await profile_record(db, profile_id, True)
    version_matches(item.revision, body.expected_revision)
    if item.state != "DRAFT":
        raise ApiError(409, "PROFILE_IMMUTABLE", "已提交或批准的配置不可编辑，请建新版本")
    validate_profile_snapshot(body.dataset, body.snapshot)
    if (
        body.dataset != item.dataset
        or body.version != item.version
        or body.snapshot["version"] != body.version
        or body.snapshot["manual_version"] != body.manual_version
    ):
        raise ApiError(422, "PROFILE_VERSION_MISMATCH", "草稿标识与快照版本须一致")
    item.snapshot, item.canonical_hash = body.snapshot, canonical_sha256(body.snapshot)
    item.manual_version = body.manual_version
    item.revision += 1
    audit(
        db,
        request,
        actor.id,
        "PROFILE_DRAFT_UPDATED",
        item.id,
        {"revision": item.revision, "reason_hash": canonical_sha256(body.reason)},
    )
    return view(item)


@router.post("/profile-revisions/{profile_id}/{action}")
async def transition_profile(
    profile_id: str, action: str, body: ProfileReview, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    item = await profile_record(db, profile_id, True)
    version_matches(item.revision, body.version)
    previous = item.state
    allowed = {
        "submit": ("DRAFT", "IN_REVIEW"),
        "approve": ("IN_REVIEW", "APPROVED"),
        "reject": ("IN_REVIEW", "DRAFT"),
        "retire": ("APPROVED", "RETIRED"),
    }
    if action not in allowed or item.state != allowed[action][0]:
        raise ApiError(409, "PROFILE_TRANSITION_INVALID", "当前状态不允许该操作")
    if action == "submit":
        require_role(actor, "lead")
    if action in {"approve", "reject"}:
        if item.creator_id == actor.id:
            raise ApiError(403, "INDEPENDENT_APPROVAL_REQUIRED", "配置须由另一授权人员评审")
        participating = await db.scalar(
            select(AnnotationBatch.id).where(
                AnnotationBatch.dataset == item.dataset,
                (AnnotationBatch.annotator_a == actor.id)
                | (AnnotationBatch.annotator_b == actor.id),
            )
        )
        if participating:
            raise ApiError(403, "PARTICIPANT_RESTRICTED", "参标人员不能批准本数据集规则")
    if action == "approve":
        if not body.evidence:
            raise ApiError(422, "APPROVAL_EVIDENCE_REQUIRED", "独立批准须保存审批依据")
        validate_profile_snapshot(item.dataset, item.snapshot)
        item.approver_id = actor.id
        item.approval = {
            "actor_id": actor.id,
            "reason": body.reason,
            "evidence": body.evidence,
            "at": now().isoformat(),
        }
        item.snapshot = {**item.snapshot, "approval": item.approval}
        item.canonical_hash = canonical_sha256(item.snapshot)

    if action == "approve":
        affected = (
            await db.scalars(
                select(AnnotationBatch)
                .where(
                    AnnotationBatch.dataset == item.dataset,
                    AnnotationBatch.state.notin_(["S4_READY", "SUPERSEDED", "CANCELLED"]),
                    AnnotationBatch.profile_hash != item.canonical_hash,
                )
                .with_for_update()
            )
        ).all()
        for batch in affected:
            await pause_batch(batch)
            batch.blocked_reasons = sorted(
                set(batch.blocked_reasons + ["PROFILE_REVISION_CHANGED"])
            )
            db.add(
                ChangeEvent(
                    batch_id=batch.id,
                    change_type="PROFILE_APPROVED",
                    revision_ref=item.id,
                    previous_hash=batch.profile_hash,
                    next_hash=item.canonical_hash,
                    actor_id=actor.id,
                    reason=body.reason,
                )
            )
            audit(
                db,
                request,
                actor.id,
                "BATCH_RULE_REVISION_INVALIDATED",
                batch.id,
                {
                    "before_profile_hash": batch.profile_hash,
                    "new_profile_hash": item.canonical_hash,
                    "version": batch.version,
                    "profile_revision_id": item.id,
                },
            )
    item.state = allowed[action][1]
    item.revision += 1
    audit(
        db,
        request,
        actor.id,
        "PROFILE_" + action.upper(),
        item.id,
        {
            "before": previous,
            "after": item.state,
            "version": item.revision,
            "reason_hash": canonical_sha256(body.reason),
        },
    )
    return view(item)


async def pause_batch(batch: AnnotationBatch) -> None:
    if batch.state not in {"PAUSED", "SUPERSEDED", "CANCELLED", "S4_READY"}:
        batch.resume_state, batch.state = batch.state, "PAUSED"
        batch.version += 1


@router.get("/work-issues")
async def issues(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    visible = WorkIssue.reporter_id == actor.id
    if set(actor.roles) & {"lead", "auditor"}:
        visible = (
            WorkIssue.batch_id.in_(
                select(AnnotationBatch.id).where(
                    AnnotationBatch.annotator_a != actor.id,
                    AnnotationBatch.annotator_b != actor.id,
                    AnnotationBatch.id.notin_(
                        select(Assignment.batch_id).where(Assignment.user_id == actor.id)
                    ),
                )
            )
            | visible
        )
    rows = (
        await db.scalars(
            select(WorkIssue)
            .where(visible)
            .order_by(WorkIssue.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {
        "items": [view(row) for row in rows],
        "total": await db.scalar(select(func.count()).select_from(WorkIssue).where(visible)),
    }


@router.post("/work-issues", status_code=201)
async def report_issue(body: IssueInput, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "annotator")
    assignment, batch, unit = await own_assignment(db, actor, body.assignment_id)
    if batch.state in {"S4_READY", "SUPERSEDED", "CANCELLED"}:
        raise ApiError(409, "ROUND_CLOSED", "封存批次须通过新revision处理")
    for location in body.locators:
        # Invalid locators can be reported without reproducing a false source coordinate.
        if body.issue_type != "INVALID_LOCATOR":
            validate_locator(unit, location.model_dump(exclude_none=True))
    item = WorkIssue(
        batch_id=batch.id,
        assignment_id=assignment.id,
        unit_id=assignment.unit_id,
        issue_type=body.issue_type,
        description=body.reason,
        locators=[loc.model_dump(exclude_none=True) for loc in body.locators],
        reporter_id=actor.id,
    )
    db.add(item)
    await pause_batch(batch)
    if body.issue_type == "EARLY_EXPOSURE":
        db.add(
            Exposure(
                user_id=actor.id,
                unit_id=assignment.unit_id,
                family_keys=sorted(family_keys(unit)),
                batch_id=batch.id,
                reason="EARLY_EXPOSURE_REPORTED",
            )
        )
    await db.flush()
    audit(
        db,
        request,
        actor.id,
        "WORK_ISSUE_OPENED",
        item.id,
        {
            "batch_id": batch.id,
            "before": batch.resume_state,
            "after": batch.state,
            "batch_version": batch.version,
        },
    )
    return view(item)


@router.post("/work-issues/{issue_id}/resolve")
async def resolve_issue(
    issue_id: str, body: ResolveIssue, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    item = await db.scalar(select(WorkIssue).where(WorkIssue.id == issue_id).with_for_update())
    if item is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    batch = await business_batch(db, actor, item.batch_id, lock=True)
    version_matches(item.version, body.version)
    if item.status != "OPEN":
        raise ApiError(409, "ISSUE_CLOSED", "问题已经处理")
    if item.reporter_id == actor.id:
        raise ApiError(403, "INDEPENDENT_RESOLUTION_REQUIRED", "须由独立运营核对处置依据")
    if body.disposition == "NEW_REVISION" and not body.revision_ref:
        raise ApiError(422, "REVISION_REQUIRED", "实质变化须关联受控新来源或profile revision")
    if body.disposition == "UNCHANGED" and item.issue_type == "EARLY_EXPOSURE":
        raise ApiError(409, "EXPOSURE_REQUIRES_NEW_ROUND", "提前暴露须安排未暴露人员新轮")
    if body.disposition == "NEW_REVISION":
        revision = await db.get(ProfileRevision, body.revision_ref)
        from ..models import SourceImport

        imported = await db.get(SourceImport, body.revision_ref)
        if not (
            (revision and revision.state == "APPROVED" and revision.dataset == batch.dataset)
            or (imported and imported.id != batch.import_id)
        ):
            raise ApiError(422, "REVISION_NOT_CONTROLLED", "新revision须为已批准配置或新受控来源")
        db.add(
            ChangeEvent(
                batch_id=batch.id,
                change_type="ISSUE_NEW_REVISION",
                revision_ref=body.revision_ref,
                previous_hash=batch.profile_hash,
                next_hash=revision.canonical_hash
                if revision
                else imported.content_hash
                if imported
                else "",
                actor_id=actor.id,
                reason=body.reason,
            )
        )
        batch.blocked_reasons = sorted(set(batch.blocked_reasons + ["NEW_ROUND_REQUIRED"]))
    item.status = "RESOLVED"
    item.resolver_id = actor.id
    item.resolution_reason = body.reason
    item.revision_ref = body.revision_ref
    item.version += 1
    await db.flush()
    remaining = await db.scalar(
        select(func.count())
        .select_from(WorkIssue)
        .where(WorkIssue.batch_id == batch.id, WorkIssue.status == "OPEN")
    )
    if (
        not remaining
        and not batch.blocked_reasons
        and body.disposition == "UNCHANGED"
        and batch.state == "PAUSED"
    ):
        batch.state = batch.resume_state or "BLIND_OPEN"
        batch.resume_state = None
        batch.version += 1
    audit(
        db,
        request,
        actor.id,
        "WORK_ISSUE_RESOLVED",
        item.id,
        {
            "batch_id": batch.id,
            "disposition": body.disposition,
            "batch_version": batch.version,
            "reason_hash": canonical_sha256(body.reason),
        },
    )
    return view(item)


@router.post("/annotation-batches/{batch_id}/pause")
async def pause(
    batch_id: str, body: VersionReason, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await business_batch(db, actor, batch_id, True)
    version_matches(batch.version, body.version)
    await pause_batch(batch)
    audit(
        db,
        request,
        actor.id,
        "BATCH_PAUSED",
        batch.id,
        {"reason_hash": canonical_sha256(body.reason), "version": batch.version},
    )
    return view(batch)


@router.post("/annotation-batches/{batch_id}/resume")
async def resume(
    batch_id: str, body: VersionReason, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await business_batch(db, actor, batch_id, True)
    version_matches(batch.version, body.version)
    if (
        batch.state != "PAUSED"
        or batch.blocked_reasons
        or await db.scalar(
            select(WorkIssue.id).where(WorkIssue.batch_id == batch.id, WorkIssue.status == "OPEN")
        )
    ):
        raise ApiError(409, "BATCH_BLOCKED", "须先处理全部材料问题及版本阻塞")
    batch.state = batch.resume_state or "BLIND_OPEN"
    batch.resume_state = None
    batch.version += 1
    audit(
        db,
        request,
        actor.id,
        "BATCH_RESUMED",
        batch.id,
        {"reason_hash": canonical_sha256(body.reason), "version": batch.version},
    )
    return view(batch)


@router.post("/annotation-batches/{batch_id}/replace-seat")
async def replace_seat(
    batch_id: str, body: SeatReplace, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    from .workflow import batch_view, check_pair

    require_role(actor, "lead")
    batch = await business_batch(db, actor, batch_id, True)
    version_matches(batch.version, body.version)
    if batch.state not in {"BLIND_OPEN", "BLIND_SEALED"}:
        raise ApiError(409, "SEAT_REPLACEMENT_CLOSED", "仅BLIND阶段可整席替换；REVIEW须完整新轮")
    previous_id = batch.annotator_a if body.seat == "A" else batch.annotator_b
    other_id = batch.annotator_b if body.seat == "A" else batch.annotator_a
    if body.new_annotator_id == previous_id:
        raise ApiError(422, "REPLACEMENT_SAME_USER", "替换人员须不同于原人员")
    imported = await source(db, batch.import_id)
    units = [source_unit(imported, unit_id) for unit_id in batch.selected_ids]
    await check_pair(db, body.new_annotator_id, other_id, units)
    qualification = await db.scalar(
        select(Qualification)
        .where(
            Qualification.user_id == body.new_annotator_id, Qualification.dataset == batch.dataset
        )
        .order_by(Qualification.created_at.desc())
    )
    if qualification and (not qualification.available or qualification.valid_until <= now()):
        raise ApiError(409, "ANNOTATOR_UNAVAILABLE", "新人员资格已过期或当前不可用")
    replacement = SeatReplacement(
        batch_id=batch.id,
        seat=body.seat,
        old_user_id=previous_id,
        new_user_id=body.new_annotator_id,
        actor_id=actor.id,
        reason=body.reason,
        version=batch.version,
    )
    db.add(replacement)
    await db.flush()
    old_rows = (
        await db.scalars(
            select(Assignment)
            .where(
                Assignment.batch_id == batch.id,
                Assignment.seat == body.seat,
                Assignment.active.is_(True),
            )
            .with_for_update()
        )
    ).all()
    if {row.unit_id for row in old_rows} != set(batch.selected_ids):
        raise ApiError(409, "ASSIGNMENT_SCOPE_INVALID", "原席位完整范围不一致，须先对账")
    for old in old_rows:
        old.active = False
    await db.flush()
    for old in old_rows:
        new = Assignment(
            batch_id=batch.id,
            unit_id=old.unit_id,
            user_id=body.new_annotator_id,
            seat=body.seat,
            content_revision=old.content_revision,
            unit_revision_id=old.unit_revision_id,
            gold_revision_id=old.gold_revision_id,
            replacement_id=replacement.id,
        )
        db.add(new)
        await db.flush()
        old.replaced_by_id = new.id
    if body.seat == "A":
        batch.annotator_a = body.new_annotator_id
    else:
        batch.annotator_b = body.new_annotator_id
    batch.state = "BLIND_OPEN"
    batch.version += 1
    audit(
        db,
        request,
        actor.id,
        "SEAT_REPLACED",
        replacement.id,
        {
            "batch_id": batch.id,
            "before_user": previous_id,
            "after_user": body.new_annotator_id,
            "version": batch.version,
            "reason_hash": canonical_sha256(body.reason),
        },
    )
    return {**await batch_view(db, batch), "replacement_id": replacement.id}


@router.get("/calibrations")
async def calibrations(
    request: Request,
    actor: Actor,
    db: Db,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    visible = CalibrationRecord.batch_id.in_(
        select(AnnotationBatch.id).where(
            AnnotationBatch.annotator_a != actor.id,
            AnnotationBatch.annotator_b != actor.id,
            AnnotationBatch.id.notin_(
                select(Assignment.batch_id).where(Assignment.user_id == actor.id)
            ),
        )
    )
    rows = (
        await db.scalars(
            select(CalibrationRecord)
            .where(visible)
            .order_by(CalibrationRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    for row in rows:
        batch = await get_batch(db, row.batch_id)
        imported = await source(db, batch.import_id)
        for unit_id in row.case_refs:
            unit = source_unit(imported, unit_id)
            db.add(
                Exposure(
                    user_id=actor.id,
                    unit_id=unit_id,
                    family_keys=sorted(family_keys(unit)),
                    batch_id=batch.id,
                    reason="CALIBRATION_CASE_READ",
                )
            )
        audit(
            db,
            request,
            actor.id,
            "CALIBRATION_READ",
            row.id,
            {"batch_id": batch.id, "case_count": len(row.case_refs)},
        )
    return {
        "items": [view(row) for row in rows],
        "total": await db.scalar(
            select(func.count()).select_from(CalibrationRecord).where(visible)
        ),
    }


@router.post("/calibrations", status_code=201)
async def create_calibration(
    body: CalibrationInput, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await business_batch(db, actor, body.batch_id, True)
    if body.meeting_at.tzinfo is None or len(set(body.participant_ids)) != len(
        body.participant_ids
    ):
        raise ApiError(422, "CALIBRATION_INVALID", "会议须有时区且参加人不得重复")
    if not set(body.case_refs) <= set(batch.selected_ids):
        raise ApiError(422, "CALIBRATION_SCOPE_INVALID", "案例须引用本批抽检单元")
    for participant in body.participant_ids:
        if await db.get(User, participant) is None:
            raise ApiError(422, "PARTICIPANT_INVALID", "参加人必须为现有人员")
    agreement = await db.scalar(select(Agreement).where(Agreement.batch_id == batch.id))
    item = CalibrationRecord(
        **body.model_dump(),
        original_agreement=agreement.result if agreement else {},
        actor_id=actor.id,
    )
    imported = await source(db, batch.import_id)
    for unit_id in body.case_refs:
        unit = source_unit(imported, unit_id)
        for participant_id in body.participant_ids:
            db.add(
                Exposure(
                    user_id=participant_id,
                    unit_id=unit_id,
                    family_keys=sorted(family_keys(unit)),
                    batch_id=batch.id,
                    reason="CALIBRATION_CASE_ATTENDED",
                )
            )
    db.add(item)
    await db.flush()
    audit(
        db,
        request,
        actor.id,
        "CALIBRATION_RECORDED",
        item.id,
        {"batch_id": batch.id, "manual_version": body.manual_version},
    )
    return view(item)


@router.get("/qualifications")
async def qualifications(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor", "annotator")
    visible = (
        true() if set(actor.roles) & {"lead", "auditor"} else Qualification.user_id == actor.id
    )
    rows = (
        await db.scalars(
            select(Qualification)
            .where(visible)
            .order_by(Qualification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {
        "items": [view(row) for row in rows],
        "total": await db.scalar(select(func.count()).select_from(Qualification).where(visible)),
    }


@router.post("/qualifications", status_code=201)
async def qualify(
    body: QualificationInput, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    get_profile(body.dataset)
    user = await db.get(User, body.user_id)
    if not user or "annotator" not in user.roles or body.user_id == actor.id:
        raise ApiError(422, "QUALIFICATION_ACTOR_INVALID", "资格须由独立负责人批准有效标注员")
    if body.valid_until.tzinfo is None or body.valid_until <= now() or not body.evidence:
        raise ApiError(422, "QUALIFICATION_EVIDENCE_REQUIRED", "资格须有未来有效期及批准依据")
    item = Qualification(**body.model_dump(), approver_id=actor.id)
    db.add(item)
    await db.flush()
    audit(
        db,
        request,
        actor.id,
        "QUALIFICATION_RECORDED",
        item.id,
        {"user_id": body.user_id, "dataset": body.dataset},
    )
    return view(item)


@router.get("/validation-revisions")
async def validations(
    request: Request,
    actor: Actor,
    db: Db,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    require_role(actor, "lead", "auditor", "verifier")
    visible: ColumnElement[bool] = ValidationRevision.batch_id.in_(
        select(AnnotationBatch.id).where(
            AnnotationBatch.annotator_a != actor.id,
            AnnotationBatch.annotator_b != actor.id,
            AnnotationBatch.id.notin_(
                select(Assignment.batch_id).where(Assignment.user_id == actor.id)
            ),
        )
    )
    # A standalone verifier sees only their own records; role alone grants no batch browse permission.
    if not set(actor.roles) & {"lead", "auditor"}:
        visible = visible & (ValidationRevision.verifier_id == actor.id)
    rows = (
        await db.scalars(
            select(ValidationRevision)
            .where(visible)
            .order_by(ValidationRevision.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    for row in rows:
        batch = await get_batch(db, row.batch_id)
        imported = await source(db, batch.import_id)
        unit = source_unit(imported, row.unit_id)
        db.add(
            Exposure(
                user_id=actor.id,
                unit_id=row.unit_id,
                family_keys=sorted(family_keys(unit)),
                batch_id=batch.id,
                reason="VALIDATION_RECORD_READ",
            )
        )
        audit(
            db,
            request,
            actor.id,
            "VALIDATION_RECORD_READ",
            row.id,
            {"batch_id": batch.id, "unit_id": row.unit_id},
        )
    return {
        "items": [view(row) for row in rows],
        "total": await db.scalar(
            select(func.count()).select_from(ValidationRevision).where(visible)
        ),
    }


@router.post("/validation-revisions", status_code=201)
async def record_validation(
    body: ValidationInput, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "verifier")
    batch = await get_batch(db, body.batch_id, True)
    require_independent(actor, batch)
    if await db.scalar(
        select(Assignment.id)
        .where(Assignment.batch_id == batch.id, Assignment.user_id == actor.id)
        .limit(1)
    ):
        raise ApiError(403, "PARTICIPANT_RESTRICTED", "历史参标人员不能复验本批候选")
    if body.unit_id not in batch.selected_ids:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    decision = await db.scalar(
        select(FinalDecision).where(
            FinalDecision.batch_id == batch.id, FinalDecision.unit_id == body.unit_id
        )
    )
    if decision and decision.actor_id == actor.id:
        raise ApiError(403, "INDEPENDENT_VERIFIER_REQUIRED", "最终修订人与复验人须不同")
    proposal = await db.scalar(
        select(ValidationRevision)
        .where(
            ValidationRevision.batch_id == batch.id,
            ValidationRevision.unit_id == body.unit_id,
            ValidationRevision.content_hash == body.content_hash,
            ValidationRevision.profile_hash == body.profile_hash,
            ValidationRevision.status == "PENDING",
        )
        .order_by(ValidationRevision.created_at.desc())
    )
    if not proposal:
        raise ApiError(409, "VALIDATION_PROPOSAL_REQUIRED", "须先由负责人登记候选和复验范围")
    if await db.scalar(
        select(Arbitration.id).where(
            Arbitration.batch_id == batch.id,
            Arbitration.unit_id == body.unit_id,
            Arbitration.arbitrator_id == actor.id,
        )
    ):
        raise ApiError(403, "INDEPENDENT_VERIFIER_REQUIRED", "仲裁内容作者不能复验本人修订")
    if proposal.editor_id == actor.id:
        raise ApiError(403, "INDEPENDENT_VERIFIER_REQUIRED", "修订提出人与复验人须为不同人员")
    if proposal.verifier_id != actor.id:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    if batch.state != "PAIR_COMPLETE":
        raise ApiError(409, "VALIDATION_SCOPE_CLOSED", "复验范围已暂停、失效或完成")
    imported = await source(db, batch.import_id)
    unit = source_unit(imported, body.unit_id)
    validate_final_gold(unit, body.final_gold)
    expected = canonical_sha256(final_candidate(unit, body.final_gold))
    if body.content_hash != expected or body.profile_hash != batch.profile_hash:
        raise ApiError(409, "VALIDATION_DIGEST_CONFLICT", "复验证据须绑定当前完整候选及profile摘要")
    evidence = body.evidence
    allowed = {
        "kind",
        "revision",
        "content_hash",
        "profile_hash",
        "point_results",
        "locators",
        "source_ref",
    }
    if (
        set(evidence) - allowed
        or evidence.get("kind") not in {"synthetic", "controlled_s3"}
        or not isinstance(evidence.get("revision"), str)
        or not evidence["revision"].strip()
        or evidence.get("content_hash") != expected
        or evidence.get("profile_hash") != batch.profile_hash
    ):
        raise ApiError(
            422,
            "VALIDATION_EVIDENCE_INVALID",
            "须提供受控证据结构及一致摘要；不接受浏览器passed声明",
        )
    if evidence["kind"] == "controlled_s3":
        raise ApiError(
            409, "EXTERNAL_CONTRACT_NOT_ALIGNED", "真实S3复验接入尚未对齐，不能自声明正式PASS"
        )
    if imported.mode != "demo":
        raise ApiError(409, "SYNTHETIC_EVIDENCE_DEMO_ONLY", "合成复验证据只适用于演示来源")
    results = evidence.get("point_results")
    expected_points = {
        f"P{i + 1:03d}" for i, _ in enumerate(body.final_gold.get("answer_points", []))
    }
    if (
        not isinstance(results, list)
        or any(
            not isinstance(row, dict)
            or set(row) != {"point_key", "status", "reason"}
            or row["status"] not in {"PASS", "FAIL"}
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
            for row in results
        )
        or {row["point_key"] for row in results} != expected_points
        or len(results) != len(expected_points)
    ):
        raise ApiError(422, "VALIDATION_POINT_COVERAGE_REQUIRED", "逐点证据须完整且不重复")
    locators = evidence.get("locators")
    if not isinstance(locators, list) or not locators:
        raise ApiError(422, "VALIDATION_LOCATORS_REQUIRED", "复验须提供原文定位核对证据")
    for location in locators:
        validate_locator(unit, location)
    item = ValidationRevision(
        batch_id=batch.id,
        unit_id=body.unit_id,
        content_hash=expected,
        profile_hash=body.profile_hash,
        final_gold=body.final_gold,
        validation_revision=evidence["revision"],
        status="PASS" if all(row["status"] == "PASS" for row in results) else "FAIL",
        change_kind=change_kind(unit, body.final_gold),
        editor_id=proposal.editor_id,
        verifier_id=actor.id,
        evidence=evidence,
        evidence_hash=canonical_sha256(evidence),
        reason=body.reason,
    )
    db.add(item)
    await db.flush()
    audit(
        db,
        request,
        actor.id,
        "VALIDATION_REVISION_RECORDED",
        item.id,
        {
            "batch_id": batch.id,
            "unit_id": body.unit_id,
            "status": item.status,
            "evidence_hash": item.evidence_hash,
        },
    )
    return view(item)


def candidate_view(
    batch: AnnotationBatch, proposal: ValidationRevision, unit: dict[str, Any]
) -> dict[str, Any]:
    return {
        "proposal_id": proposal.id,
        "verifier_id": proposal.verifier_id,
        "editor_id": proposal.editor_id,
        "batch_id": batch.id,
        "unit_id": proposal.unit_id,
        "final_gold": proposal.final_gold,
        "content_hash": proposal.content_hash,
        "profile_hash": proposal.profile_hash,
        "contexts": unit.get("contexts", []),
        "material": unit,
        "change_kind": proposal.change_kind,
        "validation_revision": proposal.validation_revision,
    }


@router.post("/validation-candidates", status_code=201)
async def propose_validation(
    body: ValidationCandidateInput, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await business_batch(db, actor, body.batch_id, True)
    if batch.state != "PAIR_COMPLETE" or body.unit_id not in batch.selected_ids:
        raise ApiError(409, "VALIDATION_SCOPE_CLOSED", "候选须属于已完成复核且未定稿的本批单元")
    verifier = await db.get(User, body.verifier_id)
    if not verifier or not verifier.active or "verifier" not in verifier.roles:
        raise ApiError(422, "VERIFIER_INVALID", "须指定有效且获verifier能力的独立复验人")
    if verifier.id in {actor.id, batch.annotator_a, batch.annotator_b} or await db.scalar(
        select(Assignment.id)
        .where(Assignment.batch_id == batch.id, Assignment.user_id == verifier.id)
        .limit(1)
    ):
        raise ApiError(
            403, "INDEPENDENT_VERIFIER_REQUIRED", "指定复验人须独立于本批参标及最终内容修订人"
        )
    if await db.scalar(
        select(Arbitration.id).where(
            Arbitration.batch_id == batch.id,
            Arbitration.unit_id == body.unit_id,
            Arbitration.arbitrator_id == verifier.id,
        )
    ):
        raise ApiError(
            403, "INDEPENDENT_VERIFIER_REQUIRED", "仲裁内容作者不能被指定为本人修订的复验人"
        )
    imported = await source(db, batch.import_id)
    unit = source_unit(imported, body.unit_id)
    validate_final_gold(unit, body.final_gold)
    digest = canonical_sha256(final_candidate(unit, body.final_gold))
    proposal = ValidationRevision(
        batch_id=batch.id,
        unit_id=body.unit_id,
        content_hash=digest,
        profile_hash=batch.profile_hash or "",
        final_gold=body.final_gold,
        validation_revision="proposal:" + digest,
        status="PENDING",
        change_kind=change_kind(unit, body.final_gold),
        editor_id=actor.id,
        verifier_id=verifier.id,
        evidence={"scope": "independent-source-check"},
        evidence_hash=canonical_sha256({"scope": "independent-source-check"}),
        reason=body.reason,
    )
    previous = await db.scalar(
        select(ValidationRevision).where(
            ValidationRevision.batch_id == batch.id,
            ValidationRevision.unit_id == body.unit_id,
            ValidationRevision.validation_revision == proposal.validation_revision,
        )
    )
    if previous is not None:
        if previous.verifier_id != verifier.id or previous.editor_id != actor.id:
            raise ApiError(
                409,
                "VALIDATION_ASSIGNMENT_IMMUTABLE",
                "复验分配已冻结，更换人员须登记新候选revision",
            )
        db.add(
            Exposure(
                user_id=actor.id,
                unit_id=body.unit_id,
                family_keys=sorted(family_keys(unit)),
                batch_id=batch.id,
                reason="VALIDATION_CANDIDATE_PROPOSED",
            )
        )
        audit(
            db,
            request,
            actor.id,
            "VALIDATION_CANDIDATE_READ",
            previous.id,
            {"batch_id": batch.id, "unit_id": body.unit_id},
        )
        return candidate_view(batch, previous, unit)
    db.add(proposal)
    await db.flush()
    audit(
        db,
        request,
        actor.id,
        "VALIDATION_CANDIDATE_PROPOSED",
        proposal.id,
        {
            "batch_id": batch.id,
            "unit_id": body.unit_id,
            "content_hash": digest,
            "editor_id": actor.id,
            "verifier_id": verifier.id,
        },
    )
    db.add(
        Exposure(
            user_id=actor.id,
            unit_id=body.unit_id,
            family_keys=sorted(family_keys(unit)),
            batch_id=batch.id,
            reason="VALIDATION_CANDIDATE_PROPOSED",
        )
    )
    return candidate_view(batch, proposal, unit)


@router.get("/validation-candidates")
async def validation_candidate(
    batch_id: str, unit_id: str, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "verifier", "lead", "auditor")
    batch = await get_batch(db, batch_id)
    require_independent(actor, batch)
    if await db.scalar(
        select(Assignment.id)
        .where(Assignment.batch_id == batch.id, Assignment.user_id == actor.id)
        .limit(1)
    ):
        raise ApiError(403, "PARTICIPANT_RESTRICTED", "历史参标人员不能读取本批复验候选")
    proposal = await db.scalar(
        select(ValidationRevision)
        .where(
            ValidationRevision.batch_id == batch.id,
            ValidationRevision.unit_id == unit_id,
            ValidationRevision.status == "PENDING",
        )
        .order_by(ValidationRevision.created_at.desc())
    )
    if (
        proposal is None
        or unit_id not in batch.selected_ids
        or (proposal.verifier_id != actor.id and not set(actor.roles) & {"lead", "auditor"})
    ):
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    if proposal.editor_id == actor.id and not set(actor.roles) & {"lead", "auditor"}:
        raise ApiError(403, "INDEPENDENT_VERIFIER_REQUIRED", "修订人不能独立复验本人候选")
    imported = await source(db, batch.import_id)
    unit = source_unit(imported, unit_id)
    db.add(
        Exposure(
            user_id=actor.id,
            unit_id=unit_id,
            family_keys=sorted(family_keys(unit)),
            batch_id=batch.id,
            reason="VALIDATION_CANDIDATE_READ",
        )
    )
    audit(
        db,
        request,
        actor.id,
        "VALIDATION_CANDIDATE_READ",
        proposal.id,
        {"batch_id": batch.id, "unit_id": unit_id},
    )
    return candidate_view(batch, proposal, unit)
