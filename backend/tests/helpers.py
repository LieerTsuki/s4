"""Test-only setup and API fixtures."""

from typing import Any

import httpx


async def seed_user(app: Any, name: str, roles: list[str]) -> str:
    from openkb_s4.models import User
    from openkb_s4.security import hash_password

    async with app.state.sessions() as db, db.begin():
        user = User(
            username=name,
            display_name=name,
            person_id=f"person-{name}",
            roles=roles,
            password_hash=hash_password("test-password-strong"),
        )
        db.add(user)
        await db.flush()
        return str(user.id)


async def login(client: httpx.AsyncClient, name: str) -> dict[str, str]:
    response = await client.post(
        "/api/s4/v1/auth/login", json={"username": name, "password": "test-password-strong"}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def demo_payload(count: int = 12) -> dict[str, Any]:
    return {
        "contract_version": "openkb.s3-s4.v1",
        "mode": "demo",
        "batch_id": "DEMO-API-001",
        "source_revision": "r1",
        "units": [
            {
                "unit_id": f"QA-D1-{i:04}",
                "dataset": "QA-D1",
                "difficulty": ["简单", "中等", "困难"][i % 3],
                "question": f"第{i}条演示材料的审核结论是什么？",
                "gold": {
                    "answer_points": ["演示正确要点", "演示待修订要点"],
                    "gold_doc_ids": [f"doc-{i}"],
                    "answerable": "answerable",
                },
                "contexts": [
                    {
                        "doc_id": f"doc-{i}",
                        "text": "仅供本地演示的合成原文，包含足够审核范围。",
                        "title": "合成演示原文",
                    }
                ],
                "metadata": {"generation_model": "synthetic-demo"},
            }
            for i in range(count)
        ],
    }


async def finish_reviews(
    app: Any, client: httpx.AsyncClient, batch: dict[str, Any], flips: int = 0
) -> tuple[dict[str, str], dict[str, Any]]:
    """Exercise every actual stage; flips changes B's first point on N units."""
    from openkb_s4.worker import run_once

    for name in ("a", "b"):
        headers = await login(client, name)
        tasks = (await client.get("/api/s4/v1/me/tasks")).json()["items"]
        for task in tasks:
            response = await client.post(
                f"/api/s4/v1/assignments/{task['id']}/submit",
                headers={**headers, "Idempotency-Key": "blind-" + task["id"]},
                json={
                    "phase": "BLIND",
                    "content_revision": task["content_revision"],
                    "profile_version": task["profile_version"],
                    "payload": {"answer": "independent answer", "reason": "source text"},
                },
            )
            assert response.status_code == 200, response.text
    headers = await login(client, "lead")
    assert (
        await client.post(
            f"/api/s4/v1/annotation-batches/{batch['id']}/release-review", headers=headers
        )
    ).status_code == 200
    for name in ("a", "b"):
        headers = await login(client, name)
        tasks = (await client.get("/api/s4/v1/me/tasks")).json()["items"]
        for index, task in enumerate(tasks):
            detail = (await client.get(f"/api/s4/v1/assignments/{task['id']}")).json()
            response = await client.post(
                f"/api/s4/v1/assignments/{task['id']}/submit",
                headers={**headers, "Idempotency-Key": "review-" + task["id"]},
                json={
                    "phase": "REVIEW",
                    "content_revision": task["content_revision"],
                    "profile_version": task["profile_version"],
                    "profile_hash": detail["profile_hash"],
                    "payload": review_v2(
                        detail,
                        {
                            "P001": "wrong" if name == "b" and index < flips else "correct",
                            "P002": "wrong",
                        },
                    ),
                },
            )
            assert response.status_code == 200, response.text
    headers = await login(client, "lead")
    response = await client.post(
        f"/api/s4/v1/annotation-batches/{batch['id']}/agreement", headers=headers
    )
    assert response.status_code == 202, response.text
    await run_once(app.state.sessions, app.state.settings)
    job = (await client.get(f"/api/s4/v1/jobs/{response.json()['job_id']}")).json()
    assert job["state"] == "DONE", job
    agreements = (await client.get("/api/s4/v1/agreements")).json()["items"]
    return headers, next(row for row in agreements if row["batch_id"] == batch["id"])


def review_v2(detail: dict[str, Any], labels: dict[str, str] | None = None) -> dict[str, Any]:
    """Explicit synthetic fixture observations, created only by test annotators."""
    docs = detail["gold"]["gold_doc_ids"]
    points = {point["point_key"]: "correct" for point in detail["points"]}
    if labels is not None:
        points = labels
    locators = [{"doc_id": doc, "start": 0, "end": 5} for doc in docs]
    return {
        "review_version": "openkb.s4-review.v2",
        "point_labels": points,
        "point_reasons": {key: "synthetic test observation: inspected source" for key in points},
        "point_evidence": {key: locators for key in points},
        "evidence_labels": {doc: 2 for doc in docs},
        "evidence_reasons": {doc: "synthetic test source supports answer" for doc in docs},
        "answerable": detail["gold"]["answerable"],
        "answerable_reason": "synthetic source reviewed",
        "reason": "synthetic test review",
        "suggested_points": [],
        "evidence_changes": [],
    }


async def calibration(
    client: httpx.AsyncClient, headers: dict[str, str], batch: dict[str, Any]
) -> str:
    response = await client.post(
        "/api/s4/v1/calibrations",
        headers=headers,
        json={
            "batch_id": batch["id"],
            "meeting_at": "2026-10-28T00:00:00Z",
            "participant_ids": [batch["annotator_a"], batch["annotator_b"]],
            "case_refs": [batch["selected_ids"][0]],
            "decisions": "synthetic test calibration: review complete scope",
            "manual_version": batch["manual_version"],
            "training_refs": ["synthetic-test-training"],
            "reason": "synthetic test full-batch relabel calibration",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])
