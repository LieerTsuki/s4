"""Controlled snapshot downloads, authenticated receipts and minimal audit visibility."""
import hmac
import json
import re
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import FileResponse
from pydantic import Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..domain.contracts import canonical_sha256
from ..models import AnnotationBatch, AuditEvent, Handoff, HandoffSent
from ..schemas import HandoffInput, ReceiptInput, StrictModel
from ..security import Actor, ApiError, Db, digest, require_role
from ..services.common import audit, mark_import_exposure, prohibit_participant_import, source
from ..services.handoffs import FILES, verify_snapshot
from ..services.jobs import enqueue
from ..services.operations import independent_operator

router = APIRouter()


class DeliveryEvidence(StrictModel):
    kind: str = Field(pattern="^(manual_delivery|controlled_transfer)$")
    reference: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")

    @field_validator("reference")
    @classmethod
    def controlled_reference(cls, value: str) -> str:
        if not re.fullmatch(r"evidence:[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", value):
            raise ValueError("需要受控证据引用")
        return value


class SentInput(StrictModel):
    snapshot_hash: str = Field(pattern="^[0-9a-f]{64}$")
    destination_ref: str = Field(pattern="^(manual|receiver):[A-Za-z0-9][A-Za-z0-9_.-]{0,150}$")
    evidence: DeliveryEvidence
    idempotency_key: str = Field(min_length=1, max_length=160)


class ReceiptEnvelope(ReceiptInput):
    """Legacy demo requests reach the alignment gate; formal receipts need all bindings."""
    sent_event_id: str | None = Field(default=None, min_length=1, max_length=36)
    destination_ref: str | None = Field(default=None, pattern="^(manual|receiver):[A-Za-z0-9][A-Za-z0-9_.-]{0,150}$")
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)


def validate_receipt_binding(item: Handoff, event: HandoffSent | None, body: ReceiptEnvelope) -> None:
    """Validate metadata only; this never enables an external contract or acceptance."""
    if not body.sent_event_id or not body.destination_ref or not body.idempotency_key or not body.idempotency_key.strip():
        raise ApiError(422, "RECEIPT_BINDING_REQUIRED", "正式回执须绑定发送事件、目标与独立幂等键")
    if item.status != "HANDOFF_SENT":
        raise ApiError(409, "HANDOFF_NOT_SENT", "未登记实际发送证据，不能接收回执")
    if not event or event.id != body.sent_event_id or event.handoff_id != item.id or event.mode != item.mode:
        raise ApiError(409, "SENT_EVENT_MISMATCH", "回执发送事件与本交接不一致")
    if event.snapshot_hash != item.snapshot_hash or body.snapshot_hash != item.snapshot_hash:
        raise ApiError(409, "SNAPSHOT_MISMATCH", "回执与已发送冻结快照不一致")
    if event.destination_ref != body.destination_ref:
        raise ApiError(409, "RECEIPT_DESTINATION_MISMATCH", "回执目标与实际发送事件不一致")


def handoff_view(item: Handoff) -> dict[str, Any]:
    return {"id": item.id, "import_id": item.import_id, "mode": item.mode, "status": item.status,
            "manifest": item.manifest, "blocked_reasons": item.blocked_reasons,
            "external_status": item.external_status, "snapshot_hash": item.snapshot_hash,
            "created_at": item.created_at.isoformat()}


@router.post("/handoffs", status_code=202)
async def create_handoff(body: HandoffInput, request: Request, actor: Actor, db: Db) -> dict[str, str]:
    require_role(actor, "lead")
    imported = await source(db, body.import_id)
    await prohibit_participant_import(db, actor, imported.id)
    rows = (await db.scalars(select(AnnotationBatch).where(AnnotationBatch.import_id == imported.id, AnnotationBatch.state != "SUPERSEDED"))).all()
    key = "handoff:" + digest(imported.content_hash + ":" + ":".join(sorted(row.id for row in rows)))
    job = await enqueue(db, "EXPORT", key, actor.id, {"import_id": imported.id})
    audit(db, request, actor.id, "HANDOFF_REQUESTED", imported.id)
    return {"job_id": job.id}


