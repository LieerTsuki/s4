"""Real PostgreSQL fixtures; dedicated test database is mandatory for API tests."""
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv("../.env")


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    from openkb_s4.config import Settings
    from openkb_s4.main import create_app

    url = os.environ.get("S4_TEST_DATABASE_URL")
    if not url:
        pytest.skip("S4_TEST_DATABASE_URL is required: PostgreSQL integration test")
    if "test" not in url.rsplit("/", 1)[-1]:
        raise RuntimeError("Refusing to clear a database whose name does not contain test")
    # Reset with the migration owner, then run API and worker with production grants.
    # Derive only the database name; never print either connection credential.
    runtime_url = os.environ.get("S4_TEST_APP_DATABASE_URL")
    if not runtime_url and os.environ.get("S4_DATABASE_URL"):
        runtime_url = make_url(os.environ["S4_DATABASE_URL"]).set(database=make_url(url).database).render_as_string(hide_password=False)
    owner_target, runtime_target = make_url(url), make_url(runtime_url or url)
    if (owner_target.host, owner_target.port, owner_target.database) != (runtime_target.host, runtime_target.port, runtime_target.database):
        raise RuntimeError("Test runtime and owner must target the same dedicated test database")
    app = create_app(Settings(database_url=runtime_url or url, data_dir=tmp_path, login_limit=3,
                              legacy_writes_enabled=True))
    owner_engine = create_async_engine(url)
    async with owner_engine.begin() as connection:
        await connection.execute(text("TRUNCATE users CASCADE"))
        await connection.execute(text("TRUNCATE login_rates, audit_events, heartbeats"))
    await owner_engine.dispose()
    # TRUNCATE users CASCADE also clears the nullable signer FK baseline table.
    from openkb_s4.domain.contracts import canonical_sha256
    from openkb_s4.domain.profiles import baseline_snapshot, list_profiles
    from openkb_s4.models import ProfileRevision
    async with app.state.sessions() as db, db.begin():
        for profile in list_profiles():
            snapshot = baseline_snapshot(profile['dataset'])
            db.add(ProfileRevision(dataset=profile['dataset'],version=snapshot['version'],manual_version=snapshot['manual_version'],snapshot=snapshot,canonical_hash=canonical_sha256(snapshot),state='APPROVED',approval=snapshot['approval']))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield app, client
    await app.state.engine.dispose()
