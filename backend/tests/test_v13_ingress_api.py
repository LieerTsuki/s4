"""JSONL uploads preserve original bytes and do not import invalid batches."""
import asyncio
import base64
import hashlib
import json
import time
from typing import Any

import pytest
from helpers import login, seed_user
from sqlalchemy import select
from test_v13_workflow import P, source_payload


@pytest.mark.asyncio
async def test_jsonl_raw_archive_is_reachable_from_backup_audit(api: Any) -> None:
    from openkb_s4.models import AuditEvent
    from openkb_s4.services.content_store import ContentStore

    app, client = api
    await seed_user(app, "lead", ["lead"])
    headers = await login(client, "lead")
    payload = source_payload(2)
    envelope = {key: value for key, value in payload.items() if key != "units"}
    raw = b"\xef\xbb\xbf" + b"\r\n".join(json.dumps(unit, ensure_ascii=False).encode() for unit in payload["units"]) + b"\r\n"
    response = await client.post(P + "/imports/upload", headers=headers,
        json={"envelope": envelope, "file_base64": base64.b64encode(raw).decode()})
    assert response.status_code == 201, response.text
    assert response.json()["raw_file_sha256"] == hashlib.sha256(raw).hexdigest()
    async with app.state.sessions() as db:
        audit = await db.scalar(select(AuditEvent).where(AuditEvent.action == "V13_IMPORT_FILE_UPLOADED"))
        assert audit is not None
        archive = ContentStore(app.state.settings.data_dir / "controlled").read_json(audit.details["raw_file_ref"])
        assert base64.b64decode(archive["file_base64"]) == raw
        assert "question" not in str(audit.details)
    broken = source_payload(2)
    broken["units"][0]["difficulty"] = "简单"
    broken["units"][1]["gold"]["expected_refusal"] = "false"
    preflight = await client.post(P + "/imports/validate", headers=headers, json=broken)
    assert preflight.status_code == 200
    assert preflight.json()["error_count"] == 2
    failed = await client.post(P + "/imports/upload", headers=headers,
        json={"envelope": envelope, "file_base64": base64.b64encode(b"not json\n{}").decode()})
    assert failed.status_code == 422 and not failed.json()["validation_report"]["valid"]
    assert (await client.get(P + "/imports")).json()["total"] == 1


@pytest.mark.asyncio
async def test_slow_snapshot_io_does_not_block_other_http_requests(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from openkb_s4.services.content_store import ContentStore

    app, client = api
    await seed_user(app, "lead", ["lead"])
    headers = await login(client, "lead")
    original = ContentStore.put_json
    def slow(store: ContentStore, value: Any) -> dict[str, str]:
        time.sleep(.08)
        return original(store, value)
    monkeypatch.setattr(ContentStore, "put_json", slow)
    ticks: list[float] = []
    running = True
    async def ticker() -> None:
        while running:
            start = time.perf_counter()
            await asyncio.sleep(.01)
            ticks.append(time.perf_counter() - start)
    heartbeat = asyncio.create_task(ticker())
    pending = asyncio.create_task(client.post(P + "/imports", headers=headers, json=source_payload(2)))
    await asyncio.sleep(.01)
    live = await client.get(P + "/health/live")
    result = await pending
    running = False
    await heartbeat
    assert result.status_code == 201, result.text
    assert live.status_code == 200 and max(ticks) < .2
