"""PostgreSQL + immutable snapshots backup and isolated restore rehearsal.

Requires the project's PostgreSQL Docker container and existing owner role.
Never drops a database or overwrites a restore directory. No secrets are exported.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
TABLES = ('users', 'source_imports', 'annotation_batches', 'assignments', 'submissions',
          'agreements', 'arbitrations', 'final_decisions', 'exposures', 'jobs', 'handoffs', 'audit_events')


def docker(*args: str) -> None:
    subprocess.run(['docker', *args], check=True, capture_output=True)


def hashes(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob('*')) if path.is_file()}


async def counts(url: str) -> dict[str, int]:
    connection = await asyncpg.connect(url)
    try:
        return {table: await connection.fetchval(f'SELECT count(*) FROM "{table}"') for table in TABLES}
    finally:
        await connection.close()


async def run(args: argparse.Namespace) -> None:
    values = dotenv_values(args.env_file)
    owner = make_url(values['S4_MIGRATION_DATABASE_URL'])
    database = args.database or owner.database
    if not database or not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', database):
        raise ValueError('Database must be a simple lowercase identifier.')
    target_url = owner.set(drivername='postgresql', database=database)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    if args.action == 'backup':
        folder = args.output.resolve() if args.output else ROOT / 'backups' / stamp
        folder.mkdir(parents=True, exist_ok=False)
        temp_dump = '/tmp/s4-backup-' + uuid.uuid4().hex + '.dump'
        try:
            docker('exec', args.container, 'pg_dump', '-U', str(owner.username), '-d', database,
                   '--format=custom', '--no-owner', '--file=' + temp_dump)
            docker('cp', args.container + ':' + temp_dump, str(folder / 'database.dump'))
        finally:
            docker('exec', args.container, 'rm', '-f', temp_dump)
        source = args.data_dir.resolve() if args.data_dir else Path(values.get('S4_DATA_DIR') or ROOT / 'var').resolve()
        artifacts = folder / 'artifacts'
        if args.api_container:
            artifacts.mkdir()
            docker('cp', args.api_container + ':/var/lib/s4/exports', str(artifacts / 'exports'))
        elif (source / 'exports').exists():
            shutil.copytree(source / 'exports', artifacts / 'exports')
        else:
            artifacts.mkdir()
        manifest = {'created_at': datetime.now(UTC).isoformat(), 'source_database': database,
                    'row_counts': await counts(target_url.render_as_string(hide_password=False)),
                    'files': hashes(folder), 'maintenance_window_required': True}
        (folder / 'backup-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print('Backup created:', folder)
        return
    folder = args.backup.resolve()
    manifest = json.loads((folder / 'backup-manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Backup checksum verification failed: ' + name)
    restored_name = 's4_restore_' + datetime.now(UTC).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    restored_dir = ROOT / 'var' / restored_name
    if restored_dir.exists():
        raise ValueError('Restore destination already exists.')
    maintenance = owner.set(drivername='postgresql', database='postgres')
    connection = await asyncpg.connect(maintenance.render_as_string(hide_password=False))
    try:
        await connection.execute(f'CREATE DATABASE "{restored_name}"')
    finally:
        await connection.close()
    temp_dump = '/tmp/s4-restore-' + uuid.uuid4().hex + '.dump'
    try:
        docker('cp', str(folder / 'database.dump'), args.container + ':' + temp_dump)
        docker('exec', args.container, 'pg_restore', '-U', str(owner.username), '-d', restored_name,
               '--no-owner', '--exit-on-error', temp_dump)
    finally:
        docker('exec', args.container, 'rm', '-f', temp_dump)
    shutil.copytree(folder / 'artifacts', restored_dir)
    restored_url = owner.set(drivername='postgresql', database=restored_name).render_as_string(hide_password=False)
    actual = await counts(restored_url)
    if actual != manifest['row_counts']:
        raise ValueError('Restored row counts differ; database retained for investigation.')
    from openkb_s4.services.handoffs import verify_snapshot
    connection = await asyncpg.connect(restored_url)
    try:
        snapshots = await connection.fetch('SELECT id, manifest FROM handoffs')
    finally:
        await connection.close()
    expected_ids = {row['id'] for row in snapshots}
    actual_ids = {path.parent.name for path in restored_dir.glob('exports/*/s4_handoff_manifest.json')
                  if not path.parent.name.endswith('.partial')}
    if expected_ids != actual_ids:
        raise ValueError('Restored database and snapshot directories differ.')
    for row in snapshots:
        directory = (restored_dir / 'exports' / row['id']).resolve()
        if not directory.is_relative_to(restored_dir):
            raise ValueError('Invalid restored snapshot identity.')
        expected_manifest = json.loads(row['manifest']) if isinstance(row['manifest'], str) else row['manifest']
        verify_snapshot(directory, expected_manifest)
    verified = len(snapshots)
    evidence = {'restored_database': restored_name, 'restored_data_dir': str(restored_dir),
                'row_counts': actual, 'verified_snapshots': verified, 'source_backup': str(folder),
                'verified_at': datetime.now(UTC).isoformat(), 'live_database_modified': False}
    (restored_dir / 'restore-verification.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print('Isolated restore verified:', restored_dir / 'restore-verification.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--container', default='openkb-s4-db-1')
    parser.add_argument('--database')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--api-container', help='Copy Compose artifact volume through this API container.')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--backup', type=Path)
    arguments = parser.parse_args()
    if arguments.action == 'restore' and not arguments.backup:
        parser.error('--backup is required for restore')
    asyncio.run(run(arguments))
