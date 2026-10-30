"""Legacy endpoints cannot silently create records with superseded semantics."""
from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_legacy_business_writes_are_readonly_by_default(tmp_path: Path) -> None:
    from openkb_s4.config import Settings
    from openkb_s4.main import create_app

    app = create_app(Settings(data_dir=tmp_path))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/api/s4/v1/imports", json={})
            assert response.status_code == 409
            assert response.json()["error_code"] == "LEGACY_READ_ONLY"
            response = await client.get("/api/s4/v2/health/live")
            assert response.status_code == 200
    finally:
        await app.state.engine.dispose()
