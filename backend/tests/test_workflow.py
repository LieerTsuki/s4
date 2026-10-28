"""Behavior tests against a real database and real worker."""
from typing import Any

import httpx
from helpers import calibration, demo_payload, login, seed_user


async def setup_batch(app: Any, client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, Any], dict[str, str]]:
    from openkb_s4.worker import run_once

    people = {name: await seed_user(app, name, roles) for name, roles in [("lead", ["lead"]), ("a", ["annotator"]), ("b", ["annotator"]), ("judge", ["arbitrator"])]}
    headers = await login(client, "lead")
    response = await client.post("/api/s4/v1/imports", headers=headers, json=demo_payload())
    assert response.status_code == 202, response.text
    await run_once(app.state.sessions, app.state.settings)
    job = (await client.get(f"/api/s4/v1/jobs/{response.json()['job_id']}")).json()
    assert job["state"] == "DONE", job
    response = await client.post("/api/s4/v1/annotation-batches", headers=headers, json={"import_id": job["result"]["import_id"], "dataset": "QA-D1", "annotator_a": people["a"], "annotator_b": people["b"], "seed": 19})
    assert response.status_code == 201, response.text
    return headers, response.json(), people


async def test_blind_projection_sealing_and_whole_batch_release(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    lead_headers, batch, people = await setup_batch(app, client)
    batch_id = batch["id"]
    assert batch["sample_count"] == 8
    response = await client.post(f"/api/s4/v1/annotation-batches/{batch_id}/release-review", headers=lead_headers)
    assert response.status_code == 409
    a_headers = await login(client, "a")
    tasks_a = (await client.get("/api/s4/v1/me/tasks")).json()["items"]
    assert len(tasks_a) == 8
    assert (await client.get(f"/api/s4/v1/annotation-batches/{batch_id}")).status_code == 403
    a_task = (await client.get(f"/api/s4/v1/assignments/{tasks_a[0]['id']}")).json()
    assert a_task["phase"] == "BLIND"
    assert "gold" not in a_task and "points" not in a_task and "expected_behavior" not in a_task
    assert "answer_points" not in str(a_task["material"])
    draft_url = f"/api/s4/v1/assignments/{a_task['id']}/draft"
    assert (await client.patch(draft_url, headers=a_headers, json={"phase": "BLIND", "version": 0, "payload": {"answer": "独立判断", "reason": "依据原文"}})).status_code == 200
    assert (await client.patch(draft_url, headers=a_headers, json={"phase": "BLIND", "version": 0, "payload": {}})).status_code == 409
    body = {"phase": "BLIND", "content_revision": a_task["content_revision"], "profile_version": a_task["profile_version"], "payload": {"answer": "独立判断", "reason": "依据原文"}}
    submit_url = f"/api/s4/v1/assignments/{a_task['id']}/submit"
    headers = {**a_headers, "Idempotency-Key": "test-submit"}
    first = await client.post(submit_url, headers=headers, json=body)
    assert first.status_code == 200, first.text
    second = await client.post(submit_url, headers=headers, json=body)
    assert second.json()["id"] == first.json()["id"]
    body["payload"]["answer"] = "更改已封存"
    assert (await client.post(submit_url, headers=headers, json=body)).status_code == 409
    for task in tasks_a[1:]:
        detail = (await client.get(f"/api/s4/v1/assignments/{task['id']}")).json()
        response = await client.post(f"/api/s4/v1/assignments/{task['id']}/submit", headers={**a_headers, "Idempotency-Key": task["id"]}, json={"phase": "BLIND", "content_revision": detail["content_revision"], "profile_version": detail["profile_version"], "payload": {"answer": "本人答案", "reason": "原文支持"}})
        assert response.status_code == 200, response.text
    b_headers = await login(client, "b")
    assert (await client.get(f"/api/s4/v1/assignments/{a_task['id']}")).status_code == 404
    tasks_b = (await client.get("/api/s4/v1/me/tasks")).json()["items"]
    for task in tasks_b:
        detail = (await client.get(f"/api/s4/v1/assignments/{task['id']}")).json()
        assert (await client.post(f"/api/s4/v1/assignments/{task['id']}/submit", headers={**b_headers, "Idempotency-Key": task["id"]}, json={"phase": "BLIND", "content_revision": detail["content_revision"], "profile_version": detail["profile_version"], "payload": {"answer": "本人B答案", "reason": "原文支持"}})).status_code == 200
    lead_headers = await login(client, "lead")
    assert (await client.post(f"/api/s4/v1/annotation-batches/{batch_id}/release-review", headers=lead_headers)).status_code == 200
    assert (await client.post(f"/api/s4/v1/annotation-batches/{batch_id}/release-review", headers=lead_headers)).status_code == 200
    await login(client, "a")
    detail = (await client.get(f"/api/s4/v1/assignments/{a_task['id']}")).json()
    assert detail["phase"] == "REVIEW"
    assert detail["points"][0]["point_key"] == "P001"
    assert detail["own_blind"]["answer"] == "独立判断"
    assert "annotator_b" not in detail and "agreement" not in detail


async def test_importer_cannot_be_assigned_as_unexposed_annotator(api: tuple[Any, httpx.AsyncClient]) -> None:
    from openkb_s4.worker import run_once
    app, client = api
    lead_id = await seed_user(app, "lead", ["lead", "annotator"])
    b_id = await seed_user(app, "b", ["annotator"])
    headers = await login(client, "lead")
    job = await client.post("/api/s4/v1/imports", headers=headers, json=demo_payload())
    await run_once(app.state.sessions, app.state.settings)
    status = (await client.get(f"/api/s4/v1/jobs/{job.json()['job_id']}")).json()
    response = await client.post("/api/s4/v1/annotation-batches", headers=headers,
        json={"import_id": status["result"]["import_id"], "dataset": "QA-D1", "annotator_a": lead_id, "annotator_b": b_id, "seed": 5})
    assert response.status_code == 409
    assert response.json()["error_code"] == "PREVIOUS_EXPOSURE"


async def test_business_reader_exposure_prevents_future_blind_assignment(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    _, batch, _ = await setup_batch(app, client)
    reader = await seed_user(app, "reader", ["lead", "annotator"])
    fresh = await seed_user(app, "fresh", ["annotator"])
    headers = await login(client, "reader")
    assert (await client.get(f"/api/s4/v1/annotation-batches/{batch['id']}")).status_code == 200
    calibration_id=await calibration(client,headers,batch)
    response = await client.post("/api/s4/v1/rounds", headers=headers, json={"calibration_id":calibration_id,"batch_id": batch["id"], "annotator_a": reader, "annotator_b": fresh, "seed": 55, "reason": "全批校准重标"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "PREVIOUS_EXPOSURE"


async def test_relabel_resamples_entire_frozen_population_with_registered_seed(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    headers, batch, _ = await setup_batch(app, client)
    a = await seed_user(app, "newa", ["annotator"])
    b = await seed_user(app, "newb", ["annotator"])
    calibration_id=await calibration(client,headers,batch)
    response = await client.post("/api/s4/v1/rounds", headers=headers, json={"calibration_id":calibration_id,"batch_id": batch["id"], "annotator_a": a, "annotator_b": b, "seed": 999, "reason": "冻结全批重标"})
    assert response.status_code == 201, response.text
    from openkb_s4.domain.sampling import sample_units
    assert response.json()["selected_ids"] == sample_units(demo_payload()["units"], 999)["selected_ids"]
    assert response.json()["seed"] == 999
    assert response.json()["relabel_mode"] == "FULL_POPULATION_RESAMPLE"


async def test_lead_who_participates_cannot_read_business_lists_or_peer_jobs(api: tuple[Any, httpx.AsyncClient]) -> None:
    from sqlalchemy import select

    from openkb_s4.models import Job, User
    app, client = api
    _, batch, people = await setup_batch(app, client)
    async with app.state.sessions() as db, db.begin():
        person = await db.get(User, people["a"])
        person.roles = ["lead", "annotator", "auditor"]
        import_job = await db.scalar(select(Job).where(Job.kind == "IMPORT"))
        job_id = import_job.id
    await login(client, "a")
    assert (await client.get("/api/s4/v1/imports")).json()["items"] == []
    assert (await client.get("/api/s4/v1/annotation-batches")).json()["items"] == []
    assert (await client.get("/api/s4/v1/agreements")).json()["items"] == []
    assert (await client.get(f"/api/s4/v1/jobs/{job_id}")).status_code == 403
    assert (await client.get(f"/api/s4/v1/annotation-batches/{batch['id']}")).status_code == 403
    assert (await client.get("/api/s4/v1/audit")).status_code == 403
