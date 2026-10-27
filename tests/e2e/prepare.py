"""Prepare a dedicated synthetic-only browser database; never reset a live database."""
from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
from pathlib import Path

import asyncpg
from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


async def prepare() -> None:
    local = dotenv_values(ROOT / ".env")
    migration = local.get("S4_MIGRATION_DATABASE_URL")
    if not migration:
        raise RuntimeError("Set S4_MIGRATION_DATABASE_URL in the ignored .env first.")
    owner = make_url(migration)
    maintenance = owner.set(drivername="postgresql", database="postgres")
    conn = await asyncpg.connect(maintenance.render_as_string(hide_password=False))
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 's4_e2e'")
        if not exists:
            await conn.execute("CREATE DATABASE s4_e2e OWNER s4_owner")
    finally:
        await conn.close()
    path = ROOT / ".env.e2e"
    previous = dotenv_values(path) if path.exists() else {}
    password = previous.get("S4_E2E_ADMIN_PASSWORD") or secrets.token_urlsafe(32)
    url = owner.set(database="s4_e2e").render_as_string(hide_password=False)
    runtime_url = make_url(local['S4_DATABASE_URL']).set(database='s4_e2e').render_as_string(hide_password=False)
    values = {
        "S4_DATABASE_URL": runtime_url,
        "S4_MIGRATION_DATABASE_URL": url,
        "S4_DATA_DIR": str(ROOT / "var" / "e2e"),
        "S4_COOKIE_SECURE": "false",
        "S4_ALLOWED_ORIGIN": "http://localhost:5174",
        "S4_EXTERNAL_ALIGNMENT_CONFIRMED": "false",
        "S4_E2E_ADMIN_USERNAME": "e2e-admin",
        "S4_E2E_ADMIN_PASSWORD": password,
    }
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    env = {**os.environ, **values}
    await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", env=env, check=True)
    os.environ.update(values)
    from openkb_s4.config import Settings
    from openkb_s4.db import make_sessions
    from openkb_s4.models import User
    from openkb_s4.security import check_password, hash_password

    engine, factory = make_sessions(Settings().database_url)
    try:
        async with factory() as db, db.begin():
            existing = await db.scalar(select(User).where(User.username == "e2e-admin"))
            if existing is None:
                db.add(User(username="e2e-admin", display_name="浏览器测试管理员", person_id="synthetic-e2e-admin",
                            roles=["admin"], password_hash=hash_password(password)))
            elif not check_password(existing.password_hash, password):
                raise RuntimeError("Existing browser-test credentials do not match; refusing to overwrite.")
    finally:
        await engine.dispose()
    print("Dedicated s4_e2e database prepared; credentials remain in ignored .env.e2e.")


if __name__ == "__main__":
    asyncio.run(prepare())
