"""Controlled UTF-8 JSONL and independently scoped S3 service ingress."""

import json
from hashlib import sha256

from helpers import demo_payload, login, seed_user


async def test_jsonl_upload_normalizes_reports_but_never_reads_client_paths(api):
    app, c = api
    await seed_user(app, "lead", ["lead"])
    h = await login(c, "lead")
    payload = demo_payload()
    raw = "\n".join(json.dumps(unit, ensure_ascii=False) for unit in payload.pop("units")) + "\n"
    response = await c.post(
        "/api/s4/v1/imports/upload",
        headers=h,
        json={
            "filename": "synthetic.jsonl",
            "units_jsonl": raw,
            "envelope": payload,
            "source_index": {},
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["raw_file_sha256"] == sha256(raw.encode("utf-8")).hexdigest()
    assert response.json()["normalized_sha256"] != response.json()["raw_file_sha256"]
    assert response.json()["validation_report"]["valid"] is True
    invalid = await c.post(
        "/api/s4/v1/imports/upload",
        headers=h,
        json={"filename": "../secret.jsonl", "units_jsonl": raw, "envelope": payload},
    )
    assert invalid.status_code == 422
    malformed = await c.post(
        "/api/s4/v1/imports/upload",
        headers=h,
        json={"filename": "invalid.jsonl", "units_jsonl": "{bad json}\n", "envelope": payload},
    )
    assert malformed.status_code == 422
    errors = malformed.json()["details"]["validation_report"]["errors"]
    assert errors[0]["row"] == 1 and errors[0]["error_code"] == "JSONL_PARSE_ERROR"


async def test_service_import_credential_has_only_ingress_scope_and_bound_actor(api):
    app, c = api
    service = await seed_user(app, "s3_service", ["lead"])
    app.state.settings.import_token = "test-only-s3-import-token"
    app.state.settings.receipt_token = "test-only-s5-receipt-token"
    app.state.settings.import_service_user_id = service
    payload = demo_payload()
    assert (await c.post("/api/s4/v1/service/imports", json=payload)).status_code == 401
    assert (
        await c.post(
            "/api/s4/v1/service/imports",
            headers={"Authorization": "Bearer test-only-s5-receipt-token"},
            json=payload,
        )
    ).status_code == 401
    response = await c.post(
        "/api/s4/v1/service/imports",
        headers={"Authorization": "Bearer test-only-s3-import-token"},
        json=payload,
    )
    assert response.status_code == 202, response.text
    assert response.json()["scope"] == "s3:import"
    assert (
        await c.get(
            "/api/s4/v1/imports", headers={"Authorization": "Bearer test-only-s3-import-token"}
        )
    ).status_code == 401


def test_import_and_receipt_credentials_cannot_share_identity():
    import pytest
    from pydantic import ValidationError

    from openkb_s4.config import Settings

    with pytest.raises(ValidationError):
        Settings(import_token="same-test-token", receipt_token="same-test-token")
