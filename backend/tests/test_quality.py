"""Human quality gates over immutable pairs, including grey and rejected batches."""
from typing import Any

import httpx
import pytest
from helpers import calibration, demo_payload, finish_reviews, login, seed_user
from test_workflow import setup_batch


def decisions(batch: dict[str, Any]) -> list[dict[str, Any]]:
    units = {unit["unit_id"]: unit for unit in demo_payload()["units"]}
    return [{"unit_id": unit_id, "final_gold": units[unit_id]["gold"], "reason": "reviewed all original source material"} for unit_id in batch["selected_ids"]]


@pytest.mark.parametrize(("flips", "verdict"), [(0, "ACCEPT"), (3, "ARBITRATE"), (8, "REJECT_BATCH")])
async def test_quality_requires_human_finalization_and_preserves_original_result(api: tuple[Any, httpx.AsyncClient], flips: int, verdict: str) -> None:
    app, client = api
    _, batch, people = await setup_batch(app, client)
    headers, agreement = await finish_reviews(app, client, batch, flips)
    assert agreement["verdict"] == verdict
    body = {"decisions": decisions(batch)}
    url = f"/api/s4/v1/annotation-batches/{batch['id']}/finalize"
    # N/n export cannot run until all sampled content decisions are made.
    job = (await client.post("/api/s4/v1/handoffs", headers=headers, json={"import_id": batch["import_id"]})).json()
    from openkb_s4.worker import run_once
    await run_once(app.state.sessions, app.state.settings)
    status = (await client.get(f"/api/s4/v1/jobs/{job['job_id']}")).json()
    assert status["state"] == "FAILED" and status["error_code"] == "ALL_BATCHES_REQUIRED"
    if verdict == "REJECT_BATCH":
        assert (await client.post(url, headers=headers, json=body)).status_code == 409
        fresh_a = await seed_user(app, "fresh_a", ["annotator"])
        fresh_b = await seed_user(app, "fresh_b", ["annotator"])
        calibration_id=await calibration(client,headers,batch)
        invalid = await client.post("/api/s4/v1/rounds", headers=headers, json={"calibration_id":calibration_id,"batch_id": batch["id"], "annotator_a": people["a"], "annotator_b": fresh_b, "seed": 7, "reason": "calibration"})
        assert invalid.status_code == 409 and invalid.json()["error_code"] == "PREVIOUS_EXPOSURE"
        valid = await client.post("/api/s4/v1/rounds", headers=headers, json={"calibration_id":calibration_id,"batch_id": batch["id"], "annotator_a": fresh_a, "annotator_b": fresh_b, "seed": 7, "reason": "calibration with the whole frozen sample"})
        assert valid.status_code == 201, valid.text
        assert valid.json()["round"] == 2
        assert valid.json()["sample_count"] == batch["sample_count"]
        assert valid.json()["seed"] == 7
    elif verdict == "ARBITRATE":
        assert (await client.post(url, headers=headers, json=body)).json()["error_code"] == "ARBITRATION_INCOMPLETE"
        judge_headers = await login(client, "judge")
        arbitration_ids = []
        for decision in body["decisions"]:
            if decision["unit_id"] not in agreement["disagreement_unit_ids"]:
                continue
            response = await client.post("/api/s4/v1/arbitrations", headers=judge_headers, json={**decision, "batch_id": batch["id"]})
            assert response.status_code == 201, response.text
            arbitration_ids.append(response.json()["id"])
        headers = await login(client, "lead")
        for arbitration_id in arbitration_ids:
            assert (await client.post(f"/api/s4/v1/arbitrations/{arbitration_id}/confirm", headers=headers, json={"reason": "independent lead reviewed source"})).status_code == 200
        assert (await client.post(url, headers=headers, json=body)).json()["state"] == "S4_READY"
    else:
        assert (await client.post(url, headers=headers, json={"decisions": body["decisions"][:-1]})).status_code == 422
        response = await client.post(url, headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "S4_READY"
        assert (await client.post(url, headers=headers, json=body)).status_code == 409
    original = (await client.get("/api/s4/v1/agreements")).json()["items"][0]
    assert original["kappa"] == agreement["kappa"]
    assert original["verdict"] == agreement["verdict"]
    await login(client, "a")
    assert (await client.get(f"/api/s4/v1/annotation-batches/{batch['id']}")).status_code == 403
    assert (await client.get("/api/s4/v1/agreements")).status_code == 403


async def test_final_gold_rejects_fabricated_source_ids(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    _, batch, _ = await setup_batch(app, client)
    headers, _ = await finish_reviews(app, client, batch)
    body = {"decisions": decisions(batch)}
    body["decisions"][0]["final_gold"] = {"answerable": "answerable", "answer_points": ["confirmed"], "gold_doc_ids": ["nonexistent-document"]}
    response = await client.post(f"/api/s4/v1/annotation-batches/{batch['id']}/finalize", headers=headers, json=body)
    assert response.status_code == 422
