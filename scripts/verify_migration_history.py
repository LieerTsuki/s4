"""Capture/compare existing business columns across an additive migration.

Run capture with application writers stopped, migrate, then compare before
restarting writers. Only column names, row counts and SHA-256 leave the database.
New tables/columns are allowed; original columns and row contents must match.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'alembic_version', 'heartbeats', 'audit_events', 'login_rates', 'sessions'}


def quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def snapshot(connection: asyncpg.Connection, columns: dict[str, list[str]] | None) -> dict[str, Any]:
    if columns is None:
        columns = {}
        for row in await connection.fetch(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='public' ORDER BY table_name, ordinal_position"
        ):
            if row['table_name'] not in EXCLUDED:
                columns.setdefault(row['table_name'], []).append(row['column_name'])
    result: dict[str, Any] = {}
    for table, names in columns.items():
        rows = await connection.fetch('SELECT ' + ','.join(map(quote, names)) + ' FROM ' + quote(table))
        encoded = sorted(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) for row in rows)
        result[table] = {'columns': names, 'rows': len(rows),
                         'sha256': hashlib.sha256('\n'.join(encoded).encode('utf-8')).hexdigest()}
    return result


async def run(args: argparse.Namespace) -> None:
    values = dotenv_values(args.env_file)
    url = make_url(values['S4_MIGRATION_DATABASE_URL']).set(drivername='postgresql')
    if args.database:
        url = url.set(database=args.database)
    previous = json.loads(args.evidence.read_text(encoding='utf-8')) if args.action == 'compare' else None
    connection = await asyncpg.connect(url.render_as_string(hide_password=False))
    try:
        async with connection.transaction(isolation='repeatable_read', readonly=True):
            data = await snapshot(connection, {k: v['columns'] for k, v in previous['tables'].items()} if previous else None)
    finally:
        await connection.close()
    result = {'database': url.database, 'tables': data}
    if previous:
        if previous['database'] != url.database or previous['tables'] != data:
            changed = [name for name in data if previous['tables'].get(name) != data[name]]
            raise RuntimeError(f'Existing business history changed: {changed}')
        result['unchanged'] = True
        args.evidence.with_suffix('.verified.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(f'Original columns and row hashes unchanged across migration: {len(data)} tables.')
    else:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(f'Captured business hashes for {len(data)} tables; no raw material written.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['capture', 'compare'])
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--database')
    parser.add_argument('--evidence', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
