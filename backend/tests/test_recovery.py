"""Actual database locks, job leases, duplicate registration and sealed rows."""
import asyncio
from datetime import timedelta
from typing import Any

import httpx
from helpers import demo_payload, finish_reviews, login, seed_user
from sqlalchemy import select


async def test_concurrent_import_registration_returns_one_durable_job(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    await seed_user(app, "lead", ["lead"])
    headers = await login(client, "lead")
    responses = await asyncio.gather(*(client.post("/api/s4/v1/imports", headers=headers, json=demo_payload()) for _ in range(2)))
    assert [response.status_code for response in responses] == [202, 202]
    assert len({response.json()["job_id"] for response in responses}) == 1


async def test_expired_job_lease_is_recovered_once_with_concurrent_workers(api: tuple[Any, httpx.AsyncClient]) -> None:
    from openkb_s4.models import Job, SourceImport, now
    from openkb_s4.worker import run_once
    app, client = api
    await seed_user(app, "lead", ["lead"])
    headers = await login(client, "lead")
    response = await client.post("/api/s4/v1/imports", headers=headers, json=demo_payload())
    job_id = response.json()["job_id"]
    async with app.state.sessions() as db, db.begin():
        job = await db.get(Job, job_id)
        job.state, job.attempts, job.lease_until = "RUNNING", 1, now() - timedelta(seconds=5)
    await asyncio.gather(run_once(app.state.sessions, app.state.settings), run_once(app.state.sessions, app.state.settings))
    status = (await client.get(f"/api/s4/v1/jobs/{job_id}")).json()
    assert status["state"] == "DONE" and status["attempts"] == 2
    async with app.state.sessions() as db:
        assert len((await db.scalars(select(SourceImport))).all()) == 1
    assert (await client.get("/api/s4/v1/health/ready")).status_code == 200


async def test_bad_import_fails_safely_and_can_retry_without_losing_raw_denominator(api: tuple[Any, httpx.AsyncClient]) -> None:
    from openkb_s4.worker import run_once
    app, client = api
    await seed_user(app, "lead", ["lead"])
    headers = await login(client, "lead")
    payload = demo_payload()
    payload["units"][0]["contexts"] = []
    response = await client.post("/api/s4/v1/imports", headers=headers, json=payload)
    await run_once(app.state.sessions, app.state.settings)
    status = (await client.get(f"/api/s4/v1/jobs/{response.json()['job_id']}")).json()
    assert status["state"] == "FAILED"
    assert "database" not in status["error_message"].lower()
    retry = await client.post("/api/s4/v1/imports", headers=headers, json=payload)
    assert retry.json()["job_id"] == response.json()["job_id"]


async def test_expired_job_at_attempt_limit_fails_without_running_again(api: tuple[Any, httpx.AsyncClient]) -> None:
    from openkb_s4.models import Job, SourceImport, now
    from openkb_s4.worker import run_once
    app, client = api
    await seed_user(app, "lead", ["lead"])
    headers = await login(client, "lead")
    response = await client.post("/api/s4/v1/imports", headers=headers, json=demo_payload())
    job_id = response.json()["job_id"]
    async with app.state.sessions() as db, db.begin():
        job = await db.get(Job, job_id)
        job.state, job.attempts, job.lease_until = "RUNNING", 3, now() - timedelta(seconds=1)
    await run_once(app.state.sessions, app.state.settings)
    status = (await client.get(f"/api/s4/v1/jobs/{job_id}")).json()
    assert status["state"] == "FAILED" and status["attempts"] == 3
    assert status["error_code"] == "RETRY_LIMIT_REACHED"
    async with app.state.sessions() as db:
        assert not (await db.scalars(select(SourceImport))).all()


async def test_concurrent_submission_is_serialized_and_same_request_replays(api: tuple[Any, httpx.AsyncClient]) -> None:
    from test_workflow import setup_batch
    app, client = api
    await setup_batch(app, client)
    headers = await login(client, "a")
    task = (await client.get("/api/s4/v1/me/tasks")).json()["items"][0]
    body = {"phase": "BLIND", "content_revision": task["content_revision"], "profile_version": task["profile_version"], "payload": {"answer": "independent", "reason": "source"}}
    url = f"/api/s4/v1/assignments/{task['id']}/submit"
    responses = await asyncio.gather(*(client.post(url, headers={**headers, "Idempotency-Key": "same-request"}, json=body) for _ in range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert (await client.post(url, headers={**headers, "Idempotency-Key": "different-request"}, json=body)).status_code == 409


async def test_export_io_failure_is_bounded_then_explicit_retry_publishes_once(api: tuple[Any, httpx.AsyncClient]) -> None:
    from test_quality import decisions
    from test_workflow import setup_batch

    from openkb_s4.models import Handoff
    from openkb_s4.worker import run_once
    app, client = api
    _, batch, _ = await setup_batch(app, client)
    headers, _ = await finish_reviews(app, client, batch)
    assert (await client.post(f"/api/s4/v1/annotation-batches/{batch['id']}/finalize", headers=headers, json={"decisions": decisions(batch)})).status_code == 200
    # A real filesystem failure after the worker's claim simulates unavailable storage.
    export_root = app.state.settings.data_dir / "exports"
    export_root.write_text("storage unavailable", encoding="utf-8")
    response = await client.post("/api/s4/v1/handoffs", headers=headers, json={"import_id": batch["import_id"]})
    job_id = response.json()["job_id"]
    for _ in range(3):
        assert await run_once(app.state.sessions, app.state.settings)
    job = (await client.get(f"/api/s4/v1/jobs/{job_id}")).json()
    assert job["state"] == "FAILED" and job["attempts"] == 3
    assert job["error_code"] == "WORKER_ERROR"
    async with app.state.sessions() as db:
        assert not (await db.scalars(select(Handoff))).all()
    export_root.unlink()
    retry = await client.post("/api/s4/v1/handoffs", headers=headers, json={"import_id": batch["import_id"]})
    assert retry.json()["job_id"] == job_id
    await run_once(app.state.sessions, app.state.settings)
    assert (await client.get(f"/api/s4/v1/jobs/{job_id}")).json()["state"] == "DONE"
    async with app.state.sessions() as db:
        assert len((await db.scalars(select(Handoff))).all()) == 1
