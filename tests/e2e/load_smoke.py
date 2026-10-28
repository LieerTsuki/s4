"""Synthetic local capacity smoke: 2,200 units and 11 concurrent BLIND reads.

This records measured local latencies, not target-production acceptance. It adds
isolated synthetic identities/material to s4_e2e and never truncates any database.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
PREFIX = '/api/s4/v1'


async def signed_in(client: httpx.AsyncClient, name: str, password: str) -> dict[str, str]:
    response = await client.post(PREFIX + '/auth/login', json={'username': name, 'password': password})
    response.raise_for_status()
    return {'X-CSRF-Token': response.json()['csrf_token']}


async def main() -> None:
    env = dotenv_values(ROOT / '.env.e2e')
    run = uuid4().hex[:10]
    password = uuid4().hex + '-synthetic'
    credentials: dict[str, str] = {}
    identities: dict[str, str] = {}
    url = 'http://127.0.0.1:8004'
    async with httpx.AsyncClient(base_url=url, timeout=120) as admin:
        admin_headers = await signed_in(admin, env['S4_E2E_ADMIN_USERNAME'], env['S4_E2E_ADMIN_PASSWORD'])
        for seat, roles in [('lead', ['lead']), ('a', ['annotator']), ('b', ['annotator'])]:
            name = f'capacity-{run}-{seat}'
            response = await admin.post(PREFIX + '/users', headers=admin_headers, json={
                'username': name, 'display_name': f'容量合成{seat}', 'person_id': name,
                'password': password, 'roles': roles})
            response.raise_for_status()
            credentials[seat] = name
            identities[seat] = response.json()['id']
    original = json.loads((ROOT / 'contracts/examples/demo-import.json').read_text(encoding='utf-8'))
    candidate = {key: deepcopy(value) for key, value in original.items() if key != 'units'}
    candidate.update(batch_id=f'CAPACITY-{run}', source_revision=f'capacity-{run}', units=[])
    for index in range(2200):
        unit = deepcopy(original['units'][index % len(original['units'])])
        unit.update(unit_id=f'QA-D1-CAPACITY-{run}-{index:04d}', seed_id=f'CAPACITY-SEED-{run}-{index:04d}')
        candidate['units'].append(unit)
    async with httpx.AsyncClient(base_url=url, timeout=120) as lead:
        headers = await signed_in(lead, credentials['lead'], password)
        started = time.perf_counter()
        response = await lead.post(PREFIX + '/imports', headers=headers, json=candidate)
        response.raise_for_status()
        job_id = response.json()['job_id']
        deadline = time.monotonic() + 120
        while True:
            response = await lead.get(PREFIX + '/jobs/' + job_id)
            response.raise_for_status()
            job = response.json()
            if job['state'] in {'DONE', 'FAILED'}:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('Capacity import did not finish within 120 seconds.')
            await asyncio.sleep(.25)
        if job['state'] != 'DONE':
            raise RuntimeError(f'Capacity import failed: {job.get("error_code")}')
        import_seconds = time.perf_counter() - started
        started = time.perf_counter()
        response = await lead.post(PREFIX + '/annotation-batches', headers=headers, json={
            'import_id': job['result']['import_id'], 'dataset': 'QA-D1',
            'annotator_a': identities['a'], 'annotator_b': identities['b'], 'seed': 71})
        response.raise_for_status()
        batch = response.json()
        batch_seconds = time.perf_counter() - started
        assert batch['sample_count'] == 220
    async with httpx.AsyncClient(base_url=url, timeout=30, limits=httpx.Limits(max_connections=11)) as reader:
        await signed_in(reader, credentials['a'], password)
        response = await reader.get(PREFIX + '/me/tasks', params={'offset': 0, 'limit': 500})
        response.raise_for_status()
        tasks = [row for row in response.json()['items'] if row['batch_id'] == batch['id']]
        assert len(tasks) == 220
        semaphore = asyncio.Semaphore(11)
        async def read(index: int) -> float:
            async with semaphore:
                started = time.perf_counter()
                response = await reader.get(PREFIX + '/assignments/' + tasks[index % len(tasks)]['id'])
                response.raise_for_status()
                detail = response.json()
                assert detail['phase'] == 'BLIND' and 'gold' not in detail and 'points' not in detail
                assert 'expected_behavior' not in json.dumps(detail)
                return 1000 * (time.perf_counter() - started)
        latencies = await asyncio.gather(*(read(index) for index in range(110)))
    report = {'scope': 'synthetic local capacity smoke; no production acceptance', 'units': 2200,
              'sampled_units': 220, 'concurrent_connections': 11, 'successful_reads': len(latencies),
              'import_seconds': round(import_seconds, 3), 'batch_creation_seconds': round(batch_seconds, 3),
              'read_latency_ms': {'p50': round(statistics.median(latencies), 2),
                                  'p95': round(statistics.quantiles(latencies, n=100, method='inclusive')[94], 2),
                                  'max': round(max(latencies), 2)}, 'batch_id': batch['id'], 'external_alignment': 'NOT_ALIGNED'}
    target = ROOT / 'var/evidence/local-capacity-smoke.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
