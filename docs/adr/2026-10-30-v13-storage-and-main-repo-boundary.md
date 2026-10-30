# ADR: v1.3 operational indexes, private content objects and integration boundary

Date: 2026-10-30. Status: adopted for the local migration; main-repository deployment and database replacement remain pending upstream review.

## Context

The current requirements are indexed by `liyue/document/00_v1.3执行入口与文档索引.md`. Implementation scheme 08 V2.0 requires full human verification and a separate observation branch, private file-backed material/gold/submissions, a main-repository SQLite index mapping, builder/typer integration and GitLab CI. The existing application has PostgreSQL operations and historical v1/v2 JSON bodies. The supplied materials do not include the main repository's actual SQLite v1.1 schema, CLI wait semantics, complete D6 vocabulary or authoritative CI five-gate configuration.

## Decision

1. Keep the current `liyue/s4` working directory and PostgreSQL job/session/operational database for a reversible local migration. Add explicit v1.3 tables and `/api/s4/v2`; do not mutate historical records into current verification records.
2. New material, gold, source, draft, sealed review, quality action and handoff content are private content-addressed UTF-8 objects. New tables hold object references, SHA256, operational identity and necessary state/index fields. Source material and concealed gold have separate references so BLIND reads do not fetch the concealed object.
3. Seal content before publishing its reference in a database transaction. This is not a distributed atomic transaction. Crashes may retain unreferenced objects; read-only reconciliation reports them and never automatically deletes sealed content. Every read, export, backup and isolated restore must verify the relevant content graph.
4. Preserve historical PostgreSQL bodies and their original hashes under read-only legacy business APIs. This is a protected migration boundary, **not a claim that every historical body has already been physically removed from SQL**. A subsequent controlled archive must first verify complete old nested JSON/text coverage, historical access adapters, backup/restore and permission behavior. No broad `UPDATE`/`DELETE` migration or destructive downgrade is included.
5. Old evidence labels and answerability are not mechanically converted. Old 2 cannot distinguish direct support from necessary supporting evidence; ambiguous out_of_scope is not assumed to mean permissions. A new validated source/revision and actual human work are required for v1.3 records.
6. Do not invent SQLite columns or write speculative main-repository SQL. Keep a versioned adapter boundary and report main-repository mapping pending. Likewise, the local GitLab job exercises this repository on a dedicated runner; it is not evidence that the main repository or its five gates have accepted this application.
7. Formal S3/S5 protocols, J1/C1 policy and specialist dictionaries remain explicit external dependencies. Neither a local configuration switch, synthetic fixture nor this ADR can sign external approval.

## Consequences and verification

The isolated rehearsals in `var/evidence/v13-isolated-migration.json` and `var/evidence/v13-isolated-migration-0006.json` compare every original business column, count and row hash through 0003→0005→0006. `var/evidence/v13-migration-chain.json` verifies that all 26 initial business-table hashes survive the full chain. These checks used a newly restored database, not the live development DB. The management tools reject live/test targets for rehearsal; SQL/reference reconciliation uses a repeatable-read read-only transaction and emits counts/hashes only.

Deployment requires a consistent backup that includes private objects, an isolated recovery, a stopped-writer before/after hash comparison and a maintenance window. Merely reverting the API image is not a database/content rollback strategy. Main-repository DB/CLI/identity/Schema synchronization and independent-service retention must be reviewed with the actual maintainers before formal rollout.

No new runtime dependency was introduced for this decision.
