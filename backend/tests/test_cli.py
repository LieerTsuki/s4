"""First-account bootstrap is serialized even while the user table is empty."""
import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import select


async def test_concurrent_bootstrap_creates_exactly_one_admin(api: tuple[Any, httpx.AsyncClient], monkeypatch: pytest.MonkeyPatch) -> None:
    from openkb_s4 import cli
    from openkb_s4.models import User
    app, _ = api
    monkeypatch.setattr(cli, "get_settings", lambda: app.state.settings)
    results = await asyncio.gather(*(cli.bootstrap(f"first-{i}", "Administrator", f"first-person-{i}", "test-only-strong-passphrase") for i in range(2)), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    async with app.state.sessions() as db:
        users = (await db.scalars(select(User))).all()
        assert len(users) == 1 and users[0].roles == ["admin"]
