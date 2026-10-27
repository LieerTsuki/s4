"""The runtime role must perform the whole workflow without mutating sealed data."""
import asyncio
from typing import Any

import httpx
from helpers import demo_payload, login, seed_user
from sqlalchemy import text
from test_handoffs import ready_snapshot


async def test_restricted_runtime_role_can_complete_workflow_without_owner_permissions(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    async with app.state.sessions() as db:
        privileges = (await db.execute(text("SELECT has_table_privilege(current_user, 'source_imports', 'UPDATE'), has_table_privilege(current_user, 'submissions', 'DELETE'), has_table_privilege(current_user, 'agreements', 'UPDATE'), has_table_privilege(current_user, 'final_decisions', 'UPDATE'), has_table_privilege(current_user, 'audit_events', 'DELETE')"))).one()
        assert not any(privileges), "Run this regression with the restricted application role"
    _, _, handoff = await ready_snapshot(app, client)
    assert handoff["status"] == "DEMO_READY"


async def test_runtime_scope_lock_serializes_duplicate_batch_creation(api: tuple[Any, httpx.AsyncClient]) -> None:
    from openkb_s4.worker import run_once
    app, client = api
    await seed_user(app, "lead", ["lead"])
    a, b = await seed_user(app, "a", ["annotator"]), await seed_user(app, "b", ["annotator"])
    headers = await login(client, "lead")
    response = await client.post("/api/s4/v1/imports", headers=headers, json=demo_payload())
    await run_once(app.state.sessions, app.state.settings)
    imported = (await client.get(f"/api/s4/v1/jobs/{response.json()['job_id']}")).json()["result"]["import_id"]
    body = {"import_id": imported, "dataset": "QA-D1", "annotator_a": a, "annotator_b": b, "seed": 1}
    responses = await asyncio.gather(*(client.post("/api/s4/v1/annotation-batches", headers=headers, json=body) for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()["error_code"] == "SCOPE_ALREADY_PLANNED"
    assert (await client.get("/api/s4/v1/annotation-batches")).json()["total"] == 1
