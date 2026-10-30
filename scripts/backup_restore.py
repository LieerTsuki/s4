"""PostgreSQL + immutable snapshots backup and isolated restore rehearsal.

Requires the project's PostgreSQL Docker container and existing owner role.
Never drops a database or overwrites a restore directory. No secrets are exported.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger("openkb_s4.backup_restore")


def docker(*args: str) -> None:
    subprocess.run(['docker', *args], check=True, capture_output=True)


def hashes(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob('*')) if path.is_file()}


def verify_backup_files(folder: Path, manifest: dict[str, Any]) -> None:
    """Validate paths, exact file inventory and digests before creating a restore DB."""
    declared = manifest['files']
    for name, expected in declared.items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or path == folder.resolve():
            raise ValueError('Backup path is outside its archive.')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Backup checksum verification failed.')
    actual = set(hashes(folder)) - {'backup-manifest.json'}
    if actual != set(declared):
        raise ValueError('Backup file set differs from its manifest.')


def raw_import_manifest(audits: list[Any]) -> dict[str, str]:
    """Extract only digest-named JSONL references recorded by the upload service."""
    expected: dict[str, str] = {}
    for row in audits:
        details = row['details']
        if isinstance(details, str):
            details = json.loads(details)
        if not isinstance(details, dict):
            raise TypeError('Raw import audit must contain a controlled file reference.')
        digest, reference = details.get('raw_file_sha256'), details.get('file_ref')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) or reference != digest + '.jsonl':
            raise ValueError('Raw import audit must contain a controlled digest-named file reference.')
        expected[reference] = digest
    return dict(sorted(expected.items()))


def verify_raw_import_files(data_root: Path, expected: dict[str, str], *, strict_inventory: bool = True) -> None:
    """Require archived original bytes, rejecting symlinks, paths and digest drift."""
    if not isinstance(expected, dict):
        raise TypeError('Raw import inventory must be a controlled mapping.')
    raw_import_manifest([{'details': {'file_ref': name, 'raw_file_sha256': digest}} for name, digest in expected.items()])
    directory = data_root / 'imports'
    if directory.is_symlink() or not directory.resolve().is_relative_to(data_root.resolve()):
        raise ValueError('Raw import directory must stay inside controlled artifacts.')
    for name, digest in expected.items():
        path = directory / name
        if path.is_symlink() or path.resolve().parent != directory.resolve():
            raise ValueError('Raw import file must stay inside controlled artifacts.')
        if not path.is_file():
            raise ValueError('Referenced raw import file is missing.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Raw import file digest does not match its upload audit.')
    if strict_inventory and directory.exists() and {entry.name for entry in directory.iterdir()} != set(expected):
        raise ValueError('Raw import inventory differs from archived upload audits.')


async def operation_event(url: str, action: str, operation_id: str, details: dict[str, Any]) -> None:
    """Append a safe operational audit, with no connection string or material."""
    connection = await asyncpg.connect(url)
    try:
        await connection.execute(
            'INSERT INTO audit_events(id, created_at, actor_id, action, object_id, request_id, details) VALUES($1,$2,$3,$4,$5,$6,$7)',
            str(uuid.uuid4()), datetime.now(UTC), None, action, operation_id, 'backup-restore', json.dumps(details),
        )
    finally:
        await connection.close()


async def connection_counts(connection: asyncpg.Connection) -> dict[str, int]:
    tables = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    result: dict[str, int] = {}
    for row in tables:
        table = row['tablename']
        identifier = '"' + table.replace('"', '""') + '"'
        result[table] = await connection.fetchval('SELECT count(*) FROM ' + identifier)
    return result


async def counts(url: str) -> dict[str, int]:
    connection = await asyncpg.connect(url)
    try:
        return await connection_counts(connection)
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
        source = args.data_dir.resolve() if args.data_dir else Path(values.get('S4_DATA_DIR') or ROOT / 'var').resolve()
        artifacts = folder / 'artifacts'
        artifacts.mkdir()
        connection = await asyncpg.connect(target_url.render_as_string(hide_password=False))
        try:
            async with connection.transaction(isolation='repeatable_read', readonly=True):
                snapshot = await connection.fetchval('SELECT pg_export_snapshot()')
                row_counts = await connection_counts(connection)
                handoffs = await connection.fetch('SELECT id, manifest FROM handoffs')
                raw_files = raw_import_manifest(await connection.fetch("SELECT details FROM audit_events WHERE action='IMPORT_FILE_UPLOADED' ORDER BY created_at,id"))
                from openkb_s4.services.content_inventory import (
                    database_references,
                    references_in,
                    verify_controlled_graph,
                )
                from openkb_s4.services.content_store import ContentStore
                controlled_roots = await database_references(connection)
                try:
                    docker('exec', args.container, 'pg_dump', '-U', str(owner.username), '-d', database,
                           '--snapshot=' + snapshot, '--format=custom', '--no-owner', '--file=' + temp_dump)
                    docker('cp', args.container + ':' + temp_dump, str(folder / 'database.dump'))
                finally:
                    docker('exec', args.container, 'rm', '-f', temp_dump)
                from openkb_s4.services.handoffs import verify_snapshot
                for row in handoffs:
                    identity = row['id']
                    if not re.fullmatch(r'[0-9a-f-]{36}', identity):
                        raise ValueError('Invalid published snapshot identity.')
                    destination = artifacts / 'exports' / identity
                    destination.parent.mkdir(exist_ok=True)
                    if args.api_container:
                        docker('cp', args.api_container + ':/var/lib/s4/exports/' + identity, str(destination))
                    else:
                        shutil.copytree(source / 'exports' / identity, destination)
                    expected = json.loads(row['manifest']) if isinstance(row['manifest'], str) else row['manifest']
                    verify_snapshot(destination, expected)
                if not args.api_container:
                    verify_raw_import_files(source, raw_files, strict_inventory=False)
                for name in raw_files:
                    destination = artifacts / 'imports' / name
                    destination.parent.mkdir(exist_ok=True)
                    if args.api_container:
                        docker('cp', args.api_container + ':/var/lib/s4/imports/' + name, str(destination))
                    else:
                        shutil.copyfile(source / 'imports' / name, destination)
                verify_raw_import_files(artifacts, raw_files)
                if controlled_roots:
                    destination = artifacts / 'controlled'
                    if args.api_container:
                        docker('cp', args.api_container + ':/var/lib/s4/controlled', str(destination))
                    else:
                        shutil.copytree(source / 'controlled', destination)
                    verify_controlled_graph(ContentStore(destination), controlled_roots)
                v13_snapshots = []
                if await connection.fetchval("SELECT to_regclass('public.v13_handoffs')"):
                    v13_snapshots = await connection.fetch('SELECT id,manifest_ref FROM v13_handoffs')
                from openkb_s4.services.handoffs_v13 import verify_package
                controlled_export_roots = []
                for row in v13_snapshots:
                    identity = row['id']
                    if not re.fullmatch(r'[0-9a-f-]{36}', identity):
                        raise ValueError('Invalid v1.3 snapshot identity')
                    destination = artifacts / 'exports-v13' / identity
                    destination.parent.mkdir(exist_ok=True)
                    if args.api_container:
                        docker('cp', args.api_container + ':/var/lib/s4/exports-v13/' + identity, str(destination))
                    else:
                        shutil.copytree(source / 'exports-v13' / identity, destination)
                    ref = json.loads(row['manifest_ref']) if isinstance(row['manifest_ref'], str) else row['manifest_ref']
                    verify_package(destination, ContentStore(artifacts / 'controlled').read_json(ref))
                    controlled_export_roots.extend(references_in(json.loads((destination / 's4_report.json').read_bytes())))
                verify_controlled_graph(ContentStore(artifacts / 'controlled'), controlled_roots + controlled_export_roots)
        finally:
            await connection.close()
        manifest = {'created_at': datetime.now(UTC).isoformat(), 'source_database': database,
                    'row_counts': row_counts,
                    'files': hashes(folder), 'consistency': 'postgres_exported_snapshot_and_immutable_manifest',
                    'raw_import_files': raw_files,
                    'controlled_roots': controlled_roots,
                    'controlled_export_roots': controlled_export_roots,
                    'published_v13_snapshot_ids': sorted(row['id'] for row in v13_snapshots),
                    'published_snapshot_ids': sorted(row['id'] for row in handoffs), 'maintenance_window_required': False}
        (folder / 'backup-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        await operation_event(target_url.render_as_string(hide_password=False), 'BACKUP_COMPLETED', stamp,
                              {'manifest_sha256': hashlib.sha256((folder / 'backup-manifest.json').read_bytes()).hexdigest(),
                               'published_snapshot_count': len(handoffs), 'raw_import_file_count': len(raw_files), 'consistency': manifest['consistency']})
        print('Backup created:', folder)
        return
    folder = args.backup.resolve()
    manifest = json.loads((folder / 'backup-manifest.json').read_text(encoding='utf-8'))
    verify_backup_files(folder, manifest)
    if 'raw_import_files' in manifest:
        verify_raw_import_files(folder / 'artifacts', manifest['raw_import_files'])
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
        restored_raw_files = raw_import_manifest(await connection.fetch("SELECT details FROM audit_events WHERE action='IMPORT_FILE_UPLOADED' ORDER BY created_at,id"))
        from openkb_s4.services.content_inventory import (
            database_references,
            references_in,
            verify_controlled_graph,
        )
        from openkb_s4.services.content_store import ContentStore
        controlled_roots = await database_references(connection)
        controlled_count = verify_controlled_graph(ContentStore(restored_dir / 'controlled'), controlled_roots)
        if 'controlled_roots' in manifest and sorted(controlled_roots, key=lambda value: value['object_key']) != sorted(manifest['controlled_roots'], key=lambda value: value['object_key']):
            raise ValueError('Restored controlled references differ from the source snapshot')
        from openkb_s4.services.handoffs_v13 import verify_package
        v13_snapshots = []
        if await connection.fetchval("SELECT to_regclass('public.v13_handoffs')"):
            v13_snapshots = await connection.fetch('SELECT id,manifest_ref FROM v13_handoffs')
        if {row['id'] for row in v13_snapshots} != set(manifest.get('published_v13_snapshot_ids', [])):
            raise ValueError('Restored v1.3 snapshot index differs')
        export_roots = []
        for row in v13_snapshots:
            if not re.fullmatch(r'[0-9a-f-]{36}', row['id']):
                raise ValueError('Invalid restored v1.3 snapshot identity')
            ref = json.loads(row['manifest_ref']) if isinstance(row['manifest_ref'], str) else row['manifest_ref']
            verify_package(restored_dir / 'exports-v13' / row['id'], ContentStore(restored_dir / 'controlled').read_json(ref))
            export_roots.extend(references_in(json.loads((restored_dir / 'exports-v13' / row['id'] / 's4_report.json').read_bytes())))
        controlled_count = verify_controlled_graph(ContentStore(restored_dir / 'controlled'), controlled_roots + export_roots)
        if 'controlled_export_roots' in manifest and sorted(export_roots, key=lambda value: value['object_key']) != sorted(manifest['controlled_export_roots'], key=lambda value: value['object_key']):
            raise ValueError('Restored export evidence references differ')
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
    if 'raw_import_files' in manifest and restored_raw_files != manifest['raw_import_files']:
        raise ValueError('Restored upload audits differ from the raw import inventory.')
    # Older backups have no raw_import_files field. They remain compatible when
    # no upload is referenced; an old archive missing referenced files must fail.
    verify_raw_import_files(restored_dir, restored_raw_files)
    verified = len(snapshots)
    evidence = {'restored_database': restored_name, 'restored_data_dir': str(restored_dir),
                'row_counts': actual, 'verified_snapshots': verified, 'verified_raw_import_files': len(restored_raw_files), 'source_backup': str(folder),
                'verified_controlled_objects': controlled_count, 'verified_v13_snapshots': len(v13_snapshots),
                'verified_at': datetime.now(UTC).isoformat(), 'live_business_data_modified': False,
                'operations_audit_recorded': True}
    (restored_dir / 'restore-verification.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    await operation_event(target_url.render_as_string(hide_password=False), 'RESTORE_COMPLETED', restored_name,
                          {'verified_snapshots': verified, 'verified_raw_import_files': len(restored_raw_files), 'source_manifest_sha256': hashlib.sha256((folder / 'backup-manifest.json').read_bytes()).hexdigest(),
                           'live_business_data_modified': False})
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
    try:
        asyncio.run(run(arguments))
    except Exception as failure:  # noqa: BLE001 - DB/subprocess messages may include URL credentials; record safe categories only.
        # Failure categories are useful in operations; subprocess output and
        # database exception strings may contain secrets and are not persisted.
        operation_id = str(uuid.uuid4())
        failure_record = {'id': operation_id, 'operation': arguments.action, 'state': 'FAILED',
                          'error_category': type(failure).__name__, 'created_at': datetime.now(UTC).isoformat()}
        try:
            failure_directory = ROOT / 'var' / 'operations'
            failure_directory.mkdir(parents=True, exist_ok=True)
            (failure_directory / (operation_id + '.json')).write_text(json.dumps(failure_record, indent=2), encoding='utf-8')
        except OSError:
            LOGGER.error('operation_failure_record_unavailable')
        try:
            config_values = dotenv_values(arguments.env_file)
            owner_url = make_url(config_values['S4_MIGRATION_DATABASE_URL'])
            audit_url = owner_url.set(drivername='postgresql', database=arguments.database or owner_url.database).render_as_string(hide_password=False)
            asyncio.run(operation_event(audit_url, arguments.action.upper() + '_FAILED', operation_id, {'error_category': type(failure).__name__}))
        except Exception:  # noqa: BLE001 - audit connection failures may include credentials; never print exception text.
            LOGGER.error('operation_failure_audit_unavailable')
        raise SystemExit('Backup/restore failed; inspect the retained operation artifacts and safe operational audit.') from None
