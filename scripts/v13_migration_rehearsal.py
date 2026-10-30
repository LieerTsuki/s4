"""Rehearse v1.3 additive migrations only on an already verified isolated restore.

Never creates, drops or migrates s4_dev/s4_test. Output contains counts/hashes,
not business content, credentials or SQL parameter logs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def require_isolated_restore(name: str) -> str:
    if not re.fullmatch(r"s4_restore_[0-9]{8}_[0-9]{6}_[0-9a-f]{6}", name):
        raise ValueError("Migration rehearsal requires a verified isolated restore database")
    return name


async def run(args: argparse.Namespace) -> None:
    from openkb_s4.services.content_inventory import (
        database_references,
        verify_controlled_graph,
    )
    from openkb_s4.services.content_store import ContentStore
    from verify_migration_history import snapshot

    database = require_isolated_restore(args.database)
    restored = ROOT / "var" / database
    proof_path = restored / "restore-verification.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    if proof["restored_database"] != database or not proof.get("live_business_data_modified") is False:
        raise ValueError("Restore proof does not identify this isolated database")
    if args.output.exists():
        raise ValueError("Rehearsal output already exists; keep previous evidence")
    values = dotenv_values(args.env_file)
    owner = make_url(values["S4_MIGRATION_DATABASE_URL"]).set(database=database)
    url = owner.set(drivername="postgresql").render_as_string(hide_password=False)
    connection = await asyncpg.connect(url)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            before = await snapshot(connection, None)
            old_revision = await connection.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await connection.close()
    environment = dict(os.environ, S4_MIGRATION_DATABASE_URL=owner.render_as_string(hide_password=False))
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "alembic", "upgrade", "head"],
                                     cwd=ROOT / "backend", env=environment, capture_output=True,
                                     text=True, check=False)
    if result.returncode:
        raise RuntimeError("Migration rehearsal failed; isolated database retained")
    connection = await asyncpg.connect(url)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            after = await snapshot(connection, {table: data["columns"] for table, data in before.items()})
            new_revision = await connection.fetchval("SELECT version_num FROM alembic_version")
            references = await database_references(connection)
            controlled = verify_controlled_graph(ContentStore(restored / "controlled"), references)
            tables = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    finally:
        await connection.close()
    if before != after:
        raise RuntimeError("Original business contents changed; isolated database retained")
    evidence = {"database": database, "before_revision": old_revision, "after_revision": new_revision,
                "original_business_tables": before, "original_columns_and_rows_unchanged": True,
                "public_table_count": len(tables), "verified_controlled_objects": controlled,
                "live_business_data_modified": False, "restore_evidence": str(proof_path.relative_to(ROOT)),
                "verified_at": datetime.now(UTC).isoformat()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Isolated migration verified: {old_revision} -> {new_revision}; {len(before)} original business tables unchanged.")
    print("Evidence:", args.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, required=True)
    try:
        asyncio.run(run(parser.parse_args()))
    except Exception as exc:  # noqa: BLE001 - DB errors can contain credentials; only emit category.
        raise SystemExit("Isolated rehearsal failed (" + type(exc).__name__ + "); retained artifacts require inspection.") from None
