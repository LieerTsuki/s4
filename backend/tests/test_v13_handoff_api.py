"""Real worker publishes N/n versioned packages and never fabricates S5 receipt."""
from typing import Any

import pytest
from helpers import login
from test_v13_workflow import P, review, setup_v13, submit


@pytest.mark.asyncio
async def test_full_verification_and_observation_publish_v2_with_real_worker(api: Any) -> None:
    from openkb_s4.worker import run_once

    app, client, users, headers, imported = await setup_v13(api, 12)
    obs = await client.post(P + "/observation-batches", headers=headers,
                            json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"]})
    assert obs.status_code == 201, obs.text
    main = await client.post(P + "/verification-batches", headers=headers,
                             json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]})
    assert main.status_code == 201, main.text
    pending = await client.post(P + "/handoffs", headers=headers, json={"import_id": imported})
    assert pending.status_code == 409
    for name in ("v", "a", "b"):
        headers = await login(client, name)
        tasks = (await client.get(P + "/me/tasks")).json()["items"]
        for task in tasks:
            assert (await submit(client, headers, task, {"answer": "本人独立答案", "reason": "原文核查"})).status_code == 200
        if name == "v":
            for task in tasks:
                detail = (await client.get(P + f"/assignments/{task['id']}")).json()
                assert (await submit(client, headers, detail, review(detail))).status_code == 200
    headers = await login(client, "lead")
    assert (await client.post(P + f"/observation-batches/{obs.json()['id']}/release-review", headers=headers)).status_code == 200
    for name in ("a", "b"):
        headers = await login(client, name)
        tasks = (await client.get(P + "/me/tasks")).json()["items"]
        for task in tasks:
            detail = (await client.get(P + f"/assignments/{task['id']}")).json()
            assert (await submit(client, headers, detail, review(detail))).status_code == 200
    headers = await login(client, "lead")
    response = await client.post(P + f"/observation-batches/{obs.json()['id']}/observe", headers=headers)
    assert response.status_code == 200, response.text
    response = await client.post(P + "/handoffs", headers=headers, json={"import_id": imported})
    assert response.status_code == 202, response.text
    assert await run_once(app.state.sessions, app.state.settings)
    job = (await client.get(P + "/jobs/" + response.json()["job_id"])).json()
    assert job["state"] == "DONE", job
    identity = job["result"]["handoff_id"]
    handoff = (await client.get(P + "/handoffs/" + identity)).json()
    assert handoff["manifest"]["unit_count"] == 12
    assert handoff["manifest"]["sample_count"] == 8
    assert handoff["manifest"]["formal_credential"] is False
    file = await client.get(P + f"/handoffs/{identity}/files/verified_annotations.jsonl")
    assert file.status_code == 200 and len(file.text.splitlines()) == 12
    evidence = {"idempotency_key": "manual-delivery-1", "snapshot_hash": handoff["snapshot_hash"],
                "destination_ref": "receiver:local-demo", "evidence_ref": "evidence:test-delivery", "evidence_sha256": "a" * 64}
    sent = await client.post(P + f"/handoffs/{identity}/sent", headers=headers, json=evidence)
    assert sent.status_code == 200, sent.text
    again = await client.post(P + f"/handoffs/{identity}/sent", headers=headers, json=evidence)
    assert again.json() == sent.json()
    assert (await client.post(P + f"/handoffs/{identity}/sent", headers=headers, json={**evidence, "evidence_sha256": "b" * 64})).status_code == 409
    calibration = await client.post(P + "/quality-actions", headers=headers,
        json={"batch_id": obs.json()["id"], "kind": "CALIBRATION", "reason": "补充实际口径会记录", "evidence": {"report": "synthetic-calibration"}})
    assert calibration.status_code == 201, calibration.text
    queued_again = await client.post(P + "/handoffs", headers=headers, json={"import_id": imported})
    assert queued_again.status_code == 202
    assert queued_again.json()["job_id"] != response.json()["job_id"]
    assert await run_once(app.state.sessions, app.state.settings)
    regenerated = (await client.get(P + "/jobs/" + queued_again.json()["job_id"])).json()
    assert regenerated["state"] == "DONE", regenerated
    assert regenerated["result"]["handoff_id"] != identity
    returned = await client.post(P + "/quality-actions", headers=headers,
        json={"batch_id": main.json()["id"], "kind": "RETURN_TO_S2", "reason": "发送后复核发现需退回", "evidence": {"report": "synthetic"}})
    assert returned.status_code == 201, returned.text
    assert (await client.post(P + f"/handoffs/{identity}/sent", headers=headers,
        json={**evidence, "idempotency_key": "new-send-after-return"})).status_code == 409
    assert (await client.post(P + f"/handoffs/{identity}/sent", headers=headers, json=evidence)).json() == sent.json()
    await login(client, "a")
    assert (await client.get(P + f"/handoffs/{identity}/files/verified_annotations.jsonl")).status_code in {403, 404}
    assert (await client.post(P + f"/handoffs/{identity}/receipts", json={})).status_code == 403