@router.get("/handoffs")
async def handoffs(actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    rows = (await db.scalars(select(Handoff).order_by(Handoff.created_at.desc()))).all()
    visible = []
    for row in rows:
        try:
            await prohibit_participant_import(db, actor, row.import_id)
        except ApiError:
            continue
        visible.append(handoff_view(row))
    return {"items": visible[offset:offset + limit], "total": len(visible), "offset": offset, "limit": limit}


@router.get("/handoffs/{handoff_id}")
async def handoff_detail(handoff_id: str, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    item = await db.get(Handoff, handoff_id)
    if not item:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await prohibit_participant_import(db, actor, item.import_id)
    return handoff_view(item)


@router.get("/handoffs/{handoff_id}/files/{filename}")
async def download(handoff_id: str, filename: str, request: Request, actor: Actor, db: Db) -> FileResponse:
    require_role(actor, "lead", "auditor")
    item = await db.get(Handoff, handoff_id)
    if not item or filename not in FILES:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await prohibit_participant_import(db, actor, item.import_id)
    directory = request.app.state.settings.data_dir / "exports" / item.id
    verify_snapshot(directory, item.manifest)
    await mark_import_exposure(db, actor, item.import_id, "SNAPSHOT_READ")
    audit(db, request, actor.id, "SNAPSHOT_DOWNLOADED", item.id, {"file": filename})
    return FileResponse(directory / filename, filename=filename, media_type="application/json" if filename.endswith(".json") else "application/x-ndjson")


@router.get("/handoffs/{handoff_id}/evidence")
async def handoff_evidence(handoff_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    item = await db.get(Handoff, handoff_id)
    if not item:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await prohibit_participant_import(db, actor, item.import_id)
    directory = request.app.state.settings.data_dir / "exports" / item.id
    verify_snapshot(directory, item.manifest)
    report = json.loads((directory / "s4_report.json").read_text(encoding="utf-8"))
    bundle = report.get("evidence_bundle")
    if not isinstance(bundle, dict) or canonical_sha256(bundle) != report.get("evidence_sha256"):
        raise ApiError(409, "LEGACY_EVIDENCE_UNAVAILABLE", "原冻结包未包含完整复算资料或资料摘要失配，不能补造历史证据")
    await mark_import_exposure(db, actor, item.import_id, "EVIDENCE_READ")
    audit(db, request, actor.id, "HANDOFF_EVIDENCE_READ", item.id, {"evidence_sha256": report["evidence_sha256"], "snapshot_hash": item.snapshot_hash})
    return dict(bundle)


@router.post("/handoffs/{handoff_id}/sent")
async def mark_sent(handoff_id: str, body: SentInput, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    item = await db.scalar(select(Handoff).where(Handoff.id == handoff_id).with_for_update())
    if not item:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    await prohibit_participant_import(db, actor, item.import_id)
    if item.snapshot_hash != body.snapshot_hash:
        raise ApiError(409, "SNAPSHOT_MISMATCH", "发送证据与冻结快照不一致")
    if item.mode == "formal":
        raise ApiError(409, "EXTERNAL_CONTRACT_NOT_ALIGNED", "正式外部接口尚未对齐，不能登记正式发送")
    verify_snapshot(request.app.state.settings.data_dir / "exports" / item.id, item.manifest)
    values = {"handoff_id": item.id, "snapshot_hash": item.snapshot_hash, "destination_ref": body.destination_ref,
              "actor_id": actor.id, "evidence": body.evidence.model_dump(), "idempotency_key": body.idempotency_key, "mode": item.mode}
    await db.execute(insert(HandoffSent).values(**values).on_conflict_do_nothing(index_elements=[HandoffSent.idempotency_key]))
    event = await db.scalar(select(HandoffSent).where(HandoffSent.idempotency_key == body.idempotency_key))
    assert event is not None
    if any(getattr(event, key) != value for key, value in values.items()):
        raise ApiError(409, "SENT_EVENT_CONFLICT", "幂等发送事件已绑定另一份交付证据，不能覆盖")
    before = item.status
    item.status = "HANDOFF_SENT"
    audit(db, request, actor.id, "HANDOFF_SENT", item.id, {"before_state": before, "after_state": item.status, "sent_event_id": event.id,
                                                          "snapshot_hash": item.snapshot_hash, "destination_ref": event.destination_ref, "mode": item.mode})
    return {**handoff_view(item), "sent_event_id": event.id, "destination_ref": event.destination_ref}


@router.post("/handoffs/{handoff_id}/receipt")
async def receipt(handoff_id: str, body: ReceiptEnvelope, request: Request, db: Db,
                  authorization: str = Header(default="")) -> dict[str, Any]:
    expected = request.app.state.settings.receipt_token
    if not expected or not hmac.compare_digest(authorization, "Bearer " + expected):
        raise ApiError(403, "SERVICE_SCOPE_REQUIRED", "需要独立S5回执服务凭据")
    item = await db.scalar(select(Handoff).where(Handoff.id == handoff_id).with_for_update())
    if not item:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    if item.mode != "formal" or item.external_status == "NOT_ALIGNED" or not request.app.state.settings.external_alignment_confirmed:
        raise ApiError(409, "EXTERNAL_CONTRACT_NOT_ALIGNED", "演示或未对齐契约不能登记正式接收")
    event = await db.get(HandoffSent, body.sent_event_id) if body.sent_event_id else None
    validate_receipt_binding(item, event, body)
    if item.receipt:
        if item.receipt != body.model_dump():
            raise ApiError(409, "RECEIPT_CONFLICT", "同一交接回执不可覆盖")
    else:
        item.receipt = body.model_dump()
        item.external_status = body.status
        audit(db, request, "s5-service", "S5_RECEIPT", item.id, {"status": body.status, "sent_event_id": body.sent_event_id,
                                                                "destination_ref": body.destination_ref, "idempotency_key": body.idempotency_key})
    return handoff_view(item)


@router.get("/audit")
async def audit_events(actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "auditor")
    await independent_operator(db, actor)
    participating = await db.scalar(select(AnnotationBatch.id).where((AnnotationBatch.annotator_a == actor.id) | (AnnotationBatch.annotator_b == actor.id)).limit(1))
    if participating:
        raise ApiError(403, "PARTICIPANT_RESTRICTED", "参标审计员不能读取可能暴露本批信息的审计全集")
    rows = (await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit))).all()
    return {"items": [{"id": row.id, "actor_id": row.actor_id, "action": row.action,
                       "object_id": row.object_id, "request_id": row.request_id, "details": row.details,
                       "created_at": row.created_at.isoformat()} for row in rows], "total": await db.scalar(select(func.count()).select_from(AuditEvent)), "offset": offset, "limit": limit}
