"""Synthetic 2300-unit/11-session local smoke; no human or production claim."""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
P = "/api/s4/v2"


async def main() -> None:
    from openkb_s4.db import make_sessions
    from openkb_s4.models import User
    from openkb_s4.security import hash_password

    env = dotenv_values(ROOT / ".env.v13-e2e")
    if env["S4_DATABASE_URL"].rsplit("/", 1)[-1] != "s4_v13_e2e":
        raise RuntimeError("Capacity smoke requires the dedicated synthetic browser database")
    run = uuid4().hex[:8]
    engine, sessions = make_sessions(env["S4_DATABASE_URL"])
    users = []
    try:
        async with sessions() as db, db.begin():
            for index in range(11):
                name = f"v13-load-{run}-{index}"
                user = User(username=name, display_name=name, person_id=name, roles=["annotator"],
                            password_hash=hash_password(env["S4_V13_E2E_PASSWORD"]))
                db.add(user)
                await db.flush()
                users.append((user.id, name))
            assert await db.scalar(select(User.id).where(User.username == "v13-e2e-lead"))
    finally:
        await engine.dispose()
    base = json.loads((ROOT / "contracts/v13/examples/demo-import.json").read_text(encoding="utf-8"))
    payload = {**base, "batch_id": "V13-LOAD-" + run, "source_revision": "r1", "units": []}
    for index in range(2300):
        unit = deepcopy(base["units"][0])
        unit.update(unit_id=f"QA-D1-load-{run}-{index}", difficulty=["easy", "medium", "hard"][index % 3])
        payload["units"].append(unit)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8004", timeout=180) as client:
        login = await client.post("/api/s4/v1/auth/login", json={"username": "v13-e2e-lead", "password": env["S4_V13_E2E_PASSWORD"]})
        login.raise_for_status()
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        start = time.perf_counter()
        response = await client.post(P + "/imports", headers=headers, json=payload)
        response.raise_for_status()
        import_seconds = time.perf_counter() - start
        imported = response.json()["id"]
        start = time.perf_counter()
        response = await client.post(P + "/verification-batches", headers=headers,
                                    json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [user[0] for user in users]})
        response.raise_for_status()
        plan_seconds = time.perf_counter() - start
    timings = []
    async def connection(username: str) -> None:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8004", timeout=60) as client:
            response = await client.post("/api/s4/v1/auth/login", json={"username": username, "password": env["S4_V13_E2E_PASSWORD"]})
            response.raise_for_status()
            tasks = await client.get(P + "/me/tasks?limit=500")
            tasks.raise_for_status()
            target = tasks.json()["items"][0]["id"]
            for _ in range(10):
                start = time.perf_counter()
                detail = await client.get(P + "/assignments/" + target)
                detail.raise_for_status()
                assert "gold" not in detail.json()
                timings.append((time.perf_counter() - start) * 1000)
    await asyncio.gather(*(connection(name) for _, name in users))
    result = {"synthetic_only": True, "production_acceptance": False, "human_acceptance": "NOT_PERFORMED",
              "population": 2300, "dataset_mix": "QA-D1 synthetic stress scope, not formal 13-dataset quota",
              "concurrent_sessions": 11, "successful_blind_reads": len(timings), "import_seconds": import_seconds,
              "full_verification_plan_seconds": plan_seconds, "read_latency_ms": {"p50": statistics.median(timings),
              "p95": sorted(timings)[int(len(timings) * .95) - 1], "max": max(timings)}, "import_id": imported}
    (ROOT / "var/evidence/v13-capacity-smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
