"""Read-only consistency report for v1.3 private references and retained orphans."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import dotenv_values
from openkb_s4.services.content_inventory import (
    database_references,
    verify_controlled_graph,
)
from openkb_s4.services.content_store import ContentStore
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def inspect_store(store: ContentStore, references: list[dict[str, Any]]) -> dict[str, Any]:
    referenced = verify_controlled_graph(store, references)
    retained = len(store.inventory())
    return {"referenced_objects": referenced, "retained_objects": retained,
            "retained_unreferenced_objects": retained - referenced, "automatic_deletion": False}


async def run(args: argparse.Namespace) -> None:
    values = dotenv_values(args.env_file)
    url = make_url(values["S4_DATABASE_URL"]).set(drivername="postgresql")
    if args.database:
        url = url.set(database=args.database)
    connection = await asyncpg.connect(url.render_as_string(hide_password=False))
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            references = await database_references(connection)
            report = inspect_store(ContentStore(args.data_dir.resolve() / "controlled"), references)
            report.update({"migration": await connection.fetchval("SELECT version_num FROM alembic_version"),
                           "expired_running_jobs": await connection.fetchval("SELECT count(*) FROM jobs WHERE state='RUNNING' AND lease_until < now()"),
                           "database_readonly": True, "verified_at": datetime.now(UTC).isoformat()})
    finally:
        await connection.close()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--database")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    try:
        asyncio.run(run(parser.parse_args()))
    except Exception as exc:  # noqa: BLE001 - DB errors can contain credentials; only emit category.
        raise SystemExit("Read-only reconciliation failed (" + type(exc).__name__ + "); no objects were deleted.") from None
