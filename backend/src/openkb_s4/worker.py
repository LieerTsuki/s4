"""Durable PostgreSQL jobs with leases, retries and deterministic publication."""
import argparse
import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings, get_settings
from .db import make_sessions
from .domain.contracts import canonical_sha256
from .domain.errors import DomainError
from .domain.profiles import get_profile
from .domain.statistics import calculate_agreement
from .models import (
    Agreement,
    AnnotationBatch,
    Assignment,
    AuditEvent,
    Heartbeat,
    Job,
    SourceImport,
    Submission,
    User,
    now,
)
from .security import ApiError
from .services.common import source, source_unit
from .services.handoffs import export_snapshot
from .services.import_validation import validate_import_report
from .services.jobs import enqueue
from .services.operations import reconcile

logger = logging.getLogger("openkb_s4.worker")


class ImportValidationError(ApiError):
    def __init__(self, report: dict[str, Any]) -> None:
        first = report["errors"][0] if report["errors"] else {}
        super().__init__(422, first.get("error_code", "IMPORT_INVALID"), "导入校验失败，请核对逐项错误报告")
        self.report = report


class LeaseLostError(Exception):
    """A stale worker must roll back without modifying the current owner's job."""


async def import_data(db: AsyncSession, job: Job) -> dict[str, Any]:
    report = validate_import_report(job.payload)
    if not report["valid"]:
        raise ImportValidationError(report)
    payload = report["normalized"]
    content_hash = canonical_sha256(payload)
    existing = await db.scalar(select(SourceImport).where(SourceImport.content_hash == content_hash))
    if existing:
        return {"import_id": existing.id}
    same_revision = await db.scalar(select(SourceImport).where(SourceImport.batch_id == payload["batch_id"], SourceImport.source_revision == payload["source_revision"]))
    if same_revision:
        raise ApiError(409, "SOURCE_REVISION_CONFLICT", "同一来源版本不得覆盖原内容")
    imported = SourceImport(batch_id=payload["batch_id"], source_revision=payload["source_revision"],
                            mode=payload["mode"], payload=payload, content_hash=content_hash,
                            blocked_reasons=payload.get("blocked_reasons", []), creator_id=job.creator_id)
    db.add(imported)
    await db.flush()
    from .services.revisions import ensure_revisions
    await ensure_revisions(db, imported)
    return {"import_id": imported.id}


