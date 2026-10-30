"""Authenticated v2 exports, controlled downloads and separately attested delivery."""
from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import func, select

from ..db import lock_scope
from ..domain.contracts import canonical_sha256
from ..models import Job
from ..models_handoff_v13 import V13Delivery, V13Handoff
from ..models_v13 import V13Assignment, V13Batch, V13Import, V13Unit
from ..schemas import StrictModel
from ..security import Actor, ApiError, Db, require_role
from ..services.common import audit
from ..services.content_store import ContentStore
from ..services.handoffs_v13 import FILES_V2, verify_package
from ..services.jobs import enqueue

router = APIRouter()


class HandoffCreateV2(StrictModel):
    import_id: str


class DeliveryInputV2(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    snapshot_hash: str = Field(pattern="^[0-9a-f]{64}$")
    destination_ref: str = Field(pattern="^receiver:[A-Za-z0-9_.-]{1,150}$")
    evidence_ref: str = Field(pattern="^evidence:[A-Za-z0-9_.-]{1,150}$")
    evidence_sha256: str = Field(pattern="^[0-9a-f]{64}$")


async def _independent(db: Db, actor: Actor, import_id: str) -> V13Import:
    require_role(actor, "lead", "auditor")
    imported = await db.get(V13Import, import_id)
    if not imported:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    own = await db.scalar(select(V13Assignment.id).join(V13Batch).where(
        V13Batch.import_id == import_id, V13Assignment.user_id == actor.id).limit(1))
    if own:
        raise ApiError(403, "PARTICIPANT_RESTRICTED", "历史参作业人员不能读取受限交接材料")
    from ..services.workflow_v13 import business_access
    await business_access(db, actor, import_id)
    return imported


def _store(request: Request) -> ContentStore:
    return ContentStore(request.app.state.settings.data_dir / "controlled")


def _view(item: V13Handoff, store: ContentStore) -> dict[str, Any]:
    return {"id": item.id, "import_id": item.import_id, "status": item.status,
            "snapshot_hash": item.snapshot_hash, "manifest": store.read_json(item.manifest_ref),
            "mode": "demo", "external_alignment": "NOT_ALIGNED",
            "created_at": item.created_at.isoformat()}


@router.post("/handoffs", status_code=202)
async def create_handoff(body: HandoffCreateV2, request: Request, actor: Actor, db: Db) -> dict[str, str]:
    require_role(actor, "lead")
    imported = await _independent(db, actor, body.import_id)
    from ..services.workflow_v13 import current_verification_records, import_report
    await db.refresh(imported, with_for_update=True)
    report = await import_report(db, _store(request), imported)
    if imported.mode != "demo":
        raise ApiError(409, "EXTERNAL_CONTRACT_NOT_ALIGNED", "正式协议及适用规则尚未对齐")
    if not report["demo_ready"]:
        raise ApiError(409, "VERIFICATION_EVIDENCE_INCOMPLETE", "全量核实、观测或问题尚未完成")
    revisions = (await db.scalars(select(V13Unit).where(V13Unit.import_id == imported.id).order_by(V13Unit.id))).all()
    records = await current_verification_records(db, _store(request), revisions)
    from ..models_v13 import V13QualityAction
    actions = (await db.scalars(select(V13QualityAction).join(V13Batch, V13Batch.id == V13QualityAction.batch_id).where(V13Batch.import_id == imported.id).order_by(V13QualityAction.id))).all()
    batches = (await db.scalars(select(V13Batch).where(V13Batch.import_id == imported.id).order_by(V13Batch.id))).all()
    signature = canonical_sha256({"source": imported.content_hash, "report": report,
                                   "revisions": [(row.id, row.final_revision) for row in revisions],
                                   "verification_refs": sorted((key, record.record_ref) for key, record in records.items()),
                                   "action_refs": [(action.id, action.record_ref) for action in actions],
                                   "batch_scope": [(batch.id, batch.state, batch.frozen_hash, batch.quality_ref) for batch in batches]})
    job = await enqueue(db, "EXPORT_V13", "export-v13:" + signature, actor.id, {"import_id": imported.id})
    audit(db, request, actor.id, "V13_HANDOFF_REQUESTED", imported.id)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
async def job_detail(job_id: str, actor: Actor, db: Db) -> dict[str, Any]:
    row = await db.get(Job, job_id)
    if not row or row.creator_id != actor.id:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    return {"id": row.id, "kind": row.kind, "state": row.state, "attempts": row.attempts,
            "result": row.result, "error_code": row.error_code, "error_message": row.error_message}


@router.get("/handoffs")
async def list_handoffs(request: Request, actor: Actor, db: Db,
                       offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    participated = select(V13Batch.import_id).join(V13Assignment).where(V13Assignment.user_id == actor.id)
    query = select(V13Handoff).where(V13Handoff.import_id.not_in(participated))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(V13Handoff.created_at.desc()).offset(offset).limit(limit))).all()
    return {"items": [_view(row, _store(request)) for row in rows], "total": total or 0}


