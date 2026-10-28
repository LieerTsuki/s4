"""Read-only reconciliation, personal reminders and operational visibility."""
import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models import (
    AnnotationBatch,
    Assignment,
    AuditEvent,
    Handoff,
    HandoffSent,
    Heartbeat,
    Job,
    Notification,
    ReconciliationFinding,
    ReconciliationRun,
    Submission,
    User,
    now,
)
from ..security import ApiError
from .handoffs import verify_snapshot


def reminder_key(assignment_id: str, instant: datetime, interval_minutes: int) -> str:
    """Deduplicate each assignment's reminder within a configured UTC time bucket."""
    if interval_minutes < 1:
        raise ValueError("reminder interval must be positive")
    return f"due:{assignment_id}:{int(instant.timestamp()) // (interval_minutes * 60)}"


async def remind_overdue(db: AsyncSession) -> int:
    """Only notify the assigned person; sealed work and cancelled history are excluded."""
    instant = now()
    rows = (await db.execute(select(Assignment, AnnotationBatch).join(AnnotationBatch, Assignment.batch_id == AnnotationBatch.id).where(
        Assignment.active.is_(True), AnnotationBatch.due_at <= instant,
        AnnotationBatch.state.in_(["BLIND_OPEN", "REVIEW_OPEN"]),
    ))).all()
    count = 0
    for assignment, batch in rows:
        phase = "BLIND" if batch.state == "BLIND_OPEN" else "REVIEW"
        if await db.scalar(select(Submission.id).where(Submission.assignment_id == assignment.id, Submission.phase == phase)):
            continue
        result = await db.execute(insert(Notification).values(
            user_id=assignment.user_id, kind="TASK_OVERDUE",
            business_key=reminder_key(assignment.id, instant, batch.reminder_interval_minutes),
            payload={"assignment_id": assignment.id, "phase": phase, "due_at": batch.due_at.isoformat()},
        ).on_conflict_do_nothing(index_elements=[Notification.business_key]).returning(Notification.id))
        count += len(result.all())
    return count


async def reconcile(db: AsyncSession, settings: Settings, creator_id: str | None) -> ReconciliationRun:
    """Record discrepancies without overwriting immutable evidence or inventing receipts."""
    run = ReconciliationRun(state="RUNNING", summary={}, creator_id=creator_id)
    db.add(run)
    await db.flush()
    findings: list[dict[str, Any]] = []

    def finding(kind: str, object_type: str, object_id: str, details: dict[str, Any], severity: str = "WARNING") -> None:
        findings.append({"run_id": run.id, "kind": kind, "object_type": object_type, "object_id": object_id,
                         "severity": severity, "details": details, "status": "OPEN"})

    batches = (await db.scalars(select(AnnotationBatch).where(AnnotationBatch.state.not_in(["SUPERSEDED", "CANCELLED"])))).all()
    for batch in batches:
        assignments = (await db.scalars(select(Assignment).where(Assignment.batch_id == batch.id, Assignment.active.is_(True)))).all()
        expected = {(unit, seat) for unit in batch.selected_ids for seat in ("A", "B")}
        actual = {(assignment.unit_id, assignment.seat) for assignment in assignments}
        if actual != expected or len(assignments) != len(expected):
            finding("ASSIGNMENT_SCOPE_MISMATCH", "batch", batch.id, {"expected_count": len(expected), "actual_count": len(assignments)}, "ERROR")
        required_phases = []
        if batch.state in {"BLIND_SEALED", "REVIEW_OPEN", "PAIR_COMPLETE", "S4_READY"}:
            required_phases.append("BLIND")
        if batch.state in {"PAIR_COMPLETE", "S4_READY"}:
            required_phases.append("REVIEW")
        for phase in required_phases:
            count = await db.scalar(select(func.count()).select_from(Submission).where(Submission.assignment_id.in_([item.id for item in assignments]), Submission.phase == phase))
            if count != len(expected):
                finding("SUBMISSION_COUNT_MISMATCH", "batch", batch.id, {"phase": phase, "expected_count": len(expected), "actual_count": count}, "ERROR")
    handoffs = (await db.scalars(select(Handoff))).all()
    published = {item.id for item in handoffs}
    for handoff in handoffs:
        try:
            await asyncio.to_thread(verify_snapshot, settings.data_dir / "exports" / handoff.id, handoff.manifest)
        except (ApiError, OSError, ValueError, KeyError, TypeError) as exc:
            finding("PUBLISHED_SNAPSHOT_INVALID", "handoff", handoff.id, {"error_code": exc.code if isinstance(exc, ApiError) else "SNAPSHOT_UNREADABLE"}, "ERROR")
        if handoff.status == "HANDOFF_SENT":
            sent = await db.scalar(select(HandoffSent).where(HandoffSent.handoff_id == handoff.id).order_by(HandoffSent.created_at.desc()).limit(1))
            if not sent:
                finding("SEND_EVENT_MISSING", "handoff", handoff.id, {}, "ERROR")
            elif not handoff.receipt and (now() - sent.created_at).total_seconds() >= settings.operations_receipt_warning_seconds:
                finding("RECEIPT_MISSING", "handoff", handoff.id, {"external_status": handoff.external_status, "sent_event_id": sent.id})
    export_root = settings.data_dir / "exports"
    if export_root.is_dir():
        for directory in sorted(export_root.iterdir()):
            if directory.name.endswith(".partial"):
                finding("UNPUBLISHED_PARTIAL", "snapshot", directory.name, {})
            elif directory.is_dir() and directory.name not in published:
                finding("ORPHAN_SNAPSHOT", "snapshot", directory.name, {})
    jobs = (await db.scalars(select(Job).where(Job.state.in_(["PENDING", "RUNNING", "FAILED"])))).all()
    for job in jobs:
        if job.state == "FAILED":
            finding("JOB_FAILED", "job", job.id, {"error_code": job.error_code, "attempts": job.attempts})
        elif job.state == "RUNNING" and (not job.lease_until or job.lease_until < now()):
            finding("JOB_LEASE_EXPIRED", "job", job.id, {"attempts": job.attempts})
        elif job.state == "PENDING" and (now() - job.created_at).total_seconds() > settings.operations_pending_warning_seconds:
            finding("JOB_QUEUE_DELAY", "job", job.id, {})
    for values in findings:
        db.add(ReconciliationFinding(**values))
    reminders = await remind_overdue(db)
    run.state, run.finished_at = "DONE", now()
    run.summary = {"findings": len(findings), "errors": sum(item["severity"] == "ERROR" for item in findings), "reminders_created": reminders,
                   "batches_checked": len(batches), "handoffs_checked": len(handoffs)}
    return run