async def compute_agreement(db: AsyncSession, job: Job) -> dict[str, Any]:
    batch = await db.scalar(select(AnnotationBatch).where(AnnotationBatch.id == job.payload["batch_id"]).with_for_update())
    if not batch or batch.state not in {"PAIR_COMPLETE", "S4_READY"}:
        raise ApiError(409, "PAIR_INCOMPLETE", "本批当前尚不可计算统计")
    existing = await db.scalar(select(Agreement).where(Agreement.batch_id == batch.id))
    if existing:
        return {"agreement_id": existing.id}
    assignments = (await db.scalars(select(Assignment).where(Assignment.batch_id == batch.id, Assignment.active.is_(True)))).all()
    mapping = {(a.unit_id, a.seat): a for a in assignments}
    submissions = (await db.scalars(select(Submission).where(Submission.assignment_id.in_([a.id for a in assignments]), Submission.phase == "REVIEW"))).all()
    by_assignment = {item.assignment_id: item for item in submissions}
    imported = await source(db, batch.import_id)
    a_vector: list[str] = []
    b_vector: list[str] = []
    unit_records: list[dict[str, Any]] = []
    disagreements: list[str] = []
    for unit_id in batch.selected_ids:
        a, b = mapping.get((unit_id, "A")), mapping.get((unit_id, "B"))
        if not a or not b or a.id not in by_assignment or b.id not in by_assignment or a.content_revision != b.content_revision:
            raise ApiError(409, "PAIR_INCOMPLETE", "同版本双方原始结果不完整")
        labels_a, labels_b = by_assignment[a.id].payload, by_assignment[b.id].payload
        unit = source_unit(imported, unit_id)
        expected_keys = [f"P{i + 1:03d}" for i in range(len(unit.get("gold", {}).get("answer_points", [])))]
        for key in expected_keys:
            if key not in labels_a.get("point_labels", {}) or key not in labels_b.get("point_labels", {}):
                raise ApiError(409, "PAIR_INCOMPLETE", "原始要点配对不完整")
            a_vector.append(labels_a["point_labels"][key])
            b_vector.append(labels_b["point_labels"][key])
        comparison_keys = ("point_labels", "evidence_labels", "answerable", "specialized_review", "suggested_points", "evidence_changes")
        if any(labels_a.get(key) != labels_b.get(key) for key in comparison_keys):
            disagreements.append(unit_id)
        unit_records.append({"unit_id": unit_id, "content_revision": a.content_revision,
                             "point_order": expected_keys,
                             "grades_a": labels_a, "grades_b": labels_b,
                             "submission_hash_a": by_assignment[a.id].payload_hash, "submission_hash_b": by_assignment[b.id].payload_hash})
    result = calculate_agreement(a_vector, b_vector)
    profile = batch.profile_snapshot or get_profile(batch.dataset)
    extra_blocks = [*batch.blocked_reasons, *profile.get("blocked_reasons", []), *profile.get("conditional_checks", [])]
    if profile.get("formal_enabled") is False:
        extra_blocks.append("PROFILE_STATISTICS_NOT_APPROVED")
    if profile["kind"] != "qa_points":
        extra_blocks.append("SPECIALIZED_STATISTICS_NOT_CONFIRMED")
    if extra_blocks:
        result = {**result, "kappa": None, "verdict": "BLOCKED", "blocked_reasons": sorted(set(result["blocked_reasons"] + extra_blocks))}
    result["disagreement_unit_ids"] = disagreements
    vectors = {"annotator_a": batch.annotator_a, "annotator_b": batch.annotator_b,
               "round": batch.round, "profile_version": batch.profile_version,
               "profile_hash": batch.profile_hash, "manual_version": batch.manual_version,
               "label_dictionaries": profile.get("label_dictionaries", {"point_labels": profile.get("point_labels", []), "evidence_labels": profile.get("evidence_labels", [])}),
               "point_order": [{"unit_id": record["unit_id"], "point_keys": record["point_order"]} for record in unit_records],
               "selected_ids": batch.selected_ids, "a": a_vector, "b": b_vector, "units": unit_records}
    agreement = Agreement(batch_id=batch.id, result=result, input_hash=canonical_sha256(vectors), vectors=vectors)
    db.add(agreement)
    await db.flush()
    return {"agreement_id": agreement.id}


async def heartbeat_loop(factory: async_sessionmaker[AsyncSession], settings: Settings, job_id: str, attempt: int) -> None:
    """Update health and renew the claim in a separate transaction during long work."""
    while True:
        try:
            async with factory() as db, db.begin():
                await db.execute(insert(Heartbeat).values(name="worker", at=now()).on_conflict_do_update(index_elements=[Heartbeat.name], set_={"at": now()}))
                await db.execute(update(Job).where(Job.id == job_id, Job.state == "RUNNING", Job.attempts == attempt).values(lease_until=now() + timedelta(seconds=settings.worker_lease_seconds)))
        except Exception:
            logger.error('{"event":"heartbeat_failed","job_id":"%s"}', job_id)
        await asyncio.sleep(settings.worker_heartbeat_seconds)


