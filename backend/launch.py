"""Single-process launcher for the OpenKB-Eval S4 platform.

Bootstraps the SQLite schema, seeds baseline profiles and starter accounts,
runs the durable worker loop as an in-process task and serves the API plus
the built web UI on one port. PostgreSQL deployments keep using compose.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR / "src"))

VAR_DIR = Path(os.environ.get("S4_DATA_DIR", ROOT / "var"))
VAR_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = VAR_DIR / "openkb_s4.db"

os.environ.setdefault("S4_DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}")
os.environ.setdefault("S4_SESSION_HOURS", "168")
# Platform preview injects FLASK_PORT for python services; PORT wins when set.
PORT = int(os.environ.get("PORT") or os.environ.get("FLASK_PORT") or "8084")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("s4.launch")

from fastapi.responses import FileResponse  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from openkb_s4.config import get_settings  # noqa: E402
from openkb_s4.db import make_sessions  # noqa: E402
from openkb_s4.main import create_app  # noqa: E402
from openkb_s4.models import Base, SourceImport, User  # noqa: E402
from openkb_s4.security import hash_password  # noqa: E402

DIST_DIR = ROOT / "frontend" / "dist"
DEMO_IMPORT = ROOT / "contracts" / "examples" / "demo-import.json"

STARTER_ACCOUNTS = [
    ("admin", "系统管理员", "P-ADMIN-001", ["admin"], "S4admin-Init-2026"),
    ("liyue", "李悦 · 标注运营", "P-LIYUE-001", ["lead"], "Lead-Liyue-2026"),
    ("ann-a", "标注员A", "P-ANNA-001", ["annotator"], "Annot-A-2026"),
    ("ann-b", "标注员B", "P-ANNB-001", ["annotator"], "Annot-B-2026"),
]


async def initialize_database() -> tuple:
    """Create schema, baseline profiles, starter accounts and demo material job."""
    from openkb_s4.domain.contracts import canonical_sha256
    from openkb_s4.domain.profiles import baseline_snapshot, list_profiles
    from openkb_s4.models import ProfileRevision
    from openkb_s4.services.jobs import enqueue

    settings = get_settings()
    engine, factory = make_sessions(settings.database_url)
    async with engine.begin() as connection:
        if settings.database_url.startswith("sqlite"):
            await connection.execute(text("PRAGMA journal_mode=WAL"))
            await connection.execute(text("PRAGMA busy_timeout=30000"))
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        if settings.database_url.startswith("sqlite"):
            # Migration 0007 on an existing 0006 database: create_all builds new
            # tables but cannot ALTER existing ones, so add columns idempotently.
            existing = {row[1] for row in (await connection.execute(text("PRAGMA table_info(v13_batches)"))).fetchall()}
            if existing:
                ddl = {
                    "profile_revision_id": "VARCHAR(36) REFERENCES v13_profile_revisions(id)",
                    "profile_hash": "VARCHAR(64)",
                    "profile_snapshot_ref": "JSON",
                    "profile_approval_ref": "JSON",
                    "manual_ref": "JSON",
                    "vocabulary_ref": "JSON",
                }
                for column, typedef in ddl.items():
                    if column not in existing:
                        await connection.execute(text(f"ALTER TABLE v13_batches ADD COLUMN {column} {typedef}"))
        await connection.execute(text("DELETE FROM alembic_version"))
        await connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0007_v13_profiles')"))

    async with factory() as db, db.begin():
        for profile in list_profiles():
            dataset = profile["dataset"]
            if not await db.scalar(select(ProfileRevision).where(ProfileRevision.dataset == dataset).limit(1)):
                snapshot = baseline_snapshot(dataset)
                db.add(ProfileRevision(dataset=dataset, version=snapshot["version"],
                                       manual_version=snapshot["manual_version"], snapshot=snapshot,
                                       canonical_hash=canonical_sha256(snapshot), state="APPROVED",
                                       approval=snapshot["approval"]))

    async with factory() as db, db.begin():
        for username, display, person, roles, password in STARTER_ACCOUNTS:
            if not await db.scalar(select(User).where(User.username == username).limit(1)):
                db.add(User(username=username, display_name=display, person_id=person,
                            roles=roles, password_hash=hash_password(password)))

    if DEMO_IMPORT.is_file():
        async with factory() as db, db.begin():
            if not await db.scalar(select(SourceImport).limit(1)):
                admin = await db.scalar(select(User).where(User.username == "admin"))
                payload = json.loads(DEMO_IMPORT.read_text(encoding="utf-8"))
                await enqueue(db, "IMPORT", f"seed-import:{payload.get('batch_id', 'demo')}",
                              admin.id, payload)
                logger.info("queued demo material import %s", payload.get("batch_id"))
    await engine.dispose()
    logger.info("database ready at %s", DB_PATH)
    return settings


def build_application():
    application = create_app(get_settings())
    if DIST_DIR.is_dir():

        @application.get("/{full_path:path}", include_in_schema=False)
        async def web_ui(full_path: str):
            target = (DIST_DIR / full_path).resolve()
            if full_path and str(target).startswith(str(DIST_DIR.resolve())) and target.is_file():
                return FileResponse(target)
            return FileResponse(DIST_DIR / "index.html")

    else:
        logger.warning("frontend dist missing; run `npm run build` in frontend/")

    return application


async def main() -> None:
    await initialize_database()
    application = build_application()

    import uvicorn
    from openkb_s4.worker import serve as worker_serve

    worker_task = asyncio.create_task(worker_serve(once=False))
    server = uvicorn.Server(uvicorn.Config(application, host="0.0.0.0", port=PORT, log_level="info"))
    logger.info("S4 platform listening on 0.0.0.0:%s", PORT)
    try:
        await server.serve()
    finally:
        worker_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
