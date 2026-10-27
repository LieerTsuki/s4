"""Malformed client values produce safe structured errors, never tracebacks."""
from typing import Any

import httpx
import pytest
from helpers import login
from test_workflow import setup_batch


@pytest.mark.parametrize("payload", [{"units": None}, {"units": "not-an-array"}])
async def test_import_shape_is_rejected_safely_before_exposure_scan(api: tuple[Any, httpx.AsyncClient], payload: dict[str, Any]) -> None:
    app, client = api
    from helpers import seed_user
    await seed_user(app, "lead", ["lead"])
    headers = await login(client, "lead")
    response = await client.post("/api/s4/v1/imports", headers=headers, json=payload)
    assert response.status_code == 422
    assert response.json()["request_id"]


async def test_unknown_dataset_returns_domain_error_as_422(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    headers, batch, people = await setup_batch(app, client)
    response = await client.post("/api/s4/v1/annotation-batches", headers=headers, json={"import_id": batch["import_id"], "dataset": "bogus", "annotator_a": people["a"], "annotator_b": people["b"], "seed": 5})
    assert response.status_code == 422
    assert "request_id" in response.json()


@pytest.mark.parametrize("answer", [None, [], {}, 5, True])
async def test_blind_does_not_coerce_structured_values_into_human_answers(api: tuple[Any, httpx.AsyncClient], answer: Any) -> None:
    app, client = api
    _, _, _ = await setup_batch(app, client)
    headers = await login(client, "a")
    task = (await client.get("/api/s4/v1/me/tasks")).json()["items"][0]
    response = await client.post(f"/api/s4/v1/assignments/{task['id']}/submit", headers={**headers, "Idempotency-Key": "invalid"}, json={"phase": "BLIND", "content_revision": task["content_revision"], "profile_version": task["profile_version"], "payload": {"answer": answer, "reason": "source"}})
    assert response.status_code == 422


@pytest.mark.parametrize("value", [[], {}, True, 1])
def test_malformed_review_label_is_rejected_as_business_validation(value: Any) -> None:
    from helpers import demo_payload

    from openkb_s4.security import ApiError
    from openkb_s4.services.common import validate_review
    unit = demo_payload()["units"][0]
    with pytest.raises(ApiError) as error:
        validate_review(unit, {"point_labels": {"P001": value, "P002": "wrong"}, "evidence_labels": {"doc-0": 2}, "answerable": "answerable", "reason": "source"})
    assert error.value.status == 422


@pytest.mark.parametrize("evidence", [{"doc-0": True}, {"doc-0": 3}, {"doc-0": 2.0}, {}, {"doc-0": 2, "extra": 0}])
def test_evidence_requires_exact_original_keys_and_integer_2_1_0(evidence: dict[str, Any]) -> None:
    from helpers import demo_payload

    from openkb_s4.security import ApiError
    from openkb_s4.services.common import validate_review
    with pytest.raises(ApiError) as error:
        validate_review(demo_payload()["units"][0], {"point_labels": {"P001": "correct", "P002": "wrong"}, "evidence_labels": evidence, "answerable": "answerable", "reason": "source"})
    assert error.value.code == "EVIDENCE_LABELS_INVALID"