async def run_once(factory: async_sessionmaker[AsyncSession], settings: Settings) -> bool:
    """Claim and execute at most one job; leases survive process loss."""
    async with factory() as db, db.begin():
        await db.execute(insert(Heartbeat).values(name="worker", at=now()).on_conflict_do_update(index_elements=[Heartbeat.name], set_={"at": now()}))
        job = await db.scalar(select(Job).where(or_(Job.state == "PENDING", (Job.state == "RUNNING") & (Job.lease_until < now()))).order_by(Job.created_at).with_for_update(skip_locked=True).limit(1))
        if not job:
            return False
        if job.attempts >= settings.worker_max_attempts:
            job.state, job.error_code, job.error_message, job.lease_until = "FAILED", "RETRY_LIMIT_REACHED", "后台任务已达尝试上限，请人工核对后明确重试", None
            return True
        job.state, job.attempts, job.lease_until = "RUNNING", job.attempts + 1, now() + timedelta(seconds=settings.worker_lease_seconds)
        job_id, attempt = job.id, job.attempts
    heartbeats = asyncio.create_task(heartbeat_loop(factory, settings, job_id, attempt))
    try:
        async with factory() as db, db.begin():
            # Do not hold the job row lock while processing: the independent
            # heartbeat transaction must be able to renew this lease.
            working = await db.get(Job, job_id)
            assert working is not None
            if not settings.legacy_writes_enabled and working.kind in {"IMPORT", "AGREEMENT", "EXPORT"}:
                raise ApiError(409, "LEGACY_READ_ONLY", "历史任务已停止写入，请使用v1.3新流程")
            if working.kind == "IMPORT":
                result = await import_data(db, working)
            elif working.kind == "AGREEMENT":
                result = await compute_agreement(db, working)
            elif working.kind == "EXPORT":
                imported = await source(db, working.payload["import_id"])
                handoff = await export_snapshot(db, settings, imported)
                result = {"handoff_id": handoff.id}
            elif working.kind == "EXPORT_V13":
                from .services.handoffs_v13 import export_snapshot_v13
                handoff_v13 = await export_snapshot_v13(db, settings, working.payload["import_id"], working.creator_id)
                result = {"handoff_id": handoff_v13.id}
            elif working.kind == "RECONCILE":
                run = await reconcile(db, settings, working.creator_id)
                result = {"reconciliation_id": run.id, "summary": run.summary}
            else:
                raise ApiError(422, "UNKNOWN_JOB", "不支持的后台任务类型")
            fence = await db.execute(update(Job).where(Job.id == job_id, Job.state == "RUNNING", Job.attempts == attempt).values(state="DONE", result=result, lease_until=None, error_code=None, error_message=None).returning(Job.id))
            if fence.scalar_one_or_none() is None:
                raise LeaseLostError()
            db.add(AuditEvent(actor_id=working.creator_id, action="JOB_COMPLETED", object_id=working.id,
                              request_id="worker", details={"kind": working.kind, "attempts": working.attempts}))
    except LeaseLostError:
        logger.warning('{"event":"job_lease_lost","job_id":"%s"}', job_id)
    except (ApiError, DomainError) as exc:
        async with factory() as db, db.begin():
            values: dict[str, Any] = {"state": "FAILED", "error_code": exc.code, "error_message": exc.message[:500], "lease_until": None}
            if isinstance(exc, ImportValidationError):
                values["result"] = {"validation_report": exc.report}
            await db.execute(update(Job).where(Job.id == job_id, Job.state == "RUNNING", Job.attempts == attempt).values(**values))
    except Exception:
        logger.error('{"event":"job_failed","job_id":"%s"}', job_id)
        async with factory() as db, db.begin():
            await db.execute(update(Job).where(Job.id == job_id, Job.state == "RUNNING", Job.attempts == attempt).values(
                state="FAILED" if attempt >= settings.worker_max_attempts else "PENDING", error_code="WORKER_ERROR",
                error_message="后台任务执行失败，可安全重试或查看运维状态", lease_until=None))
    finally:
        heartbeats.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeats
    return True


async def serve(once: bool) -> None:
    settings = get_settings()
    engine, factory = make_sessions(settings.database_url)
    try:
        while True:
            if not once:
                async with factory() as db, db.begin():
                    # Timer buckets deduplicate across processes and survive restart.
                    users = (await db.scalars(select(User).where(User.active.is_(True)).order_by(User.created_at))).all()
                    operator = next((user for user in users if "lead" in user.roles), None)
                    if operator:
                        key = f"reconcile:periodic:{int(now().timestamp()) // settings.reconcile_interval_seconds}"
                        if not await db.scalar(select(Job.id).where(Job.business_key == key)):
                            await enqueue(db, "RECONCILE", key, operator.id, {})
            worked = await run_once(factory, settings)
            if once:
                return
            if not worked:
                await asyncio.sleep(2)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="S4 durable job worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(serve(args.once))


if __name__ == "__main__":
    main()
