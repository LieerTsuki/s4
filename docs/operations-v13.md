# v1.3 local operations and recovery

Current business requirements come from `liyue/document/00_v1.3执行入口与文档索引.md`, with 01/07/08/09 at their 2026-10-30 revisions. Historical 0003/REVIEW v2 evidence does not validate this version. Current implementation uses new 0004/0005 tables, the additive 0006 verification-round constraint and `/api/s4/v2`; session authentication and user administration retain the existing v1 endpoints.

## Current work flow

1. Create a separate lead, primary verification workers, two independent observation workers and designated verifier accounts. A real person must not occupy both observer seats; a trusted administrator is not an isolated blind worker.
2. Import a validated `openkb.s3-s4.v2` envelope. Difficulty is English; gold grades 3/2 and ranking grades 1/0 are separate; refusal is a strict boolean. Raw S3 denominators and provenance are preserved. An uploader is exposed to the imported drafts.
3. Plan N primary VERIFICATION units and a separate deterministic OBSERVATION scope n per dataset. Each main worker seals the relevant independent answer before REVIEW; observer A/B use the observation-wide BLIND barrier. Related material families remain subject to exposure checks.
4. Verify every current unit/revision. A high kappa does not complete missing primary records. Track unresolved material issues and proposed revisions; substantial changes require an independent verifier and a new final revision.
5. Observe kappa on frozen original paired labels. Gray/undefined observations show pending policy; low kappa returns the failed scope to S2 and cannot be cleared by merely resolving an issue. New regenerated inputs need their own provenance and human work.
6. Demo export requires a complete human verification ledger and actual observation evidence. `verified_annotations.jsonl` has N records; `observation_units.jsonl` and IAA have n. Downloads, actual delivery evidence and S5 acceptance are distinct events. Local demos never receive a formal S5 acceptance credential.

Legacy business writes are disabled by default with `LEGACY_READ_ONLY`. The compatibility setting `S4_LEGACY_WRITES_ENABLED=true` is reserved for isolated historical regression environments; it does not convert old records into current verification. Never use it to bypass a current policy blocker.

## Data and permissions

API and worker must share the same database **and** private data directory. Current new content lives under `controlled/objects/<prefix>/<sha256>.json`, and versioned exports under `exports-v13/<handoff-id>/`. Do not serve these directories through static hosting or expose object keys to unauthorized clients. Database-only backups cannot recover new content references.

The new file/index model does not erase old archived SQL bodies. Their protection and the remaining main-repository integration decision are described in [the storage ADR](adr/2026-10-30-v13-storage-and-main-repo-boundary.md). Main-repository SQLite schema, builder/typer behavior and actual upstream CI mappings are pending inputs rather than fabricated integrations.

## Backup and isolated recovery

Run management tools in the host management environment, not the least-privilege API container. They require the existing owner credentials in the ignored `.env` and Docker CLI access. Never print the file or pass connection URLs on a visible command line.

```powershell
Set-Location D:\openkb-eval\liyue\s4
.\.venv\Scripts\python.exe scripts/backup_restore.py backup --api-container openkb-s4-api-1 --output backups/CHOOSE-NEW-NAME
.\.venv\Scripts\python.exe scripts/backup_restore.py restore --backup backups/CHOOSE-NEW-NAME
```

The backup binds SQL dump, table counts, original uploads, published packages and private object references to one exported PostgreSQL snapshot. Recovery creates a **new** `s4_restore_YYYYMMDD_HHMMSS_xxxxxx` database and verifies counts, private content graph and both handoff versions. The existing business database is not overwritten. Keep the returned `restore-verification.json`.

Rehearse additive migrations only after that isolated recovery:

```powershell
.\.venv\Scripts\python.exe scripts/v13_migration_rehearsal.py --database s4_restore_YYYYMMDD_HHMMSS_xxxxxx --output var/evidence/NEW-migration-rehearsal.json
```

This command rejects `s4_dev`, `s4_test` and arbitrary database identifiers. It requires the matching restore proof, keeps the original table hashes and emits a new evidence file. The pre-upgrade backup is `backups/pre-v13-20261030-ops`; isolated proof is `var/s4_restore_20261030_142253_251ccf/restore-verification.json`. Migration evidence is `var/evidence/v13-isolated-migration.json` (0003→0005), `v13-isolated-migration-0006.json` (0005→0006) and `v13-migration-chain.json` (all 26 original business tables remain unchanged through the full chain).

## Maintenance rollout

First complete fresh functional/browser checks and the isolated migration rehearsal. Then stop this project's API/worker/gateway, leaving DB running. Capture the old business hashes with `scripts/verify_migration_history.py capture`, migrate with the owner, compare hashes **before restarting writers**, and rebuild/restart the three application services. Do not stop unrelated containers. If comparison or readiness fails, retain the old and new artifacts for diagnosis; recovery uses a new verified database and controlled cutover rather than a destructive downgrade.

Read-only reconciliation is available when the management host has the matching controlled data directory:

```powershell
.\.venv\Scripts\python.exe scripts/v13_reconcile.py --data-dir var --output var/evidence/v13-reconciliation.json
```

For Compose data, use a trusted management mount or copy matching artifacts from its private volume; the host `var` is not automatically the container volume. The report verifies reachable hashes, retains orphan objects, reports expired leases and never deletes files or changes business state. A missing or corrupted referenced object fails the report.

## CI status

`.gitlab-ci.yml` contains the local integration job. It needs a **dedicated Linux shell runner** tagged `s4-linux-shell`, with Python3.11, Node24, uv, Docker Compose and Gitleaks installed; port 55434 is reserved for its isolated PostgreSQL instance. Bootstrap refuses an existing `.env` and uses a job-specific Compose project. Cleanup verifies the project proof before removing that CI project's ephemeral volumes. No GitLab runner or remote pipeline has been registered or executed by these files.

The job runs locked dependencies, real PostgreSQL backend checks, frontend coverage/build/lint, contract generation drift, secret/dependency checks, v1.3 browser workflow, and backup/restore rehearsal. It does not claim the main repository's unprovided five gate definitions or human approvals. GitHub's prior workflow is explicitly historical and manual only.

Actual browser commands are `tests/e2e/prepare_v13.py`, API/worker on the resulting `.env.v13-e2e` isolated DB, Vite on port 5176, then `S4_E2E_URL=http://localhost:5176` and `npx playwright test v13.spec.js --reporter=list` in `tests/e2e`. CI selects Chromium; local runs may use installed Edge. These are automated synthetic checks, not the 20-question human acceptance exercise.
