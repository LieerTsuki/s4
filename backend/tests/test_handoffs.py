"""Durable export publication, separated N/n and independent digest verification."""
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from helpers import demo_payload, finish_reviews, login, seed_user
from test_quality import decisions
from test_workflow import setup_batch


async def ready_snapshot(app: Any, client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    from openkb_s4.worker import run_once
    _, batch, _ = await setup_batch(app, client)
    headers, _ = await finish_reviews(app, client, batch)
    response = await client.post(f"/api/s4/v1/annotation-batches/{batch['id']}/finalize", headers=headers, json={"decisions": decisions(batch)})
    assert response.status_code == 200, response.text
    response = await client.post("/api/s4/v1/handoffs", headers=headers, json={"import_id": batch["import_id"]})
    assert response.status_code == 202, response.text
    await run_once(app.state.sessions, app.state.settings)
    job = (await client.get(f"/api/s4/v1/jobs/{response.json()['job_id']}")).json()
    assert job["state"] == "DONE", job
    handoff = (await client.get(f"/api/s4/v1/handoffs/{job['result']['handoff_id']}")).json()
    return headers, batch, handoff


async def test_n_n_snapshot_is_complete_idempotent_and_not_external_acceptance(api: tuple[Any, httpx.AsyncClient]) -> None:
    from openkb_s4.worker import run_once
    app, client = api
    headers, batch, handoff = await ready_snapshot(app, client)
    assert handoff["status"] == "DEMO_READY"
    assert handoff["external_status"] == "NOT_ALIGNED"
    manifest = handoff["manifest"]
    assert manifest["unit_count"] == 12 and manifest["sample_count"] == 8
    assert "s4_handoff_manifest.json" not in manifest["files"]
    full = (await client.get(f"/api/s4/v1/handoffs/{handoff['id']}/files/units_for_s5.jsonl")).text.splitlines()
    labeled = (await client.get(f"/api/s4/v1/handoffs/{handoff['id']}/files/labeled.jsonl")).text.splitlines()
    assert len(full) == 12 and len(labeled) == 8
    unsampled = [json.loads(row) for row in full if json.loads(row)["unit_id"] not in batch["selected_ids"]]
    assert len(unsampled) == 4
    assert all("s4_revision" not in row["metadata"] for row in unsampled)
    for name in manifest["files"]:
        assert (await client.get(f"/api/s4/v1/handoffs/{handoff['id']}/files/{name}")).status_code == 200
    assert (await client.get(f"/api/s4/v1/handoffs/{handoff['id']}/files/s4_handoff_manifest.json")).json() == manifest
    response = await client.post("/api/s4/v1/handoffs", headers=headers, json={"import_id": batch["import_id"]})
    await run_once(app.state.sessions, app.state.settings)
    job = (await client.get(f"/api/s4/v1/jobs/{response.json()['job_id']}")).json()
    assert job["result"]["handoff_id"] == handoff["id"]
    assert (await client.get("/api/s4/v1/handoffs")).json()["total"] == 1
    assert (await client.post(f"/api/s4/v1/handoffs/{handoff['id']}/receipt", json={"snapshot_hash": handoff["snapshot_hash"], "contract_version": "openkb.s4-s5.v1", "status": "S5_ACCEPTED", "reason": "test"})).status_code == 403
    app.state.settings.receipt_token = "unit-test-service-scope"
    assert (await client.post(f"/api/s4/v1/handoffs/{handoff['id']}/receipt", headers={"Authorization": "Bearer unit-test-service-scope"}, json={"snapshot_hash": handoff["snapshot_hash"], "contract_version": "openkb.s4-s5.v1", "status": "S5_ACCEPTED", "reason": "test"})).json()["error_code"] == "EXTERNAL_CONTRACT_NOT_ALIGNED"


@pytest.mark.parametrize("filename", ["labeled.jsonl", "s4_handoff_manifest.json"])
async def test_tampered_snapshot_is_rejected_on_download(api: tuple[Any, httpx.AsyncClient], filename: str) -> None:
    app, client = api
    _, _, handoff = await ready_snapshot(app, client)
    directory: Path = app.state.settings.data_dir / "exports" / handoff["id"]
    (directory / filename).write_text("{}\n", encoding="utf-8")
    response = await client.get(f"/api/s4/v1/handoffs/{handoff['id']}/files/{filename}")
    assert response.status_code == 409
    assert response.json()["error_code"] in {"CHECKSUM_MISMATCH", "MANIFEST_MISMATCH"}


async def test_snapshot_reader_cannot_blind_review_unsampled_units_later(api: tuple[Any, httpx.AsyncClient]) -> None:
    from openkb_s4.worker import run_once
    app, client = api
    _, batch, handoff = await ready_snapshot(app, client)
    reader_id = await seed_user(app, "reader", ["lead", "annotator"])
    fresh_id = await seed_user(app, "fresh", ["annotator"])
    await login(client, "reader")
    assert (await client.get(f"/api/s4/v1/handoffs/{handoff['id']}/files/units_for_s5.jsonl")).status_code == 200
    headers = await login(client, "lead")
    payload = demo_payload()
    payload["batch_id"] = "UNSAMPLED-REVISION"
    payload["units"] = [u for u in payload["units"] if u["unit_id"] not in batch["selected_ids"]]
    response = await client.post("/api/s4/v1/imports", headers=headers, json=payload)
    await run_once(app.state.sessions, app.state.settings)
    imported = (await client.get(f"/api/s4/v1/jobs/{response.json()['job_id']}")).json()["result"]["import_id"]
    response = await client.post("/api/s4/v1/annotation-batches", headers=headers, json={"import_id": imported, "dataset": "QA-D1", "annotator_a": reader_id, "annotator_b": fresh_id, "seed": 2})
    assert response.status_code == 409
    assert response.json()["error_code"] == "PREVIOUS_EXPOSURE"