async def metrics(db: AsyncSession, settings: Settings) -> dict[str, Any]:
    heartbeat = await db.get(Heartbeat, "worker")
    instant = now()
    counts: dict[str, int] = {state: count for state, count in (await db.execute(select(Job.state, func.count()).group_by(Job.state))).all()}
    oldest = await db.scalar(select(func.min(Job.created_at)).where(Job.state == "PENDING"))
    expired = await db.scalar(select(func.count()).select_from(Job).where(Job.state == "RUNNING", Job.lease_until < instant))
    last = await db.scalar(select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(1))
    backup = await db.scalar(select(func.max(AuditEvent.created_at)).where(AuditEvent.action == "BACKUP_COMPLETED"))
    restore = await db.scalar(select(func.max(AuditEvent.created_at)).where(AuditEvent.action == "RESTORE_COMPLETED"))
    return {"worker": {"at": heartbeat.at.isoformat() if heartbeat else None, "healthy": bool(heartbeat and (instant - heartbeat.at).total_seconds() <= 90)},
            "queue": {"pending": counts.get("PENDING", 0), "running": counts.get("RUNNING", 0), "failed": counts.get("FAILED", 0), "expired": expired or 0,
                      "longest_wait_seconds": max(0.0, (instant - oldest).total_seconds()) if oldest else 0},
            "last_reconciliation": run_view(last) if last else None,
            "backup": {"last_backup_at": backup.isoformat() if backup else None, "last_restore_at": restore.isoformat() if restore else None},
            "thresholds": {"pending_warning_seconds": settings.operations_pending_warning_seconds, "receipt_warning_seconds": settings.operations_receipt_warning_seconds}}


def run_view(run: ReconciliationRun) -> dict[str, Any]:
    return {"id": run.id, "state": run.state, "summary": run.summary, "created_at": run.created_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None}


async def independent_operator(db: AsyncSession, actor: User) -> None:
    """Global findings can expose participating scopes, so deny active or historical annotators."""
    if await db.scalar(select(Assignment.id).where(Assignment.user_id == actor.id).limit(1)):
        raise ApiError(403, "PARTICIPANT_RESTRICTED", "参标人员不能读取跨批次运维信息")
