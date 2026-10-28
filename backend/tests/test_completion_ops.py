"""Operations protections and evidence traceability, including real PostgreSQL APIs."""
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from helpers import login, seed_user


def test_reminder_key_has_bounded_interval_and_no_other_participant() -> None:
    from openkb_s4.models import now
    from openkb_s4.services.operations import reminder_key
    instant = now().replace(second=0, microsecond=0)
    assert reminder_key("assignment", instant, 60) == reminder_key("assignment", instant + timedelta(seconds=1), 60)
    assert reminder_key("assignment", instant, 60) != reminder_key("other", instant, 60)
    with pytest.raises(ValueError):
        reminder_key("assignment", instant, 0)


def test_sent_evidence_requires_controlled_reference_and_digest() -> None:
    from pydantic import ValidationError

    from openkb_s4.api.exports import SentInput
    base = {"snapshot_hash": "a" * 64, "destination_ref": "manual:demo-reviewer", "idempotency_key": "delivery-1", "evidence": {"kind": "manual_delivery", "reference": "evidence:delivery-1", "sha256": "b" * 64}}
    assert SentInput.model_validate(base).evidence.reference == "evidence:delivery-1"
    for reference in ("https://evil.test/file", "C:/secret", "../escape", " "):
        with pytest.raises(ValidationError):
            SentInput.model_validate({**base, "evidence": {**base["evidence"], "reference": reference}})


def test_receipt_binding_requires_exact_sent_event_destination_and_snapshot() -> None:
    from openkb_s4.api.exports import ReceiptEnvelope, validate_receipt_binding
    from openkb_s4.models import Handoff, HandoffSent
    from openkb_s4.security import ApiError
    handoff = Handoff(id="handoff", import_id="synthetic", mode="demo", status="HANDOFF_SENT", manifest={}, snapshot_hash="a" * 64)
    event = HandoffSent(id="sent", handoff_id=handoff.id, snapshot_hash=handoff.snapshot_hash, destination_ref="manual:synthetic",
                        actor_id="operator", evidence={}, idempotency_key="sent-key", mode="demo")
    values = {"status": "S5_REJECTED", "snapshot_hash": handoff.snapshot_hash, "contract_version": "openkb.s4-s5.v1", "reason": "Synthetic binding fixture; no external acceptance.",
              "sent_event_id": event.id, "destination_ref": event.destination_ref, "idempotency_key": "receipt-key"}
    validate_receipt_binding(handoff, event, ReceiptEnvelope.model_validate(values))
    for changed in ({"sent_event_id": "other"}, {"destination_ref": "manual:other"}, {"snapshot_hash": "b" * 64}, {"idempotency_key": None}):
        with pytest.raises(ApiError):
            validate_receipt_binding(handoff, event, ReceiptEnvelope.model_validate({**values, **changed}))
    with pytest.raises(ApiError):
        validate_receipt_binding(handoff, None, ReceiptEnvelope.model_validate(values))
    handoff.status = "DEMO_READY"
    with pytest.raises(ApiError):
        validate_receipt_binding(handoff, event, ReceiptEnvelope.model_validate(values))


def test_import_report_aggregates_rows_and_truncation_without_raw_text() -> None:
    from helpers import demo_payload

    from openkb_s4.services.import_validation import validate_import_report
    payload = demo_payload()
    payload["units"][0]["contexts"] = []
    payload["units"][1]["gold"]["answerable"] = "secret-invalid-value"
    report = validate_import_report(payload)
    assert not report["valid"] and report["total_rows"] == 12
    assert {error["row"] for error in report["errors"]} >= {1, 2}
    assert "secret-invalid-value" not in str(report)
    limited = validate_import_report(payload, max_errors=1)
    assert limited["truncated"] is True and limited["error_count"] >= 2
    valid = validate_import_report(demo_payload())
    assert valid["valid"] and valid["error_count"] == 0
    with pytest.raises(ValueError):
        validate_import_report(payload, max_errors=0)
    malformed = validate_import_report({**demo_payload(), "units": [True]})
    assert malformed["errors"][0]["row"] == 1
    package_error = validate_import_report({**demo_payload(), "unknown_field": "must-not-be-returned"})
    assert package_error["errors"][0]["row"] == 0
    assert "must-not-be-returned" not in str(package_error)
    formal = {**demo_payload(), "mode": "formal"}
    formal["units"][0]["contexts"] = []
    formal_report = validate_import_report(formal)
    assert any(error["row"] == 0 and error["field_path"] == "s3_report" for error in formal_report["errors"])


