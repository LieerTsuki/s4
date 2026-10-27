"""Controlled snapshot downloads, authenticated receipts and minimal audit visibility."""
import hmac
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..models import AnnotationBatch, AuditEvent, Handoff
from ..schemas import HandoffInput, ReceiptInput
from ..security import Actor, ApiError, Db, digest, require_role
from ..services.common import audit, mark_import_exposure, prohibit_participant_import, source
from ..services.handoffs import FILES, verify_snapshot
from ..services.jobs import enqueue

router = APIRouter()


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
async def handoffs(actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    rows = (await db.scalars(select(Handoff).order_by(Handoff.created_at.desc()).limit(500))).all()
    visible = []
    for row in rows:
        try:
            await prohibit_participant_import(db, actor, row.import_id)
        except ApiError:
            continue
        visible.append(handoff_view(row))
    return {"items": visible, "total": len(visible)}


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


@router.post("/handoffs/{handoff_id}/receipt")
async def receipt(handoff_id: str, body: ReceiptInput, request: Request, db: Db,
                  authorization: str = Header(default="")) -> dict[str, Any]:
    expected = request.app.state.settings.receipt_token
    if not expected or not hmac.compare_digest(authorization, "Bearer " + expected):
        raise ApiError(403, "SERVICE_SCOPE_REQUIRED", "需要独立S5回执服务凭据")
    item = await db.scalar(select(Handoff).where(Handoff.id == handoff_id).with_for_update())
    if not item:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    if item.mode != "formal" or not request.app.state.settings.external_alignment_confirmed:
        raise ApiError(409, "EXTERNAL_CONTRACT_NOT_ALIGNED", "演示或未对齐契约不能登记正式接收")
    if item.snapshot_hash != body.snapshot_hash:
        raise ApiError(409, "SNAPSHOT_MISMATCH", "回执与冻结快照不一致")
    if item.receipt:
        if item.receipt != body.model_dump():
            raise ApiError(409, "RECEIPT_CONFLICT", "同一交接回执不可覆盖")
    else:
        item.receipt = body.model_dump()
        item.external_status = body.status
        audit(db, request, "s5-service", "S5_RECEIPT", item.id, {"status": body.status})
    return handoff_view(item)


@router.get("/audit")
async def audit_events(actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "auditor")
    participating = await db.scalar(select(AnnotationBatch.id).where((AnnotationBatch.annotator_a == actor.id) | (AnnotationBatch.annotator_b == actor.id)).limit(1))
    if participating:
        raise ApiError(403, "PARTICIPANT_RESTRICTED", "参标审计员不能读取可能暴露本批信息的审计全集")
    rows = (await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit))).all()
    return {"items": [{"id": row.id, "actor_id": row.actor_id, "action": row.action,
                       "object_id": row.object_id, "request_id": row.request_id, "details": row.details,
                       "created_at": row.created_at.isoformat()} for row in rows], "total": len(rows)}
