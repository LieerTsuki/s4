"""Explicit v2 HTTP surface for v1.3 full verification and observation."""

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select

from ..db import lock_scope
from ..domain import v13 as domain
from ..domain.contracts import canonical_sha256
from ..models import User, now
from ..models_v13 import (
    V13Assignment,
    V13Batch,
    V13Draft,
    V13Import,
    V13Issue,
    V13LateSubmission,
    V13QualityAction,
    V13Revision,
    V13Submission,
    V13Unit,
)
from ..schemas_v13 import (
    DraftInput,
    IssueCreate,
    IssueResolve,
    NewRoundInput,
    ObservationBatchCreate,
    QualityActionCreate,
    ReplacementInput,
    RevisionCreate,
    RevisionVerify,
    SubmitInput,
    VerificationBatchCreate,
)
from ..security import Actor, ApiError, Db, require_role
from ..services.common import audit
from ..services.workflow_v13 import (
    annotator,
    assert_assignment_compatible,
    assert_frozen_profile,
    assert_review_visible,
    assert_task_writable,
    assert_unexposed,
    batch_view,
    business_access,
    family_keys,
    frozen_hash,
    get_batch,
    get_import,
    hidden_import_ids,
    import_report,
    main_release,
    mark_exposure,
    own_task,
    read_draft,
    require_primary_review,
    split_unit,
    store_for,
    task_view,
    verification_record,
)

router = APIRouter()


def source_view(item: V13Import, count: int) -> dict[str, Any]:
    return {"id": item.id, "batch_id": item.batch_id, "source_revision": item.source_revision,
            "mode": item.mode, "status": item.status, "unit_count": count, "N": count,
            "blocked_reasons": item.blockers, "created_at": item.created_at.isoformat(),
            "contract_version": "openkb.s3-s4.v2"}


@router.get("/profiles")
async def profiles(actor: Actor) -> list[dict[str, Any]]:
    quotas = {"QA-D1": 500, "QA-D2": 200, "QA-D3": 100, "QA-D4": 100, "QA-D4C": 100,
              "QA-D5": 300, "QA-D6": 200, "QA-D7": 200, "SEC-D1": 100, "SEC-D2": 150,
              "SEC-D3": 50, "SEC-D4": 200, "SEC-D5": 100}
    return [{"dataset": key, "quota": quota, "version": "s4-v1.3",
             "review_version": "openkb.s4-review.v3", "manual_version": "manual-v1.3",
             "kind": "extraction" if key == "QA-D6" else "security" if key.startswith("SEC") else "qa",
             "formal_enabled": False, "blocked_reasons": ["EXTERNAL_ALIGNMENT_NOT_CONFIRMED", "POLICY_J1_C1_PENDING"]}
            for key, quota in quotas.items()]