def test_backup_verification_rejects_extra_files_and_traversal(tmp_path: Path) -> None:
    import runpy
    script = Path(__file__).resolve().parents[2] / "scripts" / "backup_restore.py"
    module = runpy.run_path(str(script), run_name="backup_test")
    (tmp_path / "database.dump").write_bytes(b"synthetic dump")
    manifest = {"files": module["hashes"](tmp_path)}
    module["verify_backup_files"](tmp_path, manifest)
    (tmp_path / "extra.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="file set"):
        module["verify_backup_files"](tmp_path, manifest)
    with pytest.raises(ValueError, match="path"):
        module["verify_backup_files"](tmp_path, {"files": {"../outside": "a" * 64}})


def test_admin_cli_exposes_backup_and_restore_without_requesting_password() -> None:
    import os
    import subprocess
    import sys
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    for command in ("backup", "restore"):
        result = subprocess.run([sys.executable, "-m", "openkb_s4.cli", command, "--help"], capture_output=True, text=True, env=environment, check=False)
        assert result.returncode == 0, result.stderr
        assert "--env-file" in result.stdout and "--container" in result.stdout


async def test_operations_authorization_and_personal_notification_isolation(api: tuple[Any, httpx.AsyncClient]) -> None:
    from openkb_s4.models import Notification
    app, client = api
    lead = await seed_user(app, "ops-lead", ["lead"])
    viewer = await seed_user(app, "ops-viewer", ["annotator"])
    async with app.state.sessions() as db, db.begin():
        db.add(Notification(user_id=lead, kind="TASK_OVERDUE", business_key="lead-only", payload={"assignment_id": "lead-assignment"}))
        db.add(Notification(user_id=viewer, kind="TASK_OVERDUE", business_key="viewer-only", payload={"assignment_id": "viewer-assignment"}))
    headers = await login(client, "ops-viewer")
    assert (await client.get("/api/s4/v1/operations")).status_code == 403
    notifications = (await client.get("/api/s4/v1/notifications")).json()
    assert notifications["total"] == 1
    assert notifications["items"][0]["payload"] == {"assignment_id": "viewer-assignment"}
    notice_id = notifications["items"][0]["id"]
    assert (await client.post(f"/api/s4/v1/notifications/{notice_id}/read", headers=headers)).status_code == 200
    headers = await login(client, "ops-lead")
    assert (await client.post(f"/api/s4/v1/notifications/{notice_id}/read", headers=headers)).status_code == 404
    response = await client.post("/api/s4/v1/reconciliations", headers=headers)
    assert response.status_code == 202
    from openkb_s4.worker import run_once
    assert await run_once(app.state.sessions, app.state.settings)
    operations = await client.get("/api/s4/v1/operations")
    assert operations.status_code == 200, operations.text
    assert operations.json()["worker"]["healthy"] is True
    assert operations.json()["last_reconciliation"]["state"] == "DONE"
    page = (await client.get("/api/s4/v1/reconciliations?offset=1&limit=1")).json()
    assert page["total"] == 1 and not page["items"]
    run_id = operations.json()["last_reconciliation"]["id"]
    assert (await client.get(f"/api/s4/v1/reconciliations/{run_id}/findings")).json()["total"] == 0
    assert (await client.get("/api/s4/v1/reconciliations/missing/findings")).status_code == 404


async def test_reconcile_detects_partial_and_personal_reminders_are_idempotent(api: tuple[Any, httpx.AsyncClient]) -> None:
    from sqlalchemy import select
    from test_workflow import setup_batch

    from openkb_s4.models import AnnotationBatch, Notification, ReconciliationFinding, now
    from openkb_s4.services.operations import reconcile
    app, client = api
    _, batch, _ = await setup_batch(app, client)
    directory = app.state.settings.data_dir / "exports" / "interrupted.partial"
    directory.mkdir(parents=True)
    async with app.state.sessions() as db, db.begin():
        target = await db.get(AnnotationBatch, batch["id"])
        target.due_at = now() - timedelta(minutes=5)
        await reconcile(db, app.state.settings, None)
    async with app.state.sessions() as db, db.begin():
        await reconcile(db, app.state.settings, None)
    async with app.state.sessions() as db:
        notices = (await db.scalars(select(Notification))).all()
        findings = (await db.scalars(select(ReconciliationFinding))).all()
        assert len(notices) == 16
        assert all(set(notice.payload) == {"assignment_id", "phase", "due_at"} for notice in notices)
        assert [item.kind for item in findings].count("UNPUBLISHED_PARTIAL") == 2


async def test_download_does_not_send_and_delivery_replays_without_external_acceptance(api: tuple[Any, httpx.AsyncClient]) -> None:
    from test_handoffs import ready_snapshot
    app, client = api
    headers, _, handoff = await ready_snapshot(app, client)
    assert (await client.get(f"/api/s4/v1/handoffs/{handoff['id']}/files/s4_report.json")).status_code == 200
    assert (await client.get(f"/api/s4/v1/handoffs/{handoff['id']}")).json()["status"] == "DEMO_READY"
    body = {"snapshot_hash": handoff["snapshot_hash"], "destination_ref": "manual:demo-recipient", "evidence": {"kind": "manual_delivery", "reference": "evidence:delivery", "sha256": "b" * 64}, "idempotency_key": "sent-1"}
    url = f"/api/s4/v1/handoffs/{handoff['id']}/sent"
    first = await client.post(url, headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "HANDOFF_SENT"
    assert first.json()["external_status"] == "NOT_ALIGNED"
    assert (await client.post(url, headers=headers, json=body)).json() == first.json()
    assert (await client.post(url, headers=headers, json={**body, "destination_ref": "manual:other"})).status_code == 409
    evidence = await client.get(f"/api/s4/v1/handoffs/{handoff['id']}/evidence")
    assert evidence.status_code == 200, evidence.text
    payload = evidence.json()
    assert payload["snapshot_hash"] == handoff["snapshot_hash"]
    assert len(payload["submissions"]) == 32
    assert {item["phase"] for item in payload["submissions"]} == {"BLIND", "REVIEW"}
    assert payload["agreements"][0]["vectors"]["selected_ids"]
    assert len(payload["final_decisions"]) == 8
    assert all(item["actor_id"] and item["reason"] for item in payload["final_decisions"])
    assert all("editor_id" in item for item in payload["validations"])
    app.state.settings.receipt_token = "synthetic-receipt-test-token"
    app.state.settings.external_alignment_confirmed = True
    receipt = await client.post(f"/api/s4/v1/handoffs/{handoff['id']}/receipt", headers={"Authorization": "Bearer synthetic-receipt-test-token"},
                                json={"status": "S5_REJECTED", "reason": "Synthetic local rejection probe only", "snapshot_hash": handoff["snapshot_hash"],
                                      "contract_version": "openkb.s4-s5.v1", "sent_event_id": first.json()["sent_event_id"],
                                      "destination_ref": "manual:other", "idempotency_key": "receipt-1"})
    assert receipt.status_code == 409 and receipt.json()["error_code"] == "EXTERNAL_CONTRACT_NOT_ALIGNED"
    assert (await client.get(f"/api/s4/v1/handoffs/{handoff['id']}")).json()["external_status"] == "NOT_ALIGNED"


async def test_long_job_heartbeats_without_waiting_for_next_poll(api: tuple[Any, httpx.AsyncClient], monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from helpers import demo_payload

    from openkb_s4.models import Heartbeat
    from openkb_s4.worker import run_once
    app, client = api
    await seed_user(app, "long-lead", ["lead"])
    headers = await login(client, "long-lead")
    await client.post("/api/s4/v1/imports", headers=headers, json=demo_payload())
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_import(db: Any, job: Any) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return {"safe": True}

    monkeypatch.setattr("openkb_s4.worker.import_data", delayed_import)
    app.state.settings.worker_heartbeat_seconds = 1
    runner = asyncio.create_task(run_once(app.state.sessions, app.state.settings))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with app.state.sessions() as db:
            first = (await db.get(Heartbeat, "worker")).at
        await asyncio.sleep(1.2)
        async with app.state.sessions() as db:
            assert (await db.get(Heartbeat, "worker")).at > first
    finally:
        release.set()
        await runner


async def test_reconcile_reports_multiple_faults_without_repairing_history(api: tuple[Any, httpx.AsyncClient]) -> None:
    from helpers import demo_payload
    from sqlalchemy import select

    from openkb_s4.models import (
        AnnotationBatch,
        Handoff,
        HandoffSent,
        Job,
        ReconciliationFinding,
        SourceImport,
        now,
    )
    from openkb_s4.services.operations import reconcile
    app, client = api
    lead = await seed_user(app, "fault-ops", ["lead"])
    a = await seed_user(app, "fault-a", ["annotator"])
    b = await seed_user(app, "fault-b", ["annotator"])
    async with app.state.sessions() as db, db.begin():
        imported = SourceImport(batch_id="SYNTHETIC-FAULT", source_revision="fault-r1", mode="demo", payload=demo_payload(), content_hash="a" * 64, creator_id=lead)
        db.add(imported)
        await db.flush()
        batch = AnnotationBatch(import_id=imported.id, dataset="QA-D1", state="S4_READY", annotator_a=a, annotator_b=b, profile_version="legacy.v1", selected_ids=["QA-D1-0000"], sample_ledger={}, seed=1)
        handoff = Handoff(import_id=imported.id, mode="demo", status="HANDOFF_SENT", manifest={}, snapshot_hash="b" * 64)
        db.add_all([batch, handoff])
        await db.flush()
        db.add(HandoffSent(handoff_id=handoff.id, snapshot_hash=handoff.snapshot_hash, destination_ref="manual:synthetic", actor_id=lead,
                           evidence={"kind": "synthetic-test"}, idempotency_key="fault-delivery", mode="demo", created_at=now() - timedelta(days=2)))
        db.add_all([Job(kind="IMPORT", business_key="fault-" + state, state=state, creator_id=lead, payload={}, attempts=3 if state == "FAILED" else 1,
                        created_at=now() - timedelta(days=2), lease_until=now() - timedelta(seconds=2) if state == "RUNNING" else None)
                    for state in ("FAILED", "RUNNING", "PENDING")])
        orphan = app.state.settings.data_dir / "exports" / "orphan"
        orphan.mkdir(parents=True)
        await reconcile(db, app.state.settings, lead)
        handoff_id, batch_id = handoff.id, batch.id
    async with app.state.sessions() as db:
        kinds = {item.kind for item in (await db.scalars(select(ReconciliationFinding))).all()}
        assert {"ASSIGNMENT_SCOPE_MISMATCH", "SUBMISSION_COUNT_MISMATCH", "PUBLISHED_SNAPSHOT_INVALID", "RECEIPT_MISSING", "ORPHAN_SNAPSHOT", "JOB_FAILED", "JOB_LEASE_EXPIRED", "JOB_QUEUE_DELAY"} <= kinds
        assert (await db.get(Handoff, handoff_id)).receipt is None
        assert (await db.get(AnnotationBatch, batch_id)).state == "S4_READY"
    headers = await login(client, "fault-ops")
    operations = (await client.get("/api/s4/v1/operations")).json()
    assert operations["queue"]["expired"] == 1 and operations["queue"]["failed"] == 1
    run_id = operations["last_reconciliation"]["id"]
    findings = (await client.get(f"/api/s4/v1/reconciliations/{run_id}/findings?limit=1")).json()
    assert len(findings["items"]) == 1 and findings["total"] >= 8
    assert headers


async def test_old_worker_rolls_back_after_a_new_attempt_takes_ownership(api: tuple[Any, httpx.AsyncClient], monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from helpers import demo_payload
    from sqlalchemy import func, select

    from openkb_s4.models import AuditEvent, Job, now
    from openkb_s4.worker import import_data, run_once
    app, client = api
    await seed_user(app, "fence-ops", ["lead"])
    headers = await login(client, "fence-ops")
    response = await client.post("/api/s4/v1/imports", headers=headers, json=demo_payload())
    job_id = response.json()["job_id"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def import_with_paused_first_attempt(db: Any, job: Any) -> dict[str, Any]:
        if job.attempts != 1:
            return await import_data(db, job)
        entered.set()
        await release.wait()
        db.add(AuditEvent(actor_id=None, action="SYNTHETIC_STALE_WRITE", object_id=job.id, request_id="synthetic-test", details={}))
        return {"stale": True}

    async def stopped_heartbeat(*args: Any) -> None:
        await release.wait()

    monkeypatch.setattr("openkb_s4.worker.import_data", import_with_paused_first_attempt)
    monkeypatch.setattr("openkb_s4.worker.heartbeat_loop", stopped_heartbeat)
    runner = asyncio.create_task(run_once(app.state.sessions, app.state.settings))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        # Model a stopped worker whose persisted lease has expired. The running
        # coroutine is resumed only after a replacement has committed its work.
        async with app.state.sessions() as db, db.begin():
            job = await db.get(Job, job_id)
            job.lease_until = now() - timedelta(seconds=5)
        assert await run_once(app.state.sessions, app.state.settings)
    finally:
        release.set()
        await runner
    async with app.state.sessions() as db:
        job = await db.get(Job, job_id)
        assert job.state == "DONE" and job.attempts == 2
        assert "import_id" in job.result and "stale" not in job.result
        assert await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "SYNTHETIC_STALE_WRITE")) == 0


async def test_slow_export_fsync_does_not_stop_worker_heartbeat(api: tuple[Any, httpx.AsyncClient], monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from helpers import finish_reviews
    from test_quality import decisions
    from test_workflow import setup_batch

    from openkb_s4.models import Heartbeat
    from openkb_s4.services import handoffs
    from openkb_s4.worker import run_once
    app, client = api
    _, batch, _ = await setup_batch(app, client)
    headers, _ = await finish_reviews(app, client, batch)
    response = await client.post(f"/api/s4/v1/annotation-batches/{batch['id']}/finalize", headers=headers, json={"decisions": decisions(batch)})
    assert response.status_code == 200, response.text
    response = await client.post("/api/s4/v1/handoffs", headers=headers, json={"import_id": batch["import_id"]})
    assert response.status_code == 202
    original_fsync = handoffs.os.fsync
    delayed = False

    def slow_fsync(descriptor: int) -> None:
        nonlocal delayed
        if not delayed:
            delayed = True
            time.sleep(1.5)
        original_fsync(descriptor)

    monkeypatch.setattr(handoffs.os, "fsync", slow_fsync)
    app.state.settings.worker_heartbeat_seconds = 1
    async with app.state.sessions() as db:
        before = (await db.get(Heartbeat, "worker")).at
    assert await run_once(app.state.sessions, app.state.settings)
    async with app.state.sessions() as db:
        after = (await db.get(Heartbeat, "worker")).at
    assert (after - before).total_seconds() >= 1
    job = (await client.get(f"/api/s4/v1/jobs/{response.json()['job_id']}")).json()
    assert job["state"] == "DONE", job
