"""Real API contracts; the initial empty app proves the first red behavior."""
from typing import Any

import httpx
import pytest
from helpers import login, seed_user

from openkb_s4.main import create_app


async def test_liveness_endpoint_is_registered() -> None:
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/s4/v1/health/live")
    await app.state.engine.dispose()
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


async def test_login_logout_csrf_and_role_boundaries(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    await seed_user(app, "admin", ["admin"])
    await seed_user(app, "lead", ["lead"])
    assert (await client.get("/api/s4/v1/users")).status_code == 401
    admin_headers = await login(client, "admin")
    response = await client.post("/api/s4/v1/users", json={"username": "new", "password": "test-password-strong", "display_name": "新人", "person_id": "p-new", "roles": ["annotator"]})
    assert response.status_code == 403
    response = await client.post("/api/s4/v1/users", headers=admin_headers, json={"username": "new", "password": "test-password-strong", "display_name": "新人", "person_id": "p-new", "roles": ["annotator"]})
    assert response.status_code == 201
    assert "password_hash" not in response.json()
    assert (await client.get("/api/s4/v1/imports")).status_code == 403
    assert (await client.post("/api/s4/v1/auth/logout", headers=admin_headers)).status_code == 200
    assert (await client.get("/api/s4/v1/auth/me")).status_code == 401
    lead_headers = await login(client, "lead")
    assert (await client.get("/api/s4/v1/users")).status_code == 200
    assert (await client.post("/api/s4/v1/users", headers=lead_headers, json={"username": "bad", "password": "test-password-strong", "display_name": "bad", "person_id": "bad", "roles": ["admin"]})).status_code == 403


async def test_failed_login_is_rate_limited_and_user_deactivation_revokes_session(api: tuple[Any, httpx.AsyncClient]) -> None:
    app, client = api
    user_id = await seed_user(app, "alice", ["annotator"])
    await seed_user(app, "admin", ["admin"])
    for _ in range(3):
        assert (await client.post("/api/s4/v1/auth/login", json={"username": "nobody", "password": "wrong"})).status_code == 401
    assert (await client.post("/api/s4/v1/auth/login", json={"username": "nobody", "password": "wrong"})).status_code == 429
    await login(client, "alice")
    cookie = client.cookies.get("s4_session")
    headers = await login(client, "admin")
    assert (await client.patch(f"/api/s4/v1/users/{user_id}", headers=headers, json={"active": False})).status_code == 200
    client.cookies.set("s4_session", cookie or "", domain="testserver.local", path="/")
    assert (await client.get("/api/s4/v1/auth/me")).status_code == 401


async def test_unexpected_failure_returns_safe_json_without_secret_logs(api: tuple[Any, httpx.AsyncClient], caplog: pytest.LogCaptureFixture) -> None:
    from openkb_s4.db import database
    app, client = api
    async def unavailable() -> None:
        raise RuntimeError("SECRET_RAW_MATERIAL")
    app.dependency_overrides[database] = unavailable
    response = await client.get("/api/s4/v1/users")
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "SECRET_RAW_MATERIAL" not in response.text
    assert "SECRET_RAW_MATERIAL" not in caplog.text
