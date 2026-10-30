"""Create a separate v1.3 synthetic browser environment without clearing any DB."""
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
    values = dotenv_values(ROOT / ".env")
    owner = make_url(values["S4_MIGRATION_DATABASE_URL"])
    connection = await asyncpg.connect(owner.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False))
    try:
        if not await connection.fetchval("SELECT 1 FROM pg_database WHERE datname='s4_v13_e2e'"):
            await connection.execute('CREATE DATABASE s4_v13_e2e OWNER s4_owner')
    finally:
        await connection.close()
    path = ROOT / ".env.v13-e2e"
    old = dotenv_values(path) if path.exists() else {}
    password = old.get("S4_V13_E2E_PASSWORD") or secrets.token_urlsafe(32)
    environment = {"S4_DATABASE_URL": make_url(values["S4_DATABASE_URL"]).set(database="s4_v13_e2e").render_as_string(hide_password=False),
                   "S4_MIGRATION_DATABASE_URL": owner.set(database="s4_v13_e2e").render_as_string(hide_password=False),
                   "S4_DATA_DIR": str(ROOT / "var" / "v13-e2e"),
                   "S4_COOKIE_SECURE": "false", "S4_ALLOWED_ORIGIN": "http://localhost:5176",
                   "S4_EXTERNAL_ALIGNMENT_CONFIRMED": "false", "S4_LEGACY_WRITES_ENABLED": "false",
                   "S4_V13_E2E_PASSWORD": password}
    path.write_text("".join(f"{key}={value}\n" for key, value in environment.items()), encoding="utf-8")
    await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "alembic", "upgrade", "head"],
                            cwd=ROOT / "backend", env={**os.environ, **environment}, check=True)
    from openkb_s4.db import make_sessions
    from openkb_s4.models import User
    from openkb_s4.security import check_password, hash_password
    engine, sessions = make_sessions(environment["S4_DATABASE_URL"])
    try:
        async with sessions() as db, db.begin():
            for name, roles in {"lead": ["lead"], "v": ["annotator"], "a": ["annotator"],
                                "b": ["annotator"], "other": ["annotator"], "verifier": ["verifier"]}.items():
                username = "v13-e2e-" + name
                existing = await db.scalar(select(User).where(User.username == username))
                if existing is None:
                    db.add(User(username=username, display_name="合成演练" + name,
                                person_id=username, roles=roles, password_hash=hash_password(password)))
                elif not check_password(existing.password_hash, password):
                    raise RuntimeError("Existing synthetic credentials differ; refusing overwrite")
    finally:
        await engine.dispose()
    print("Separate s4_v13_e2e prepared; credentials retained only in ignored .env.v13-e2e")


if __name__ == "__main__":
    asyncio.run(prepare())
