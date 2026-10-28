"""Authorized operations and personal station notifications."""
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from ..models import Notification, ReconciliationFinding, ReconciliationRun, now
from ..security import Actor, ApiError, Db, require_role
from ..services.common import audit
from ..services.jobs import enqueue
from ..services.operations import independent_operator, metrics, run_view

router = APIRouter()


@router.get("/operations")
async def operations(request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    await independent_operator(db, actor)
    return await metrics(db, request.app.state.settings)


@router.post("/reconciliations", status_code=202)
async def request_reconciliation(request: Request, actor: Actor, db: Db) -> dict[str, str]:
    require_role(actor, "lead", "auditor")
    await independent_operator(db, actor)
    key = f"reconcile:manual:{int(now().timestamp()) // 60}"
    job = await enqueue(db, "RECONCILE", key, actor.id, {})
    audit(db, request, actor.id, "RECONCILIATION_REQUESTED", job.id)
    return {"job_id": job.id}


@router.get("/reconciliations")
async def reconciliations(actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    await independent_operator(db, actor)
    rows = (await db.scalars(select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).offset(offset).limit(limit))).all()
    return {"items": [run_view(row) for row in rows], "total": await db.scalar(select(func.count()).select_from(ReconciliationRun)), "offset": offset, "limit": limit}


@router.get("/reconciliations/{run_id}/findings")
async def findings(run_id: str, actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    await independent_operator(db, actor)
    if not await db.get(ReconciliationRun, run_id):
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    condition = ReconciliationFinding.run_id == run_id
    rows = (await db.scalars(select(ReconciliationFinding).where(condition).order_by(ReconciliationFinding.created_at).offset(offset).limit(limit))).all()
    return {"items": [{"id": row.id, "kind": row.kind, "object_type": row.object_type, "object_id": row.object_id,
                       "severity": row.severity, "details": row.details, "status": row.status, "created_at": row.created_at.isoformat()} for row in rows],
            "total": await db.scalar(select(func.count()).select_from(ReconciliationFinding).where(condition)), "offset": offset, "limit": limit}


def notification_view(row: Notification) -> dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "payload": row.payload, "created_at": row.created_at.isoformat(),
            "read_at": row.read_at.isoformat() if row.read_at else None}


@router.get("/notifications")
async def notifications(actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    condition = Notification.user_id == actor.id
    rows = (await db.scalars(select(Notification).where(condition).order_by(Notification.created_at.desc()).offset(offset).limit(limit))).all()
    return {"items": [notification_view(row) for row in rows], "total": await db.scalar(select(func.count()).select_from(Notification).where(condition)), "offset": offset, "limit": limit}


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, actor: Actor, db: Db) -> dict[str, Any]:
    row = await db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == actor.id).with_for_update())
    if not row:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    if not row.read_at:
        row.read_at = now()
    return notification_view(row)