@router.get("/handoffs/{handoff_id}")
async def handoff_detail(handoff_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    row = await db.get(V13Handoff, handoff_id)
    if not row:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await _independent(db, actor, row.import_id)
    return _view(row, _store(request))


@router.get("/handoffs/{handoff_id}/files/{filename}")
async def download(handoff_id: str, filename: str, request: Request, actor: Actor, db: Db) -> FileResponse:
    row = await db.get(V13Handoff, handoff_id)
    if not row or filename not in FILES_V2 | {"s4_handoff_manifest.json"}:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await _independent(db, actor, row.import_id)
    from ..services.workflow_v13 import assert_review_visible, mark_exposure
    units = (await db.scalars(select(V13Unit).where(V13Unit.import_id == row.import_id))).all()
    for unit in units:
        await assert_review_visible(db, actor, unit)
    manifest = _store(request).read_json(row.manifest_ref)
    directory = request.app.state.settings.data_dir / "exports-v13" / row.id
    try:
        verify_package(directory, manifest)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ApiError(409, "V13_PACKAGE_INVALID", "交接文件摘要或集合核对失败") from exc
    # Reading an export is a sensitive source-family exposure, including for a
    # lead who is eligible to annotate a future source-related batch.
    for unit in units:
        mark_exposure(db, actor, unit, None, "HANDOFF_DOWNLOAD")
    audit(db, request, actor.id, "V13_HANDOFF_DOWNLOADED", row.id, {"filename": filename})
    return FileResponse(directory / filename, filename=filename)


@router.post("/handoffs/{handoff_id}/sent")
async def sent(handoff_id: str, body: DeliveryInputV2, request: Request, actor: Actor, db: Db) -> dict[str, str]:
    require_role(actor, "lead")
    await lock_scope(db, "v13-delivery:" + handoff_id)
    row = await db.get(V13Handoff, handoff_id)
    if not row:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await _independent(db, actor, row.import_id)
    if row.snapshot_hash != body.snapshot_hash:
        raise ApiError(409, "SNAPSHOT_MISMATCH", "发送证据必须绑定冻结快照")
    try:
        verify_package(request.app.state.settings.data_dir / "exports-v13" / row.id,
                       _store(request).read_json(row.manifest_ref))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ApiError(409, "V13_PACKAGE_INVALID", "发送前必须核对完整冻结过程包") from exc
    signature = canonical_sha256(body.model_dump())
    existing = await db.scalar(select(V13Delivery).where(V13Delivery.handoff_id == row.id,
                                        V13Delivery.idempotency_key == body.idempotency_key))
    if existing:
        if existing.payload_hash != signature:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "相同业务键不能登记不同证据")
        return {"sent_event_id": existing.id, "status": "HANDOFF_SENT_DEMO"}
    imported = await db.scalar(select(V13Import).where(V13Import.id == row.import_id).with_for_update())
    if not imported:
        raise ApiError(404, "NOT_FOUND", "来源不存在")
    from ..services.workflow_v13 import import_report
    report = await import_report(db, _store(request), imported)
    if not report["demo_ready"]:
        raise ApiError(409, "DELIVERY_SCOPE_NO_LONGER_READY", "存在退回、未决问题或未完成核实，不能登记新的发送")
    directory = request.app.state.settings.data_dir / "exports-v13" / row.id
    import json
    packaged_units = [json.loads(line) for line in (directory / "units_for_s5.jsonl").read_bytes().splitlines()]
    current_units = (await db.scalars(select(V13Unit).where(V13Unit.import_id == row.import_id))).all()
    original = {unit["unit_id"]: unit["content_revision"] for unit in packaged_units}
    current = {unit.unit_id: unit.final_revision or unit.content_revision for unit in current_units}
    packaged_report = json.loads((directory / "s4_report.json").read_bytes())
    if original != current or any(canonical_sha256(sorted(packaged_report.get(key, []), key=canonical_sha256)) != canonical_sha256(sorted(report.get(key, []), key=canonical_sha256)) for key in ("quality", "expansions")):
        raise ApiError(409, "DELIVERY_SNAPSHOT_SUPERSEDED", "单元修订或观测已变化，请重新导出后交付")
    from ..models_v13 import V13QualityAction
    action_rows = (await db.scalars(select(V13QualityAction).join(V13Batch, V13Batch.id == V13QualityAction.batch_id).where(V13Batch.import_id == row.import_id))).all()
    current_actions = [_store(request).read_json(action.record_ref) for action in action_rows]
    packaged_actions = [json.loads(line) for line in (directory / "quality_actions.jsonl").read_bytes().splitlines()]
    if sorted(map(canonical_sha256, current_actions)) != sorted(map(canonical_sha256, packaged_actions)):
        raise ApiError(409, "DELIVERY_SNAPSHOT_SUPERSEDED", "质量动作已变化，请重新导出后交付")
    evidence = V13Delivery(handoff_id=row.id, actor_id=actor.id,
                           idempotency_key=body.idempotency_key, payload_hash=signature,
                           evidence_ref=_store(request).put_json(body.model_dump()))
    db.add(evidence)
    row.status = "HANDOFF_SENT_DEMO"
    await db.flush()
    audit(db, request, actor.id, "V13_HANDOFF_SENT_DEMO", row.id, {"event_id": evidence.id})
    return {"sent_event_id": evidence.id, "status": row.status}


@router.post("/handoffs/{handoff_id}/receipts")
async def receipt(handoff_id: str, request: Request,
                  x_s4_receipt_token: str | None = Header(default=None)) -> None:
    expected = request.app.state.settings.receipt_token
    if not expected or not hmac.compare_digest(expected, x_s4_receipt_token or ""):
        raise ApiError(403, "RECEIPT_SCOPE_REQUIRED", "回执必须由授权接收方登记")
    raise ApiError(409, "EXTERNAL_CONTRACT_NOT_ALIGNED", "新协议尚未正式联调，不登记模拟的S5接收")