@router.post("/imports", status_code=201)
async def create_import(body: dict[str, Any], request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > request.app.state.settings.max_import_bytes:
        raise ApiError(413, "IMPORT_TOO_LARGE", "导入材料超过允许大小")
    normalized = await asyncio.to_thread(domain.validate_envelope, body)
    content_hash = canonical_sha256(normalized)
    await lock_scope(db, "v13-import:" + normalized["batch_id"] + ":" + normalized["source_revision"])
    existing = await db.scalar(select(V13Import).where(V13Import.batch_id == normalized["batch_id"],
                                                       V13Import.source_revision == normalized["source_revision"]))
    store = store_for(request)
    if existing:
        if existing.content_hash != content_hash:
            raise ApiError(409, "SOURCE_REVISION_CONFLICT", "相同来源版本内容不同，须显式增加来源版本")
        units = (await db.scalars(select(V13Unit).where(V13Unit.import_id == existing.id))).all()
        for unit in units:
            mark_exposure(db, actor, unit, None, "IMPORT_UPLOADED")
        return source_view(existing, len(units))
    imported = V13Import(batch_id=normalized["batch_id"], source_revision=normalized["source_revision"],
                         mode=normalized["mode"], content_hash=content_hash,
                         source_ref=await asyncio.to_thread(store.put_json, normalized), creator_id=actor.id,
                         blockers=domain.source_blockers(normalized), status="WAITING_VERIFICATION")
    db.add(imported)
    await db.flush()
    for unit in normalized["units"]:
        material, gold = split_unit(unit)
        material_ref = await asyncio.to_thread(store.put_json, material)
        gold_ref = await asyncio.to_thread(store.put_json, gold)
        unit_ref = await asyncio.to_thread(store.put_json, unit)
        index = V13Unit(import_id=imported.id, unit_id=unit["unit_id"], dataset=unit["dataset"],
                        difficulty=unit["difficulty"], content_revision=canonical_sha256(unit),
                        material_ref=material_ref, gold_ref=gold_ref,
                        source_ref=unit_ref, family_keys=family_keys(unit))
        db.add(index)
        mark_exposure(db, actor, index, None, "IMPORT_UPLOADED")
    audit(db, request, actor.id, "V13_IMPORT_CREATED", imported.id, {"source_hash": content_hash, "N": len(normalized["units"])})
    return source_view(imported, len(normalized["units"]))


@router.get("/imports")
async def imports(actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    hidden = await hidden_import_ids(db, actor)
    query = select(V13Import).where(V13Import.id.notin_(hidden))
    rows = (await db.scalars(query.order_by(V13Import.created_at.desc()).offset(offset).limit(limit))).all()
    items = []
    for row in rows:
        count = await db.scalar(select(func.count()).select_from(V13Unit).where(V13Unit.import_id == row.id))
        items.append(source_view(row, count or 0))
    return {"items": items, "total": await db.scalar(select(func.count()).select_from(query.subquery()))}


@router.get("/imports/{import_id}/report")
async def report(import_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    await business_access(db, actor, import_id)
    imported = await get_import(db, import_id)
    result = await import_report(db, store_for(request), imported)
    if result["quality"]:
        for unit in (await db.scalars(select(V13Unit).where(V13Unit.import_id == imported.id))).all():
            await lock_operator_exposure(db, actor, imported.id)
            mark_exposure(db, actor, unit, None, "QUALITY_REPORT_READ")
    return result


async def lock_operator_exposure(db: Db, actor: User, import_id: str) -> None:
    # Serialize exposure with planning, then re-check any just-committed assignment.
    await lock_scope(db, "v13-person:" + actor.person_id)
    await business_access(db, actor, import_id)


@router.get("/imports/{import_id}")
async def import_detail(import_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    await business_access(db, actor, import_id)
    imported = await get_import(db, import_id)
    units = (await db.scalars(select(V13Unit).where(V13Unit.import_id == import_id))).all()
    for unit in units:
        mark_exposure(db, actor, unit, None, "SOURCE_READ")
    return {**source_view(imported, len(units)), "units": [{"unit_index_id": unit.id, "unit_id": unit.unit_id,
             "dataset": unit.dataset, "difficulty": unit.difficulty, "content_revision": unit.content_revision,
             "final_revision": unit.final_revision} for unit in units]}


async def prepare_batch(db: Db, body: VerificationBatchCreate | ObservationBatchCreate,
                         actor: User, request: Request, kind: str) -> V13Batch:
    require_role(actor, "lead")
    if body.profile_version != "s4-v1.3" or body.manual_version != "manual-v1.3":
        raise ApiError(422, "PROFILE_NOT_REGISTERED", "只允许已登记的v1.3本地有限表单与手册版本；正式批准仍待外部确认")
    imported = await get_import(db, body.import_id, lock=True)
    await business_access(db, actor, imported.id)
    if imported.status == "RETURNED_TO_S2":
        raise ApiError(409, "RETURNED_TO_S2", "退回后的原批不能重新标为完成，请接收新S3来源")
    units = list((await db.scalars(select(V13Unit).where(V13Unit.import_id == imported.id, V13Unit.dataset == body.dataset))).all())
    if not units:
        raise ApiError(422, "DATASET_EMPTY", "来源中没有该数据集")
    old = await db.scalar(select(V13Batch).where(V13Batch.import_id == imported.id, V13Batch.dataset == body.dataset,
                                                V13Batch.workflow_kind == kind).order_by(V13Batch.round.desc()))
    if old and (not isinstance(body, ObservationBatchCreate) or not body.parent_id):
        raise ApiError(409, "BATCH_EXISTS", "该来源数据集已有此类计划，不能重复分发覆盖历史")
    store = store_for(request)
    selected = units
    ledger: dict[str, Any] = {"required_count": len(units), "actual_count": len(units), "shortfall": 0}
    parent = None
    if isinstance(body, ObservationBatchCreate):
        users = [await annotator(db, body.annotator_a), await annotator(db, body.annotator_b)]
        if users[0].person_id == users[1].person_id:
            raise ApiError(422, "DISTINCT_PEOPLE_REQUIRED", "观测A/B须为两个不同真实人员")
        ledger = domain.sample_units([store.read_json(unit.source_ref) for unit in units], body.seed)
        if body.parent_id:
            parent = await get_batch(db, body.parent_id)
            if parent.import_id != imported.id or parent.dataset != body.dataset or parent.workflow_kind != kind or not parent.quality_ref:
                raise ApiError(422, "EXPANSION_PARENT_INVALID", "扩样须关联已有实际观测报告的同来源数据集")
            if not body.expanded_count or body.expanded_count <= len(parent.selected_ids):
                raise ApiError(422, "EXPANSION_NOT_LARGER", "扩样数量须大于原范围，原κ不覆盖")
            target = min(body.expanded_count, len(units))
            remaining = sorted(set(unit.unit_id for unit in units) - set(parent.selected_ids),
                               key=lambda value: canonical_sha256([body.seed, value]))
            ledger = {**ledger, "selected_ids": parent.selected_ids + remaining[:max(0, target - len(parent.selected_ids))],
                      "required_count": body.expanded_count, "actual_count": target,
                      "shortfall": max(0, body.expanded_count - len(units)), "parent_id": parent.id}
        selected = [unit for unit in units if unit.unit_id in ledger["selected_ids"]]
        seats = [(users[0], "A"), (users[1], "B")]
    else:
        users = [await annotator(db, user_id) for user_id in dict.fromkeys(body.assignee_ids)]
        seats = [(user, "V") for user in users]
    for user in sorted(users, key=lambda value: value.person_id):
        await assert_assignment_compatible(db, user, selected, kind)
    batch = V13Batch(import_id=imported.id, dataset=body.dataset, workflow_kind=kind,
                     selected_ids=sorted(unit.unit_id for unit in selected), sample_ledger=ledger,
                     profile_version=body.profile_version, manual_version=body.manual_version,
                     frozen_hash=frozen_hash(selected, body.profile_version, body.manual_version),
                     creator_id=actor.id, round=old.round + 1 if old else 1, parent_id=parent.id if parent else None)
    db.add(batch)
    await db.flush()
    for index, unit in enumerate(sorted(selected, key=lambda row: row.unit_id)):
        assigned = seats if kind == "OBSERVATION" else [seats[index % len(seats)]]
        for user, seat in assigned:
            db.add(V13Assignment(batch_id=batch.id, unit_index_id=unit.id, user_id=user.id,
                                  seat=seat, content_revision=unit.content_revision,
                                  material_ref=unit.material_ref, gold_ref=unit.gold_ref))
    audit(db, request, actor.id, "V13_" + kind + "_PLANNED", batch.id, {"N": len(units), "n": len(selected), "frozen_hash": batch.frozen_hash})
    await db.flush()
    return batch


@router.post("/verification-batches", status_code=201)
async def create_verification(body: VerificationBatchCreate, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    return await batch_view(db, await prepare_batch(db, body, actor, request, "VERIFICATION"), store_for(request))


@router.post("/observation-batches", status_code=201)
async def create_observation(body: ObservationBatchCreate, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    return await batch_view(db, await prepare_batch(db, body, actor, request, "OBSERVATION"), store_for(request))


async def list_batches(kind: str, request: Request, actor: User, db: Db, offset: int, limit: int) -> dict[str, Any]:
    require_role(actor, "lead", "auditor", "arbitrator")
    hidden = await hidden_import_ids(db, actor)
    query = select(V13Batch).where(V13Batch.workflow_kind == kind, V13Batch.import_id.notin_(hidden))
    rows = (await db.scalars(query.order_by(V13Batch.created_at.desc()).offset(offset).limit(limit))).all()
    for row in rows:
        await mark_quality_exposure(db, actor, row)
    return {"items": [await batch_view(db, row, store_for(request)) for row in rows],
            "total": await db.scalar(select(func.count()).select_from(query.subquery()))}


@router.get("/verification-batches")
async def verification_batches(request: Request, actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    return await list_batches("VERIFICATION", request, actor, db, offset, limit)


@router.get("/observation-batches")
async def observation_batches(request: Request, actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    return await list_batches("OBSERVATION", request, actor, db, offset, limit)


@router.get("/batches/{batch_id}")
async def batch_detail(batch_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    batch = await get_batch(db, batch_id)
    await business_access(db, actor, batch.import_id)
    await mark_quality_exposure(db, actor, batch)
    return await batch_view(db, batch, store_for(request))


async def mark_quality_exposure(db: Db, actor: User, batch: V13Batch) -> None:
    if batch.quality_ref:
        await lock_operator_exposure(db, actor, batch.import_id)
        for unit in (await db.scalars(select(V13Unit).where(V13Unit.import_id == batch.import_id,
                V13Unit.unit_id.in_(batch.selected_ids)))).all():
            mark_exposure(db, actor, unit, None, "BATCH_QUALITY_READ")


@router.post("/batches/{batch_id}/new-round", status_code=201)
async def new_round(batch_id: str, body: NewRoundInput, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    previous = await get_batch(db, batch_id, lock=True)
    imported = await get_import(db, previous.import_id, lock=True)
    await business_access(db, actor, imported.id)
    if imported.status == "RETURNED_TO_S2" or previous.state in {"SUPERSEDED", "CANCELLED", "RETURNED_TO_S2", "OBSERVED", "VERIFICATION_SEALED"}:
        raise ApiError(409, "NEW_ROUND_NOT_ALLOWED", "已终止、完成或退回批次不能借换人清除历史质量结论")
    await assert_frozen_profile(db, previous)
    if not body.reason.strip():
        raise ApiError(422, "REASON_REQUIRED", "须记录完整新轮原因")
    if previous.workflow_kind == "OBSERVATION":
        if not body.annotator_a or not body.annotator_b or body.assignee_ids:
            raise ApiError(422, "DISTINCT_PEOPLE_REQUIRED", "观测新轮须指定完整A/B，不复用原人封存")
        users = [await annotator(db, body.annotator_a), await annotator(db, body.annotator_b)]
        if users[0].person_id == users[1].person_id:
            raise ApiError(422, "DISTINCT_PEOPLE_REQUIRED", "A/B必须为不同真实人员")
        seats = [(users[0], "A"), (users[1], "B")]
    else:
        if not body.assignee_ids or body.annotator_a or body.annotator_b:
            raise ApiError(422, "ANNOTATOR_REQUIRED", "主核实新轮须指定全量核实人员")
        users = [await annotator(db, value) for value in dict.fromkeys(body.assignee_ids)]
        seats = [(user, "V") for user in users]
    units = list((await db.scalars(select(V13Unit).where(V13Unit.import_id == previous.import_id,
        V13Unit.unit_id.in_(previous.selected_ids)).order_by(V13Unit.unit_id))).all())
    if await db.scalar(select(V13Revision.id).where(V13Revision.unit_index_id.in_([unit.id for unit in units]),
            V13Revision.status == "PENDING").limit(1)):
        raise ApiError(409, "REVISION_PENDING", "先处理当前候选复验，再切换主核实签名轮次")
    for user in sorted(users, key=lambda value: value.person_id):
        await assert_assignment_compatible(db, user, units, previous.workflow_kind)
    active = list((await db.scalars(select(V13Batch).where(V13Batch.import_id == previous.import_id,
        V13Batch.dataset == previous.dataset, V13Batch.workflow_kind == previous.workflow_kind,
        V13Batch.state != "SUPERSEDED"))).all())
    replacing_expansion = bool(previous.parent_id and previous.sample_ledger.get("purpose") != "REPLACEMENT")
    if replacing_expansion:
        active = [row for row in active if row.id == previous.id]
    # Replacing a complete scope also terminates unfinished expansion branches;
    # no partial old/new people pairs are carried into the fresh round.
    if any(row.state == "RETURNED_TO_S2" for row in active):
        raise ApiError(409, "RETURNED_TO_S2", "失败范围必须退S2，不能换轮洗掉原κ")
    last_round = await db.scalar(select(func.max(V13Batch.round)).where(V13Batch.import_id == previous.import_id,
        V13Batch.dataset == previous.dataset, V13Batch.workflow_kind == previous.workflow_kind))
    store = store_for(request)
    revision_map = ({unit.unit_id: unit.final_revision or unit.content_revision for unit in units}
                    if previous.workflow_kind == "VERIFICATION" else previous.sample_ledger.get("revision_map", {}))
    fresh = V13Batch(import_id=previous.import_id, dataset=previous.dataset,
        workflow_kind=previous.workflow_kind, selected_ids=list(previous.selected_ids),
        sample_ledger={**previous.sample_ledger, "purpose": "EXPANSION" if replacing_expansion else "REPLACEMENT",
                       "replaces_batch_id": previous.id,
                       "revision_map": revision_map},
        profile_version=previous.profile_version, manual_version=previous.manual_version,
        frozen_hash=frozen_hash(units, previous.profile_version, previous.manual_version, revision_map),
        creator_id=actor.id, round=(last_round or 0) + 1,
        parent_id=previous.id)
    db.add(fresh)
    await db.flush()
    old_tasks = (await db.scalars(select(V13Assignment).where(V13Assignment.batch_id.in_([row.id for row in active]),
        V13Assignment.active.is_(True)))).all()
    for old_task in old_tasks:
        old_task.active = False
    for old_batch in active:
        old_batch.state = "SUPERSEDED"
    for index, unit in enumerate(units):
        material_ref, gold_ref = unit.material_ref, unit.gold_ref
        if previous.workflow_kind == "VERIFICATION" and unit.final_ref:
            material, gold = split_unit(store.read_json(unit.final_ref))
            material_ref, gold_ref = store.put_json(material), store.put_json(gold)
        for user, seat in seats if previous.workflow_kind == "OBSERVATION" else [seats[index % len(seats)]]:
            db.add(V13Assignment(batch_id=fresh.id, unit_index_id=unit.id, user_id=user.id, seat=seat,
                content_revision=revision_map.get(unit.unit_id, unit.content_revision),
                material_ref=material_ref, gold_ref=gold_ref))
    db.add(V13QualityAction(batch_id=fresh.id, kind="NEW_ROUND", actor_id=actor.id,
        record_ref=store_for(request).put_json({"reason": body.reason, "previous_batch_id": previous.id,
                                               "new_batch_id": fresh.id, "scope": list(previous.selected_ids)}),
        related_batch_id=previous.id))
    audit(db, request, actor.id, "V13_NEW_ROUND", fresh.id, {"previous_batch_id": previous.id})
    await db.flush()
    return await batch_view(db, fresh, store_for(request))


@router.get("/me/tasks")
async def tasks(actor: Actor, db: Db, workflow_kind: Literal["VERIFICATION", "OBSERVATION"] | None = None,
                 offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    query = select(V13Assignment, V13Batch, V13Unit).join(V13Batch, V13Batch.id == V13Assignment.batch_id).join(
        V13Unit, V13Unit.id == V13Assignment.unit_index_id).where(V13Assignment.user_id == actor.id, V13Assignment.active.is_(True))
    if workflow_kind:
        query = query.where(V13Batch.workflow_kind == workflow_kind)
    rows = (await db.execute(query.order_by(V13Assignment.created_at, V13Assignment.id).offset(offset).limit(limit))).all()
    return {"items": [await task_view(db, assignment, batch, unit) for assignment, batch, unit in rows],
            "total": await db.scalar(select(func.count()).select_from(query.subquery()))}


@router.get("/assignments/{assignment_id}")
async def task_detail(assignment_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    assignment, batch, unit = await own_task(db, actor, assignment_id)
    store = store_for(request)
    result = await task_view(db, assignment, batch, unit)
    result["material"] = store.read_json(assignment.material_ref)
    result["draft"] = await read_draft(db, store, assignment.id, assignment.phase)
    blind = await db.scalar(select(V13Submission).where(V13Submission.assignment_id == assignment.id, V13Submission.phase == "BLIND"))
    own = await db.scalar(select(V13Submission).where(V13Submission.assignment_id == assignment.id, V13Submission.phase == assignment.phase))
    result["own_submission"] = store.read_json(own.payload_ref) if own else None
    if assignment.phase == "REVIEW":
        if not blind:
            raise ApiError(409, "INDEPENDENT_RECORD_MISSING", "独立封存引用缺失，不能展示草案")
        await assert_review_visible(db, actor, unit)
        review_material = store.read_json(assignment.gold_ref)
        result["gold"] = review_material.get("gold", {})
        result["material"].update({key: value for key, value in review_material.items() if key != "gold"})
        result["points"] = [{"point_key": f"P{i+1:03d}", "text": value} for i, value in enumerate(result["gold"].get("answer_points", []))]
        result["own_blind"] = store.read_json(blind.payload_ref)
        mark_exposure(db, actor, unit, assignment.id, "REVIEW_READ")
    return result


@router.patch("/assignments/{assignment_id}/draft")
async def save_draft(assignment_id: str, body: DraftInput, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    assignment, batch, unit = await own_task(db, actor, assignment_id, lock=True)
    await assert_task_writable(db, assignment, batch, unit, body.phase)
    draft = await db.scalar(select(V13Draft).where(V13Draft.assignment_id == assignment.id, V13Draft.phase == body.phase))
    if (draft.version if draft else 0) != body.version:
        raise ApiError(409, "DRAFT_VERSION_CONFLICT", "服务器草稿版本已变化，请刷新后合并")
    ref = store_for(request).put_json(body.payload)
    if draft:
        draft.payload_ref, draft.version = ref, draft.version + 1
    else:
        draft = V13Draft(assignment_id=assignment.id, phase=body.phase, version=1, payload_ref=ref)
        db.add(draft)
    return {"version": draft.version, "payload": body.payload}


@router.post("/assignments/{assignment_id}/submit")
async def submit(assignment_id: str, body: SubmitInput, request: Request, actor: Actor, db: Db,
                 idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=160)) -> Any:
    assignment, batch, unit = await own_task(db, actor, assignment_id, lock=True)
    store = store_for(request)
    payload_hash = canonical_sha256(body.payload)
    old = await db.scalar(select(V13Submission).where(V13Submission.assignment_id == assignment.id, V13Submission.phase == body.phase))
    if old:
        if old.idempotency_key != idempotency_key or old.payload_hash != payload_hash:
            raise ApiError(409, "SEALED_SUBMISSION_CONFLICT", "正式封存不可覆盖；相同幂等键须提交相同内容")
        return {"id": old.id, "payload_hash": old.payload_hash, "status": "SEALED"}
    if not assignment.active:
        late = await db.scalar(select(V13LateSubmission).where(V13LateSubmission.assignment_id == assignment.id,
                                    V13LateSubmission.idempotency_key == idempotency_key))
        if late and late.payload_hash != payload_hash:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键内容不同")
        if not late:
            late = V13LateSubmission(assignment_id=assignment.id, actor_id=actor.id,
                                     payload_ref=store.put_json(body.payload), payload_hash=payload_hash,
                                     idempotency_key=idempotency_key)
            db.add(late)
            await db.flush()
        return JSONResponse(status_code=409, content={"error_code": "ASSIGNMENT_REPLACED", "history_id": late.id,
                                                       "message": "迟到提交已作为无效历史保存，不计当前完成", "request_id": request.state.request_id})
    await assert_task_writable(db, assignment, batch, unit, body.phase)
    if body.content_revision != assignment.content_revision or body.profile_version != batch.profile_version:
        raise ApiError(409, "FROZEN_VERSION_CONFLICT", "提交内容或规则版本与冻结任务不符")
    if body.phase == "BLIND":
        await assert_unexposed(db, actor, [unit])
        if not isinstance(body.payload.get("answer"), str) or not body.payload["answer"].strip() or not isinstance(body.payload.get("reason"), str) or not body.payload["reason"].strip():
            raise ApiError(422, "INDEPENDENT_ANSWER_REQUIRED", "独立判断和依据均为必填")
        if set(body.payload) - {"answer", "reason", "extraction"}:
            raise ApiError(422, "INDEPENDENT_PAYLOAD_INVALID", "独立阶段不能提交草案复核字段")
    else:
        await assert_review_visible(db, actor, unit)
        frozen_unit = {**store.read_json(assignment.material_ref), **store.read_json(assignment.gold_ref)}
        domain.validate_review(frozen_unit, body.payload)
        if body.payload.get("workflow_kind") != batch.workflow_kind:
            raise ApiError(422, "WORKFLOW_KIND_MISMATCH", "主核实与观测记录不能互相冒用")
    sealed = V13Submission(assignment_id=assignment.id, phase=body.phase,
                            payload_ref=store.put_json(body.payload), payload_hash=payload_hash,
                            idempotency_key=idempotency_key)
    db.add(sealed)
    assignment.status = "SEALED"
    await db.flush()
    if body.phase == "BLIND" and batch.workflow_kind == "VERIFICATION":
        await main_release(db, batch)
    if body.phase == "REVIEW" and batch.workflow_kind == "VERIFICATION":
        await verification_record(db, store, unit, actor, assignment, body.payload, assignment.content_revision)
        all_tasks = (await db.scalars(select(V13Assignment).where(V13Assignment.batch_id == batch.id, V13Assignment.active.is_(True)))).all()
        if all(row.phase == "REVIEW" and row.status == "SEALED" for row in all_tasks):
            batch.state = "VERIFICATION_SEALED"
    audit(db, request, actor.id, "V13_" + body.phase + "_SEALED", sealed.id, {"payload_hash": payload_hash, "workflow_kind": batch.workflow_kind})
    return {"id": sealed.id, "payload_hash": payload_hash, "status": "SEALED"}


@router.post("/observation-batches/{batch_id}/release-review")
async def release_review(batch_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await get_batch(db, batch_id, lock=True)
    await business_access(db, actor, batch.import_id)
    await assert_frozen_profile(db, batch)
    if batch.workflow_kind != "OBSERVATION":
        raise ApiError(422, "OBSERVATION_REQUIRED", "统一屏障仅属于观测支路")
    if batch.state == "REVIEW_OPEN":
        return await batch_view(db, batch, store_for(request))
    if batch.state != "BLIND_OPEN":
        raise ApiError(409, "PHASE_CONFLICT", "当前观测轮不能释放复核")
    rows = (await db.scalars(select(V13Assignment).where(V13Assignment.batch_id == batch.id, V13Assignment.active.is_(True)))).all()
    sealed = set((await db.scalars(select(V13Submission.assignment_id).where(V13Submission.assignment_id.in_([row.id for row in rows]), V13Submission.phase == "BLIND"))).all())
    if not rows or len(rows) != len(batch.selected_ids) * 2 or any(row.id not in sealed for row in rows):
        raise ApiError(409, "OBSERVATION_BARRIER_INCOMPLETE", "本观测批所有A/B独立封存后才能统一复核")
    for row in rows:
        unit = await db.get(V13Unit, row.unit_index_id)
        if unit and await db.scalar(select(V13Issue.id).where(V13Issue.unit_index_id == unit.id, V13Issue.status == "OPEN").limit(1)):
            raise ApiError(409, "MATERIAL_BLOCKED", "观测材料工单未解决")
        row.phase, row.status = "REVIEW", "OPEN"
    batch.state = "REVIEW_OPEN"
    audit(db, request, actor.id, "V13_OBSERVATION_RELEASED", batch.id)
    return await batch_view(db, batch, store_for(request))


@router.post("/observation-batches/{batch_id}/observe")
async def observe(batch_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await get_batch(db, batch_id, lock=True)
    await business_access(db, actor, batch.import_id)
    await assert_frozen_profile(db, batch)
    store = store_for(request)
    if batch.quality_ref:
        existing: dict[str, Any] = store.read_json(batch.quality_ref)
        return existing
    if batch.workflow_kind != "OBSERVATION" or batch.state != "REVIEW_OPEN":
        raise ApiError(409, "OBSERVATION_NOT_READY", "观测复核尚未开放或当前轮不可统计")
    rows = (await db.scalars(select(V13Assignment).where(V13Assignment.batch_id == batch.id, V13Assignment.active.is_(True)))).all()
    submissions = (await db.scalars(select(V13Submission).where(V13Submission.assignment_id.in_([row.id for row in rows]), V13Submission.phase == "REVIEW"))).all()
    by_assignment = {row.assignment_id: row for row in submissions}
    if len(rows) != 2 * len(batch.selected_ids) or len(submissions) != len(rows):
        raise ApiError(409, "OBSERVATION_PAIRS_INCOMPLETE", "全部同版本A/B复核完成后才生成正式原始观测")
    a: list[str] = []
    b: list[str] = []
    pair_records = []
    for unit_id in batch.selected_ids:
        unit = await db.scalar(select(V13Unit).where(V13Unit.import_id == batch.import_id, V13Unit.unit_id == unit_id))
        if unit is None:
            raise ApiError(409, "CONTENT_MISSING", "冻结单元缺失")
        pair = sorted([row for row in rows if row.unit_index_id == unit.id], key=lambda row: row.seat)
        if len(pair) != 2 or pair[0].content_revision != pair[1].content_revision:
            raise ApiError(409, "OBSERVATION_REVISION_MISMATCH", "配对版本或席位不完整")
        values = [store.read_json(by_assignment[row.id].payload_ref) for row in pair]
        original = store.read_json(unit.source_ref)
        keys = [f"P{i+1:03d}" for i in range(len(original.get("gold", {}).get("answer_points", [])))]
        a.extend(values[0].get("point_labels", {}).get(key, "MISSING") for key in keys)
        b.extend(values[1].get("point_labels", {}).get(key, "MISSING") for key in keys)
        pair_records.append({"unit_id": unit_id, "content_revision": pair[0].content_revision,
                             "annotator_a": pair[0].user_id, "annotator_b": pair[1].user_id,
                             "submission_a": by_assignment[pair[0].id].payload_ref,
                             "submission_b": by_assignment[pair[1].id].payload_ref,
                             "point_keys": keys})
    result = domain.observation_result(a, b)
    if batch.dataset == "QA-D6" or batch.dataset.startswith("SEC-"):
        result = {"kappa": None, "po": None, "pe": None, "n": 0, "action": "UNDEFINED", "reason": "SPECIALIZED_STATISTICS_NOT_CONFIRMED"}
    result.update({"batch_id": batch.id, "pair_count": len(pair_records), "pairs": pair_records,
                   "vectors": {"a": a, "b": b}, "sampled_at": batch.created_at.isoformat(),
                   "observed_at": now().isoformat(), "frozen_hash": batch.frozen_hash,
                   "manual_version": batch.manual_version, "profile_version": batch.profile_version})
    batch.quality_ref, batch.state = store.put_json(result), "OBSERVED"
    if result["action"] == "RETURN_TO_S2":
        imported = await get_import(db, batch.import_id, lock=True)
        imported.status = "RETURNED_TO_S2"
        batch.state = "RETURNED_TO_S2"
        db.add(V13QualityAction(batch_id=batch.id, kind="RETURN_TO_S2", actor_id=actor.id,
                                record_ref=store.put_json({"reason": "κ<0.6，整批退S2并修订指南", "original_quality_ref": batch.quality_ref})))
    audit(db, request, actor.id, "V13_QUALITY_OBSERVED", batch.id, {"quality_hash": batch.quality_ref["sha256"], "action": result["action"]})
    return result


@router.post("/quality-actions", status_code=201)
async def quality_action(body: QualityActionCreate, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    batch = await get_batch(db, body.batch_id, lock=True)
    await get_import(db, batch.import_id, lock=True)
    await business_access(db, actor, batch.import_id)
    if body.kind in {"CALIBRATION", "EXPAND", "DISAGREEMENT_REVIEW"} and not batch.quality_ref:
        raise ApiError(409, "ORIGINAL_OBSERVATION_REQUIRED", "质量动作必须关联已封存的原始观测")
    if body.related_batch_id:
        related = await get_batch(db, body.related_batch_id)
        if related.import_id != batch.import_id and body.kind != "S2_ACK":
            raise ApiError(422, "RELATED_BATCH_MISMATCH", "质量动作关联范围不一致")
    if body.kind == "S2_ACK" and not body.evidence:
        raise ApiError(422, "RECEIPT_EVIDENCE_REQUIRED", "须提供真实S2接收与新来源关联证据")
    if body.kind == "DISAGREEMENT_REVIEW":
        unit = await db.get(V13Unit, body.evidence.get("unit_index_id"))
        if (unit is None or unit.import_id != batch.import_id or unit.unit_id not in batch.selected_ids
                or body.evidence.get("content_revision") != unit.content_revision
                or body.evidence.get("resolution") not in {"KEEP_SOURCE", "REVISION_REQUIRED"}
                or not body.reason.strip()
                or not (set(body.evidence) - {"unit_index_id", "content_revision", "resolution"})):
            raise ApiError(422, "DISAGREEMENT_EVIDENCE_REQUIRED", "须绑定观测原版本、结论及实际核查证据，不能仅关闭分歧")
        await lock_operator_exposure(db, actor, batch.import_id)
        mark_exposure(db, actor, unit, None, "DISAGREEMENT_REVIEW")
    if body.kind == "RETURN_TO_S2":
        imported = await get_import(db, batch.import_id, lock=True)
        imported.status, batch.state = "RETURNED_TO_S2", "RETURNED_TO_S2"
    record = V13QualityAction(batch_id=batch.id, kind=body.kind, actor_id=actor.id,
                              record_ref=store_for(request).put_json({**body.model_dump(), "recorded_at": now().isoformat()}),
                              related_batch_id=body.related_batch_id)
    db.add(record)
    await db.flush()
    audit(db, request, actor.id, "V13_QUALITY_ACTION", record.id, {"kind": body.kind, "record_hash": record.record_ref["sha256"]})
    return {"id": record.id, "kind": record.kind, "batch_id": record.batch_id,
            "original_batch_remains_returned": True if body.kind == "S2_ACK" else None}


@router.get("/quality-actions")
async def quality_actions(request: Request, actor: Actor, db: Db, batch_id: str,
                           offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    batch = await get_batch(db, batch_id)
    await business_access(db, actor, batch.import_id)
    await lock_operator_exposure(db, actor, batch.import_id)
    rows = (await db.scalars(select(V13QualityAction).where(V13QualityAction.batch_id == batch.id)
                             .order_by(V13QualityAction.created_at).offset(offset).limit(limit))).all()
    if rows:
        for unit in (await db.scalars(select(V13Unit).where(V13Unit.import_id == batch.import_id,
                V13Unit.unit_id.in_(batch.selected_ids)))).all():
            mark_exposure(db, actor, unit, None, "QUALITY_ACTIONS_READ")
    return {"items": [{"id": row.id, "kind": row.kind, "batch_id": row.batch_id,
                       "actor_id": row.actor_id, "record": store_for(request).read_json(row.record_ref)} for row in rows],
            "total": await db.scalar(select(func.count()).select_from(V13QualityAction).where(V13QualityAction.batch_id == batch.id))}


@router.post("/assignments/{assignment_id}/replace", status_code=201)
async def replace(assignment_id: str, body: ReplacementInput, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    original = await db.get(V13Assignment, assignment_id)
    if original is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    batch = await get_batch(db, original.batch_id, lock=True)
    await get_import(db, batch.import_id, lock=True)
    await business_access(db, actor, batch.import_id)
    if not original.active:
        raise ApiError(409, "ASSIGNMENT_REPLACED", "原任务已补派")
    if batch.state in {"OBSERVED", "RETURNED_TO_S2", "CANCELLED", "SUPERSEDED"}:
        raise ApiError(409, "BATCH_CLOSED", "封存或退回批次不能补派")
    if original.phase != "BLIND":
        raise ApiError(409, "REVIEW_NEW_ROUND_REQUIRED", "已见草案后须保留原轮并用新独立人员启动完整新轮")
    target = await annotator(db, body.user_id)
    rows = [original]
    if batch.workflow_kind == "OBSERVATION":
        rows = list((await db.scalars(select(V13Assignment).where(V13Assignment.batch_id == batch.id,
                    V13Assignment.seat == original.seat, V13Assignment.active.is_(True)))).all())
        other_people = (await db.scalars(select(User.person_id).join(V13Assignment, V13Assignment.user_id == User.id).where(
            V13Assignment.batch_id == batch.id, V13Assignment.seat != original.seat, V13Assignment.active.is_(True)))).all()
        if target.person_id in other_people:
            raise ApiError(422, "DISTINCT_PEOPLE_REQUIRED", "观测替补不能占用另一个席位的真实人员")
    units = list((await db.scalars(select(V13Unit).where(V13Unit.id.in_([row.unit_index_id for row in rows])))).all())
    await assert_assignment_compatible(db, target, units, batch.workflow_kind)
    for row in rows:
        row.active = False
    await db.flush()
    replacements = []
    for row in rows:
        replacement = V13Assignment(batch_id=batch.id, unit_index_id=row.unit_index_id,
                                     user_id=target.id, seat=row.seat, content_revision=row.content_revision,
                                     material_ref=row.material_ref, gold_ref=row.gold_ref)
        db.add(replacement)
        await db.flush()
        replacements.append(replacement.id)
    db.add(V13QualityAction(batch_id=batch.id, kind="REPLACEMENT", actor_id=actor.id,
                            record_ref=store_for(request).put_json({"reason": body.reason,
                                "previous_ids": [row.id for row in rows], "replacement_ids": replacements})))
    return {"assignment_ids": replacements, "scope": "SEAT" if batch.workflow_kind == "OBSERVATION" else "TASK"}


@router.post("/issues", status_code=201)
async def create_issue(body: IssueCreate, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    unit = await db.get(V13Unit, body.unit_index_id)
    if unit is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await get_import(db, unit.import_id, lock=True)
    own = await db.scalar(select(V13Assignment.id).where(V13Assignment.unit_index_id == unit.id,
                               V13Assignment.user_id == actor.id, V13Assignment.active.is_(True)).limit(1))
    if not own:
        await business_access(db, actor, unit.import_id)
        require_role(actor, "lead")
    issue = V13Issue(import_id=unit.import_id, unit_index_id=unit.id, actor_id=actor.id,
                     record_ref=store_for(request).put_json({"reason": body.reason, "created_at": now().isoformat()}))
    db.add(issue)
    await db.flush()
    audit(db, request, actor.id, "V13_ISSUE_OPENED", issue.id)
    return {"id": issue.id, "status": issue.status}


@router.get("/issues")
async def list_issues(request: Request, actor: Actor, db: Db,
                     offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "lead", "auditor", "arbitrator", "annotator")
    visible = V13Issue.actor_id == actor.id
    if set(actor.roles).intersection({"lead", "auditor", "arbitrator"}):
        hidden = await hidden_import_ids(db, actor)
        visible = or_(visible, V13Issue.import_id.notin_(hidden))
    query = select(V13Issue).where(visible)
    rows = (await db.scalars(query.order_by(V13Issue.created_at.desc()).offset(offset).limit(limit))).all()
    store = store_for(request)
    return {"items": [{"id": row.id, "import_id": row.import_id, "unit_index_id": row.unit_index_id,
        "actor_id": row.actor_id, "status": row.status, "reason": store.read_json(row.record_ref).get("reason"),
        "resolution": store.read_json(row.resolution_ref) if row.resolution_ref else None} for row in rows],
        "total": await db.scalar(select(func.count()).select_from(query.subquery()))}


@router.post("/issues/{issue_id}/resolve")
async def resolve_issue(issue_id: str, body: IssueResolve, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    issue = await db.get(V13Issue, issue_id)
    if issue is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    require_role(actor, "lead")
    await get_import(db, issue.import_id, lock=True)
    await db.refresh(issue)
    await business_access(db, actor, issue.import_id)
    if issue.actor_id == actor.id:
        raise ApiError(403, "INDEPENDENT_RESOLVER_REQUIRED", "材料问题须由不同人员核查解决")
    if issue.status != "OPEN":
        raise ApiError(409, "ISSUE_ALREADY_RESOLVED", "该问题已有封存结论")
    issue.status, issue.resolver_id = "RESOLVED", actor.id
    issue.resolution_ref = store_for(request).put_json({**body.model_dump(), "resolved_at": now().isoformat()})
    audit(db, request, actor.id, "V13_ISSUE_RESOLVED", issue.id)
    return {"id": issue.id, "status": issue.status}


@router.post("/revisions", status_code=201)
async def propose_revision(body: RevisionCreate, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead", "arbitrator")
    unit = await db.get(V13Unit, body.unit_index_id)
    if unit is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await business_access(db, actor, unit.import_id)
    imported = await get_import(db, unit.import_id, lock=True)
    if imported.status == "RETURNED_TO_S2":
        raise ApiError(409, "RETURNED_TO_S2", "已退回原批不能通过金标修订恢复交接")
    primary = await require_primary_review(db, unit)
    if await db.scalar(select(V13Revision.id).where(V13Revision.unit_index_id == unit.id, V13Revision.status == "PENDING").limit(1)):
        raise ApiError(409, "REVISION_PENDING", "已有待复验候选，不能并行覆盖同一单元")
    verifier = await db.get(User, body.verifier_id)
    if verifier is None or not verifier.active or "verifier" not in verifier.roles or verifier.person_id == actor.person_id:
        raise ApiError(422, "INDEPENDENT_VERIFIER_REQUIRED", "须指定不同真实人员的独立复验员")
    previous_participant = await db.scalar(select(V13Assignment.id).where(V13Assignment.unit_index_id == unit.id,
                                        V13Assignment.user_id == verifier.id).limit(1))
    if previous_participant:
        raise ApiError(403, "INDEPENDENT_VERIFIER_REQUIRED", "当前核实/观测人员不能复验自己参与的实质修订")
    domain.validate_unit(body.candidate)
    candidate = domain.Unit.model_validate(body.candidate).model_dump(exclude_none=True)
    if candidate.get("unit_id") != unit.unit_id or candidate.get("dataset") != unit.dataset:
        raise ApiError(422, "REVISION_IDENTITY_CHANGED", "修订不能更改单元身份或数据集")
    store = store_for(request)
    source = store.read_json(unit.final_ref or unit.source_ref)
    if canonical_sha256(candidate) == canonical_sha256(source):
        raise ApiError(422, "REVISION_UNCHANGED", "相同内容不能冒充实质修订或补造核实记录")
    frozen_fields = {"contexts", "text", "chunk", "text_digest", "corpus_id", "schema_version", "difficulty",
                     "dataset", "track", "unit_id", "domain", "domains", "source_case_ids", "resolved_sources",
                     "source_composition", "evaluation_k", "pair_id", "paired_unit_id", "key_facts"}
    if any(candidate.get(field) != source.get(field) for field in frozen_fields):
        raise ApiError(422, "FROZEN_SOURCE_CHANGED", "原文改变须新S3来源，不能在金标修订中替换原文")
    record = V13Revision(unit_index_id=unit.id, proposer_id=actor.id, verifier_id=verifier.id,
                         candidate_ref=store.put_json(candidate),
                         record_ref=store.put_json({"reason": body.reason, "proposed_at": now().isoformat(),
                                                    "primary_assignment_id": primary.id}),
                         source_revision=unit.final_revision or unit.content_revision)
    db.add(record)
    await db.flush()
    mark_exposure(db, actor, unit, None, "REVISION_PROPOSED")
    audit(db, request, actor.id, "V13_REVISION_PROPOSED", record.id, {"candidate_hash": record.candidate_ref["sha256"]})
    return {"id": record.id, "status": record.status, "verifier_id": record.verifier_id}


@router.get("/revisions")
async def revisions(request: Request, actor: Actor, db: Db,
                    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "verifier", "lead", "auditor", "arbitrator")
    visible = V13Revision.verifier_id == actor.id
    if set(actor.roles).intersection({"lead", "auditor", "arbitrator"}):
        hidden = await hidden_import_ids(db, actor)
        eligible = select(V13Unit.id).where(V13Unit.import_id.notin_(hidden))
        visible = or_(visible, V13Revision.unit_index_id.in_(eligible))
    query = select(V13Revision).where(visible)
    rows = (await db.scalars(query.order_by(V13Revision.created_at.desc()).offset(offset).limit(limit))).all()
    store = store_for(request)
    result = []
    for row in rows:
        unit = await db.get(V13Unit, row.unit_index_id)
        if unit:
            mark_exposure(db, actor, unit, None, "REVISION_READ")
        result.append({"id": row.id, "unit_index_id": row.unit_index_id, "status": row.status, "verifier_id": row.verifier_id,
                       "candidate": store.read_json(row.candidate_ref), "proposal": store.read_json(row.record_ref)})
    return {"items": result, "total": await db.scalar(select(func.count()).select_from(query.subquery()))}


@router.get("/units/{unit_index_id}")
async def unit_candidate(unit_index_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    unit = await db.get(V13Unit, unit_index_id)
    if unit is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await business_access(db, actor, unit.import_id)
    mark_exposure(db, actor, unit, None, "CURRENT_CANDIDATE_READ")
    return {"unit_index_id": unit.id, "unit_id": unit.unit_id,
        "content_revision": unit.content_revision, "final_revision": unit.final_revision,
        "candidate": store_for(request).read_json(unit.final_ref or unit.source_ref)}


@router.post("/revisions/{revision_id}/verify")
async def verify_revision(revision_id: str, body: RevisionVerify, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "verifier")
    revision = await db.scalar(select(V13Revision).where(V13Revision.id == revision_id).with_for_update())
    if revision is None or revision.verifier_id != actor.id:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    if revision.status != "PENDING":
        raise ApiError(409, "REVISION_ALREADY_VERIFIED", "复验结论已封存")
    unit = await db.get(V13Unit, revision.unit_index_id)
    if unit is None:
        raise ApiError(409, "CONTENT_MISSING", "单元索引缺失")
    imported = await get_import(db, unit.import_id, lock=True)
    if imported.status == "RETURNED_TO_S2":
        raise ApiError(409, "RETURNED_TO_S2", "退回原批不能借复验标为通过")
    primary = await require_primary_review(db, unit)
    if actor.id == revision.proposer_id or await db.scalar(select(V13Assignment.id).where(
            V13Assignment.unit_index_id == unit.id, V13Assignment.user_id == actor.id).limit(1)):
        raise ApiError(403, "INDEPENDENT_VERIFIER_REQUIRED", "复验员不能核验本人提出或参与核实的单元")
    if await db.scalar(select(V13Issue.id).where(V13Issue.unit_index_id == unit.id, V13Issue.status == "OPEN").limit(1)):
        raise ApiError(409, "MATERIAL_BLOCKED", "材料工单未解决不能签复验结论")
    if revision.source_revision != (unit.final_revision or unit.content_revision):
        raise ApiError(409, "REVISION_CONFLICT", "候选基准已变化，须重新提出修订")
    store = store_for(request)
    proposal = store.read_json(revision.record_ref)
    if proposal.get("primary_assignment_id") != primary.id:
        raise ApiError(409, "PRIMARY_ROUND_CHANGED", "主核实轮次已变化，不能把旧复验挂到新人员签名")
    candidate = store.read_json(revision.candidate_ref)
    domain.validate_unit(candidate)
    if body.outcome == "PASS" and unit.dataset in {"QA-D6", "SEC-D2"}:
        raise ApiError(409, "CONTENT_VOCABULARY_UNCONFIRMED", "专项词表尚未提供并批准，不能签核实通过")
    revision.verification_ref = store.put_json({**body.model_dump(), "actor_id": actor.id,
                                              "verified_at": now().isoformat(), "candidate_ref": revision.candidate_ref})
    revision.status = body.outcome
    mark_exposure(db, actor, unit, None, "REVISION_VERIFIED")
    if body.outcome == "PASS":
        unit.final_ref, unit.final_revision = revision.candidate_ref, canonical_sha256(candidate)
        # This is an actual independently signed verification on the final revision,
        # separate from the immutable primary and observation submissions.
        await verification_record(db, store, unit, actor, None,
            {"verdict": "VERIFIED", "revision_id": revision.id, "verification_ref": revision.verification_ref,
             "primary_assignment_id": primary.id}, unit.final_revision)
    audit(db, request, actor.id, "V13_REVISION_VERIFIED", revision.id, {"outcome": body.outcome, "verification_hash": revision.verification_ref["sha256"]})
    return {"id": revision.id, "status": revision.status, "final_revision": unit.final_revision}
