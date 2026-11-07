"""Approved configuration evidence survives export, inventory and later retirement."""
import json
from typing import Any

import asyncpg
import pytest
from helpers import login, seed_user
from test_profile_api_v13 import approve_profile, create_profile
from test_v13_workflow import P, review, setup_v13, submit


@pytest.mark.asyncio
async def test_profile_refs_are_exported_backed_up_and_checked_before_reexport(api: Any) -> None:
    from openkb_s4.models_v13 import V13ProfileRevision
    from openkb_s4.services.content_inventory import database_references, verify_controlled_graph
    from openkb_s4.services.content_store import ContentStore
    from openkb_s4.services.handoffs_v13 import export_snapshot_v13
    from openkb_s4.worker import run_once

    app, client, users, headers, imported = await setup_v13(api, 8)
    await seed_user(app, "auditor", ["auditor"])
    profile = await approve_profile(client, headers, await create_profile(client, headers))
    headers = await login(client, "lead")
    created = []
    for kind in ("verification", "observation"):
        body = {"import_id": imported, "dataset": "QA-D1", "profile_revision_id": profile["id"]}
        body.update({"assignee_ids": [users["v"]]} if kind == "verification" else {"annotator_a": users["a"], "annotator_b": users["b"]})
        response = await client.post(P + "/" + kind + "-batches", headers=headers, json=body)
        assert response.status_code == 201, response.text
        created.append(response.json())
    for name in ("v", "a", "b"):
        headers = await login(client, name)
        tasks = (await client.get(P + "/me/tasks")).json()["items"]
        for task in tasks:
            assert (await submit(client, headers, task, {"answer": "synthetic independent", "reason": "source"})).status_code == 200
        if name == "v":
            for task in tasks:
                detail = (await client.get(P + "/assignments/" + task["id"])).json()
                assert (await submit(client, headers, detail, review(detail))).status_code == 200
    headers = await login(client, "lead")
    assert (await client.post(P + f"/observation-batches/{created[1]['id']}/release-review", headers=headers)).status_code == 200
    for name in ("a", "b"):
        headers = await login(client, name)
        for task in (await client.get(P + "/me/tasks")).json()["items"]:
            detail = (await client.get(P + "/assignments/" + task["id"])).json()
            assert (await submit(client, headers, detail, review(detail))).status_code == 200
    headers = await login(client, "lead")
    assert (await client.post(P + f"/observation-batches/{created[1]['id']}/observe", headers=headers)).status_code == 200
    assert (await client.post(P + f"/profile-revisions/{profile['id']}/retire", headers=headers,
            json={"expected_revision": profile["revision"], "reason": "synthetic retirement; preserve original frozen work"})).status_code == 200
    queued = await client.post(P + "/handoffs", headers=headers, json={"import_id": imported})
    assert queued.status_code == 202, queued.text
    assert await run_once(app.state.sessions, app.state.settings)
    job = (await client.get(P + "/jobs/" + queued.json()["job_id"])).json()
    assert job["state"] == "DONE", job
    folder = app.state.settings.data_dir / "exports-v13" / job["result"]["handoff_id"]
    report = json.loads((folder / "s4_report.json").read_text(encoding="utf-8"))
    assert len(report["profile_evidence"]) == 2
    assert {row["profile_revision_id"] for row in report["profile_evidence"]} == {profile["id"]}
    assert {row["profile_hash"] for row in report["profile_evidence"]} == {profile["canonical_hash"]}
    store = ContentStore(app.state.settings.data_dir / "controlled")
    raw = store.read_json(report["raw_evidence_ref"])
    assert raw["profile_evidence"] == report["profile_evidence"]
    connection = await asyncpg.connect(app.state.settings.database_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        roots = await database_references(connection)
    finally:
        await connection.close()
    async with app.state.sessions() as db:
        row = await db.get(V13ProfileRevision, profile["id"])
        assert row is not None
        assert row.approval_ref in roots and row.manual_ref in roots
        assert verify_controlled_graph(store, roots) > 10
        # Only a temporary isolated-test object is removed: corrupt evidence must block reuse.
        (store.root / row.manual_ref["object_key"]).unlink()
    async with app.state.sessions() as db, db.begin():
        with pytest.raises(ValueError):
            await export_snapshot_v13(db, app.state.settings, imported, users["lead"])
