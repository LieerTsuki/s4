"""Real PostgreSQL regression cases for full verification vs sampled observation."""

from typing import Any

import pytest
from helpers import login, seed_user

P = "/api/s4/v2"


def source_payload(count: int = 12) -> dict[str, Any]:
    return {
        "contract_version": "openkb.s3-s4.v2", "mode": "demo",
        "batch_id": "V13-TEST", "source_revision": "r1",
        "units": [{
            "unit_id": f"QA-D1-v13-{i}", "dataset": "QA-D1",
            "difficulty": ["easy", "medium", "hard"][i % 3],
            "question": f"合成服务{i}的期限是什么？",
            "contexts": [{"doc_id": f"doc-{i}", "text": "服务须五日办理。渠道须指定表单。"}],
            "gold": {"answer_points": ["五日办理", "指定表单"],
                     "gold_doc_ids": [f"doc-{i}"], "relevance_grades": {f"doc-{i}": 3},
                     "ranking_annotations": {}, "expected_refusal": False, "absence_reason": None},
            "metadata": {"generation_model": "synthetic-demo"},
        } for i in range(count)],
    }


async def setup_v13(api: Any, count: int = 12) -> tuple[Any, Any, dict[str, str], dict[str, str], str]:
    app, client = api
    users = {name: await seed_user(app, name, roles) for name, roles in {
        "lead": ["lead"], "v": ["annotator"], "a": ["annotator"],
        "b": ["annotator"], "other": ["annotator"], "verifier": ["verifier"],
    }.items()}
    headers = await login(client, "lead")
    response = await client.post(P + "/imports", headers=headers, json=source_payload(count))
    assert response.status_code == 201, response.text
    return app, client, users, headers, response.json()["id"]


def review(detail: dict[str, Any], wrong: bool = False) -> dict[str, Any]:
    from hashlib import sha256
    doc = detail["material"]["contexts"][0]
    locator = {"doc_id": doc["doc_id"], "context_sha256": sha256(doc["text"].encode()).hexdigest(),
               "start": 0, "end": 7, "quote": doc["text"][:7]}
    return {
        "review_version": "openkb.s4-review.v3", "workflow_kind": detail["workflow_kind"],
        "verdict": "NEEDS_REVISION" if wrong else "VERIFIED", "point_labels": {"P001": "correct", "P002": "wrong" if wrong else "correct"},
        "point_reasons": {"P001": "已核原文", "P002": "核对渠道"},
        "point_evidence": {"P001": [locator], "P002": [] if wrong else [locator]},
        "point_search_scope": {"P002": [doc["doc_id"]]} if wrong else {},
        "evidence_assessments": {doc["doc_id"]: {"grade": 3, "reason": "直接支持", "locators": [locator], "intent": "KEEP_GOLD"}},
        "expected_refusal": False, "absence_reason": None,
        "expected_refusal_reason": "材料可答", "reason": "独立核实完成",
        "specialized_review": {},
    }


async def submit(client: Any, headers: dict[str, str], task: dict[str, Any], payload: dict[str, Any]) -> Any:
    return await client.post(P + f"/assignments/{task['id']}/submit", headers={**headers, "Idempotency-Key": task["id"] + task["phase"]},
                             json={"phase": task["phase"], "content_revision": task["content_revision"], "profile_version": task["profile_version"], "payload": payload})


@pytest.mark.asyncio
async def test_v13_all_units_have_main_tasks_and_partial_completion_never_ready(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api)
    response = await client.post(P + "/verification-batches", headers=headers,
                                 json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]})
    assert response.status_code == 201, response.text
    headers = await login(client, "v")
    tasks = (await client.get(P + "/me/tasks?workflow_kind=VERIFICATION")).json()["items"]
    assert len(tasks) == 12
    blind = (await client.get(P + f"/assignments/{tasks[0]['id']}")).json()
    assert "gold" not in blind and "answer_points" not in str(blind)
    assert (await submit(client, headers, tasks[0], {"answer": "独立答案", "reason": "查阅原文"})).status_code == 200
    detail = (await client.get(P + f"/assignments/{tasks[0]['id']}")).json()
    assert detail["phase"] == "REVIEW"
    assert (await submit(client, headers, detail, review(detail))).status_code == 200
    await login(client, "lead")
    report = (await client.get(P + f"/imports/{imported}/report")).json()
    assert report["N"] == 12 and report["verification_completed"] == 1
    assert report["readiness"] != "S4_READY"
    assert "VERIFICATION_INCOMPLETE:11" in report["blockers"]


