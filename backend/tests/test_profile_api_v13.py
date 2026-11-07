"""Real PostgreSQL lifecycle, controlled-body storage and batch immutability."""
import asyncio
import json
from typing import Any

import pytest
from helpers import login, seed_user
from sqlalchemy import select
from test_v13_workflow import P, review, setup_v13, source_payload, submit


async def create_profile(client: Any, headers: dict[str, str], version: str = "local-profile-1") -> dict[str, Any]:
    response = await client.get(P + "/profile-revisions/template?dataset=QA-D1")
    assert response.status_code == 200, response.text
    snapshot = response.json()
    snapshot.update(version=version, manual_version="local-manual-1", manual_text="SENSITIVE manual body")
    body = {"dataset": "QA-D1", "version": version, "manual_version": "local-manual-1",
            "snapshot": snapshot, "reason": "SENSITIVE draft reason"}
    response = await client.post(P + "/profile-revisions", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def approve_profile(client: Any, lead_headers: dict[str, str], item: dict[str, Any]) -> dict[str, Any]:
    base = P + "/profile-revisions/" + item["id"]
    response = await client.post(base + "/submit", headers=lead_headers,
                                json={"expected_revision": item["revision"], "reason": "submit for review"})
    assert response.status_code == 200, response.text
    auditor_headers = await login(client, "auditor")
    response = await client.post(base + "/approve", headers=auditor_headers,
        json={"expected_revision": response.json()["revision"], "reason": "SENSITIVE approval reason",
              "signature": "SYNTHETIC TEST auditor signature", "evidence": {"basis": "SENSITIVE synthetic local review"}})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_v13_profile_lifecycle_freezes_batches_and_retains_external_blockers(api: Any):
    from openkb_s4.models_v13 import V13Batch, V13ProfileEvent, V13ProfileRevision
    from openkb_s4.services.workflow_v13 import assert_frozen_profile

    app, client, users, headers, imported = await setup_v13(api, 2)
    await seed_user(app, "auditor", ["auditor"])
    item = await create_profile(client, headers)
    item = await approve_profile(client, headers, item)
    assert item["state"] == "APPROVED" and item["snapshot"]["formal_enabled"] is False
    assert item["snapshot"]["blocked_reasons"]
    headers = await login(client, "lead")
    batch_body = {"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]], "profile_revision_id": item["id"]}
    response = await client.post(P + "/verification-batches", headers=headers, json=batch_body)
    assert response.status_code == 201, response.text
    frozen = response.json()
    assert frozen["profile_hash"] == item["canonical_hash"]
    assert frozen["profile_version"] == item["version"]
    assert frozen["manual_version"] == item["manual_version"]
    second = await create_profile(client, headers, "local-profile-2")
    await approve_profile(client, headers, second)
    headers = await login(client, "lead")
    response = await client.post(P + "/profile-revisions/" + item["id"] + "/retire", headers=headers,
                                 json={"expected_revision": item["revision"], "reason": "retire"})
    assert response.status_code == 200, response.text
    old = (await client.get(P + "/batches/" + frozen["id"])).json()
    assert old["frozen_hash"] == frozen["frozen_hash"] and old["profile_hash"] == frozen["profile_hash"]
    async with app.state.sessions() as db:
        batch = await db.get(V13Batch, frozen["id"])
        await assert_frozen_profile(db, batch)
        profile = await db.get(V13ProfileRevision, item["id"])
        records = (await db.scalars(select(V13ProfileEvent))).all()
        stored = [{column.name: getattr(row, column.name) for column in row.__table__.columns}
                  for row in [profile, *records]]
        assert "SENSITIVE" not in json.dumps(stored, default=str)
    new_payload = source_payload(2)
    new_payload["batch_id"] = "new-source-after-retirement"
    imported2 = (await client.post(P + "/imports", headers=headers, json=new_payload)).json()["id"]
    response = await client.post(P + "/verification-batches", headers=headers, json={**batch_body, "import_id": imported2})
    assert response.status_code == 409 and response.json()["error_code"] == "PROFILE_NOT_APPROVED"
    response = await client.post(P + "/batches/" + frozen["id"] + "/new-round", headers=headers,
                                 json={"assignee_ids": [users["other"]], "reason": "new round"})
    assert response.status_code == 409 and response.json()["error_code"] == "PROFILE_NOT_APPROVED"
    # Retirement cannot erase or disable the already frozen human work.
    headers = await login(client, "v")
    tasks = (await client.get(P + "/me/tasks")).json()["items"]
    for task in tasks:
        detail = (await client.get(P + "/assignments/" + task["id"])).json()
        assert detail["profile_guidance"] == {
            "title": item["snapshot"]["title"], "instructions": item["snapshot"]["instructions"],
            "manual_version": item["manual_version"], "manual_text": item["snapshot"]["manual_text"],
            "snapshot_sha256": item["canonical_hash"]}
        assert "signature" not in json.dumps(detail)
        assert (await submit(client, headers, task, {"answer": "independent", "reason": "source"})).status_code == 200
        detail = (await client.get(P + "/assignments/" + task["id"])).json()
        assert (await submit(client, headers, detail, review(detail))).status_code == 200


@pytest.mark.asyncio
async def test_v13_profile_roles_concurrency_and_submitted_snapshot_are_immutable(api: Any):
    app, client = api
    await seed_user(app, "lead", ["lead", "auditor"])
    await seed_user(app, "auditor", ["auditor"])
    headers = await login(client, "lead")
    item = await create_profile(client, headers)
    base = P + "/profile-revisions/" + item["id"]
    responses = await asyncio.gather(*[client.post(base + "/submit", headers=headers,
        json={"expected_revision": 1, "reason": "concurrent review"}) for _ in range(2)])
    assert sorted(response.status_code for response in responses) == [200, 409]
    response = await client.post(base + "/approve", headers=headers,
        json={"expected_revision": 2, "reason": "self approval", "signature": "self", "evidence": {"basis": "x"}})
    assert response.status_code == 403 and response.json()["error_code"] == "INDEPENDENT_APPROVAL_REQUIRED"
    response = await client.patch(base, headers=headers, json={"dataset": item["dataset"], "version": item["version"],
        "manual_version": item["manual_version"], "snapshot": item["snapshot"], "expected_revision": 2, "reason": "edit submitted"})
    assert response.status_code == 409 and response.json()["error_code"] == "PROFILE_IMMUTABLE"
    headers = await login(client, "auditor")
    response = await client.post(base + "/submit", headers=headers, json={"expected_revision": 2, "reason": "wrong role"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_v13_frozen_manual_file_tamper_blocks_work_without_changing_profile_state(api: Any):
    from openkb_s4.models_v13 import V13ProfileRevision

    app, client, users, headers, imported = await setup_v13(api, 1)
    await seed_user(app, "auditor", ["auditor"])
    item = await create_profile(client, headers)
    item = await approve_profile(client, headers, item)
    headers = await login(client, "lead")
    response = await client.post(P + "/verification-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]], "profile_revision_id": item["id"]})
    assert response.status_code == 201, response.text
    async with app.state.sessions() as db:
        row = await db.get(V13ProfileRevision, item["id"])
        path = app.state.settings.data_dir / "controlled" / row.manual_ref["object_key"]
        path.write_text('{"text":"tampered manual"}', encoding="utf-8")
    headers = await login(client, "v")
    task = (await client.get(P + "/me/tasks")).json()["items"][0]
    response = await submit(client, headers, task, {"answer": "independent", "reason": "source"})
    assert response.status_code == 409 and response.json()["error_code"] == "CONTROLLED_OBJECT_INVALID"