@pytest.mark.asyncio
async def test_v13_observation_barrier_and_foreign_task_are_server_enforced(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api)
    response = await client.post(P + "/observation-batches", headers=headers,
                                 json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"], "seed": 17})
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["sample_count"] == 8 and batch["N"] == 12
    foreign = ""
    for name in ("a", "b"):
        headers = await login(client, name)
        tasks = (await client.get(P + "/me/tasks")).json()["items"]
        if name == "a":
            foreign = tasks[0]["id"]
        else:
            assert (await client.get(P + f"/assignments/{foreign}")).status_code == 404
        for task in tasks[:8 if name == "a" else 7]:
            assert (await submit(client, headers, task, {"answer": "本人独立结论", "reason": "查原文"})).status_code == 200
    headers = await login(client, "lead")
    assert (await client.post(P + f"/observation-batches/{batch['id']}/release-review", headers=headers)).status_code == 409
    headers = await login(client, "b")
    task = (await client.get(P + "/me/tasks")).json()["items"][-1]
    assert (await submit(client, headers, task, {"answer": "本人独立结论", "reason": "查原文"})).status_code == 200
    headers = await login(client, "lead")
    assert (await client.post(P + f"/observation-batches/{batch['id']}/release-review", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_v13_source_and_submissions_are_only_content_references_in_database(api: Any) -> None:
    from sqlalchemy import select

    from openkb_s4.models_v13 import V13Import, V13Unit
    app, _, _, _, imported = await setup_v13(api)
    async with app.state.sessions() as db:
        source = await db.get(V13Import, imported)
        assert source is not None and set(source.source_ref) == {"object_key", "sha256"}
        unit = await db.scalar(select(V13Unit).where(V13Unit.import_id == imported))
        assert unit is not None
        assert set(unit.material_ref) == {"object_key", "sha256"}
        assert "五日办理" not in str(source.__dict__) + str(unit.__dict__)


@pytest.mark.asyncio
async def test_v13_draft_revision_and_submission_idempotence(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api)
    assert (await client.post(P + "/verification-batches", headers=headers, json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]})).status_code == 201
    headers = await login(client, "v")
    task = (await client.get(P + "/me/tasks")).json()["items"][0]
    url = P + f"/assignments/{task['id']}/draft"
    body = {"phase": "BLIND", "version": 0, "payload": {"answer": "草稿"}}
    assert (await client.patch(url, headers=headers, json=body)).status_code == 200
    assert (await client.patch(url, headers=headers, json=body)).status_code == 409
    payload = {"answer": "独立答案", "reason": "原文"}
    first = await submit(client, headers, task, payload)
    second = await submit(client, headers, task, payload)
    assert first.status_code == second.status_code == 200 and first.json()["id"] == second.json()["id"]
    assert (await submit(client, headers, task, {"answer": "改写", "reason": "原文"})).status_code == 409


@pytest.mark.asyncio
async def test_v13_uploaded_drafts_disqualify_observer_and_small_sample_records_shortfall(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api, 2)
    forbidden = await client.post(P + "/observation-batches", headers=headers, json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["lead"], "annotator_b": users["b"]})
    assert forbidden.status_code in {403, 422}
    response = await client.post(P + "/observation-batches", headers=headers, json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"]})
    assert response.status_code == 201, response.text
    assert response.json()["sample_ledger"]["shortfall"] == 6


