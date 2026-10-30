"""Shared dual-track policy. No source, answer or submitted text is stored in SQL."""

from collections.abc import Sequence
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import lock_scope
from ..domain.contracts import canonical_sha256
from ..models import Exposure, User, now
from ..models_v13 import (
    V13Assignment,
    V13Batch,
    V13Draft,
    V13Exposure,
    V13Import,
    V13Issue,
    V13QualityAction,
    V13Revision,
    V13Submission,
    V13Unit,
    V13Verification,
)
from ..security import ApiError, require_role
from .content_store import ContentStore

BLIND_FIELDS = frozenset({"unit_id", "dataset", "difficulty", "question", "text", "chunk", "corpus_id",
                          "text_digest", "schema_version", "acl_context", "time_context", "scope_context", "payload"})
CONTEXT_FIELDS = frozenset({"doc_id", "text", "title", "sha256", "version", "page", "start", "end",
                            "license", "source_url", "valid_from", "valid_until", "acl_context"})


def store_for(request: Request) -> ContentStore:
    return ContentStore(request.app.state.settings.data_dir / "controlled")


def split_unit(unit: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use a positive BLIND allowlist, never merely remove a top-level gold field."""
    material = {key: value for key, value in unit.items() if key in BLIND_FIELDS}
    material["contexts"] = [{key: value for key, value in doc.items() if key in CONTEXT_FIELDS}
                            for doc in unit.get("contexts", [])]
    concealed = {key: value for key, value in unit.items() if key not in material}
    return material, concealed


def family_keys(unit: dict[str, Any]) -> list[str]:
    keys = {unit["unit_id"]}
    for field in ("source_case_ids", "family_keys"):
        for value in unit.get(field, []):
            keys.add(str(value))
    metadata = unit.get("metadata", {})
    for field in ("source_case_ids", "family_keys"):
        keys.update(str(value) for value in metadata.get(field, []))
    for field in ("pair_id", "paired_unit_id", "source_case_id"):
        value = unit.get(field) or metadata.get(field)
        if value:
            keys.add(str(value))
    return sorted(keys)


def family_components(families: list[list[str]]) -> dict[str, set[str]]:
    """Union known lineage, including intermediates with no current assignment."""
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for family in families:
        if not family:
            continue
        first = find(family[0])
        for key in family[1:]:
            parent[find(key)] = first
    groups: dict[str, set[str]] = {}
    for key in parent:
        groups.setdefault(find(key), set()).add(key)
    return {key: groups[find(key)] for key in parent}


def family_scope(keys: set[str], families: list[list[str]]) -> set[str]:
    components = family_components(families)
    return {related for key in keys for related in components.get(key, {key})}


async def hidden_import_ids(db: AsyncSession, actor: User) -> set[str]:
    own_families = (await db.scalars(select(V13Unit.family_keys).join(V13Assignment,
        V13Assignment.unit_index_id == V13Unit.id).where(V13Assignment.user_id == actor.id))).all()
    if not own_families:
        return set()
    indexed = (await db.execute(select(V13Unit.import_id, V13Unit.family_keys))).all()
    scope = family_scope({key for family in own_families for key in family}, [family for _, family in indexed])
    return {identity for identity, family in indexed if scope.intersection(family)}


async def get_import(db: AsyncSession, import_id: str, lock: bool = False) -> V13Import:
    query = select(V13Import).where(V13Import.id == import_id)
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    return row


async def business_access(db: AsyncSession, actor: User, import_id: str) -> None:
    require_role(actor, "lead", "auditor", "arbitrator")
    if import_id in await hidden_import_ids(db, actor):
        raise ApiError(403, "PARTICIPANT_RESTRICTED", "本人曾参与该来源或关联材料族作业，不能读取受限运营材料")


async def get_batch(db: AsyncSession, batch_id: str, lock: bool = False) -> V13Batch:
    query = select(V13Batch).where(V13Batch.id == batch_id)
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    return row


async def assert_unexposed(db: AsyncSession, user: User, units: list[V13Unit]) -> None:
    await lock_scope(db, "v13-person:" + user.person_id)
    if "admin" in user.roles:
        raise ApiError(422, "TRUSTED_ADMIN_NOT_BLIND", "受信任系统管理员不能同时登记为隔离盲答人员")
    families = list((await db.scalars(select(V13Unit.family_keys))).all())
    keys = family_scope({key for unit in units for key in unit.family_keys}, families)
    exposed = await db.scalar(select(V13Exposure.id).where(V13Exposure.person_id == user.person_id,
                              V13Exposure.family_key.in_(keys)).limit(1))
    historical = (await db.scalars(select(Exposure).where(Exposure.user_id == user.id))).all()
    if exposed or any(keys.intersection(item.family_keys) for item in historical):
        raise ApiError(409, "MATERIAL_ALREADY_EXPOSED", "该人员已接触同族草案，不能作为首次独立作答人员")


async def annotator(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None or not user.active or "annotator" not in user.roles:
        raise ApiError(422, "ANNOTATOR_REQUIRED", "分配对象须为有效核实员账号")
    return user


async def assert_assignment_compatible(db: AsyncSession, user: User, units: list[V13Unit], kind: str) -> None:
    await assert_unexposed(db, user, units)
    other = (await db.scalars(select(V13Assignment).join(V13Batch,
        V13Batch.id == V13Assignment.batch_id).where(V13Batch.workflow_kind != kind,
        V13Assignment.user_id == user.id))).all()
    other_units = (await db.scalars(select(V13Unit).where(V13Unit.id.in_([row.unit_index_id for row in other])))).all()
    keys = family_scope({key for unit in units for key in unit.family_keys},
                        list((await db.scalars(select(V13Unit.family_keys))).all()))
    if any(keys.intersection(unit.family_keys) for unit in other_units):
        raise ApiError(409, "OBSERVATION_PRIMARY_CONFLICT", "主核实与首次观测不能复用同族人员，需先确认复用协议")


def mark_exposure(db: AsyncSession, user: User, unit: V13Unit, assignment_id: str | None,
                  reason: str) -> None:
    for key in unit.family_keys:
        db.add(V13Exposure(person_id=user.person_id, family_key=key,
                           assignment_id=assignment_id, reason=reason))


async def task_view(db: AsyncSession, assignment: V13Assignment, batch: V13Batch,
                    unit: V13Unit) -> dict[str, Any]:
    paused = await db.scalar(select(V13Issue.id).where(V13Issue.unit_index_id == unit.id,
                              V13Issue.status == "OPEN").limit(1))
    return {"id": assignment.id, "batch_id": batch.id, "unit_index_id": unit.id,
            "unit_id": unit.unit_id, "dataset": unit.dataset, "workflow_kind": batch.workflow_kind,
            "phase": assignment.phase, "status": assignment.status, "paused": bool(paused),
            "content_revision": assignment.content_revision, "profile_version": batch.profile_version,
            "manual_version": batch.manual_version, "review_version": "openkb.s4-review.v3",
            "active": assignment.active, "round": batch.round}


async def own_task(db: AsyncSession, actor: User, assignment_id: str,
                   lock: bool = False) -> tuple[V13Assignment, V13Batch, V13Unit]:
    row = await db.get(V13Assignment, assignment_id)
    if row is None or row.user_id != actor.id:
        raise ApiError(404, "NOT_FOUND", "资源不可见或不存在")
    batch = await get_batch(db, row.batch_id, lock)
    if lock:
        await get_import(db, batch.import_id, lock=True)
        await db.refresh(row)
    unit = await db.get(V13Unit, row.unit_index_id)
    if unit is None:
        raise ApiError(409, "CONTENT_MISSING", "冻结原文引用缺失")
    return row, batch, unit


async def assert_task_writable(db: AsyncSession, assignment: V13Assignment,
                               batch: V13Batch, unit: V13Unit, phase: str) -> None:
    imported = await get_import(db, batch.import_id)
    if imported.status == "RETURNED_TO_S2" or batch.state in {"RETURNED_TO_S2", "CANCELLED", "SUPERSEDED"}:
        raise ApiError(409, "BATCH_CLOSED", "原批已退回或终止，必须保留原记录并新建有效流程")
    if not assignment.active:
        raise ApiError(409, "ASSIGNMENT_REPLACED", "分配已失效；原始封存保留")
    if assignment.phase != phase or assignment.status != "OPEN":
        raise ApiError(409, "PHASE_CONFLICT", "当前阶段不允许提交，请刷新任务")
    await assert_frozen_profile(db, batch)
    if await db.scalar(select(V13Issue.id).where(V13Issue.unit_index_id == unit.id,
                        V13Issue.status == "OPEN").limit(1)):
        raise ApiError(409, "MATERIAL_BLOCKED", "材料工单未解决，任务暂停")


async def assert_frozen_profile(db: AsyncSession, batch: V13Batch) -> None:
    units = list((await db.scalars(select(V13Unit).where(V13Unit.import_id == batch.import_id,
                                             V13Unit.unit_id.in_(batch.selected_ids)))).all())
    if batch.frozen_hash != frozen_hash(units, batch.profile_version, batch.manual_version,
                                        batch.sample_ledger.get("revision_map")):
        raise ApiError(409, "FROZEN_PROFILE_CONFLICT", "冻结内容或表单定义已变化，须保留原轮并明确升级规则")


async def assert_review_visible(db: AsyncSession, actor: User, unit: V13Unit) -> None:
    """A related gold read cannot overtake any of this person's active blind work."""
    await lock_scope(db, "v13-person:" + actor.person_id)
    tasks = (await db.execute(select(V13Assignment, V13Unit).join(V13Unit,
        V13Unit.id == V13Assignment.unit_index_id).join(V13Batch,
        V13Batch.id == V13Assignment.batch_id).where(V13Assignment.user_id == actor.id,
        V13Assignment.active.is_(True), V13Batch.state.notin_(["SUPERSEDED", "CANCELLED", "RETURNED_TO_S2"])))).all()
    scope = family_scope(set(unit.family_keys), list((await db.scalars(select(V13Unit.family_keys))).all()))
    related = [task for task, indexed in tasks if scope.intersection(indexed.family_keys)]
    sealed = set((await db.scalars(select(V13Submission.assignment_id).where(
        V13Submission.assignment_id.in_([row.id for row in related]), V13Submission.phase == "BLIND"))).all())
    if any(row.id not in sealed for row in related):
        raise ApiError(409, "FAMILY_BLIND_INCOMPLETE", "本人同族独立任务尚未全部封存，不能提前读取草案")


async def require_primary_review(db: AsyncSession, unit: V13Unit) -> V13Assignment:
    assignment = await db.scalar(select(V13Assignment).join(V13Batch,
        V13Batch.id == V13Assignment.batch_id).where(V13Assignment.unit_index_id == unit.id,
        V13Assignment.active.is_(True), V13Batch.workflow_kind == "VERIFICATION",
        V13Batch.state.notin_(["SUPERSEDED", "CANCELLED", "RETURNED_TO_S2"])))
    if assignment is None:
        raise ApiError(409, "PRIMARY_VERIFICATION_REQUIRED", "修订不能代替本单元主核实人员的独立作答和草案比对")
    phases = set((await db.scalars(select(V13Submission.phase).where(
        V13Submission.assignment_id == assignment.id))).all())
    if phases != {"BLIND", "REVIEW"}:
        raise ApiError(409, "PRIMARY_VERIFICATION_REQUIRED", "本单元须先完成真实主核实两阶段封存")
    return assignment


async def main_release(db: AsyncSession, batch: V13Batch) -> None:
    """Release only already sealed per-person family scopes, never the full N barrier."""
    tasks = (await db.scalars(select(V13Assignment).join(V13Batch, V13Batch.id == V13Assignment.batch_id).where(
        V13Assignment.active.is_(True), V13Batch.state.notin_(["RETURNED_TO_S2", "CANCELLED", "SUPERSEDED"])))).all()
    units = {unit.id: unit for unit in (await db.scalars(select(V13Unit))).all()}
    components = family_components([unit.family_keys for unit in units.values()])
    batch_kinds = {identity: kind for identity, kind in (await db.execute(select(V13Batch.id, V13Batch.workflow_kind).where(V13Batch.id.in_([task.batch_id for task in tasks])))).all()}
    sealed = set((await db.scalars(select(V13Submission.assignment_id).where(
        V13Submission.assignment_id.in_([row.id for row in tasks]), V13Submission.phase == "BLIND"))).all())
    incomplete_groups = {(row.user_id, min(components[units[row.unit_index_id].family_keys[0]]))
                         for row in tasks if row.id not in sealed}
    for row in tasks:
        if batch_kinds[row.batch_id] != "VERIFICATION" or row.phase != "BLIND" or row.id not in sealed:
            continue
        group = (row.user_id, min(components[units[row.unit_index_id].family_keys[0]]))
        if group not in incomplete_groups:
            row.phase, row.status = "REVIEW", "OPEN"
    local_tasks = [task for task in tasks if task.batch_id == batch.id]
    if local_tasks and all(row.phase == "REVIEW" for row in local_tasks):
        batch.state = "VERIFY_OPEN"


async def batch_view(db: AsyncSession, batch: V13Batch, store: ContentStore) -> dict[str, Any]:
    tasks = (await db.scalars(select(V13Assignment).where(V13Assignment.batch_id == batch.id,
                                               V13Assignment.active.is_(True)))).all()
    ids = [row.id for row in tasks]
    submissions = (await db.scalars(select(V13Submission).where(V13Submission.assignment_id.in_(ids)))).all()
    total = await db.scalar(select(func.count()).select_from(V13Unit).where(V13Unit.import_id == batch.import_id,
                                                                    V13Unit.dataset == batch.dataset))
    quality = store.read_json(batch.quality_ref) if batch.quality_ref else None
    unit_rows = (await db.scalars(select(V13Unit).where(V13Unit.import_id == batch.import_id,
                                                        V13Unit.unit_id.in_(batch.selected_ids)))).all()
    passed = await current_verification_records(db, store, unit_rows)
    return {"id": batch.id, "import_id": batch.import_id, "dataset": batch.dataset,
            "workflow_kind": batch.workflow_kind, "state": batch.state, "round": batch.round,
            "N": total, "sample_count": len(batch.selected_ids), "selected_ids": batch.selected_ids,
            "sample_ledger": batch.sample_ledger, "profile_version": batch.profile_version,
            "manual_version": batch.manual_version, "frozen_hash": batch.frozen_hash,
            "blind_submitted": sum(row.phase == "BLIND" for row in submissions),
            "review_submitted": sum(row.phase == "REVIEW" for row in submissions),
            "verification_completed": len(passed),
            "quality": quality, "parent_id": batch.parent_id,
            "assignments": [{"id": row.id, "unit_index_id": row.unit_index_id,
                             "user_id": row.user_id, "seat": row.seat, "phase": row.phase,
                             "status": row.status} for row in tasks]}


async def current_verification_records(db: AsyncSession, store: ContentStore,
                                       units: Sequence[V13Unit]) -> dict[str, V13Verification]:
    """Count only the active primary signatures or revisions anchored to them."""
    ids = [unit.id for unit in units]
    verified = (await db.scalars(select(V13Verification).where(V13Verification.unit_index_id.in_(ids))
        .order_by(V13Verification.created_at.desc(), V13Verification.id.desc()))).all()
    primary = (await db.execute(select(V13Assignment, V13Batch).join(V13Batch,
        V13Batch.id == V13Assignment.batch_id).where(V13Assignment.unit_index_id.in_(ids),
        V13Batch.workflow_kind == "VERIFICATION", V13Assignment.active.is_(True),
        V13Batch.state.notin_(["SUPERSEDED", "CANCELLED", "RETURNED_TO_S2"])))).all()
    primary_phases = (await db.execute(select(V13Submission.assignment_id, V13Submission.phase).where(
        V13Submission.assignment_id.in_([assignment.id for assignment, _ in primary])))).all()
    phases_by_assignment: dict[str, set[str]] = {}
    for identity, phase in primary_phases:
        phases_by_assignment.setdefault(identity, set()).add(phase)
    sealed_primary = {assignment.id for assignment, _ in primary
                      if phases_by_assignment.get(assignment.id) == {"BLIND", "REVIEW"}}
    primary_by_unit = {assignment.unit_index_id: assignment.id for assignment, _ in primary if assignment.id in sealed_primary}
    revisions = {unit.id: unit.final_revision or unit.content_revision for unit in units}
    result = {}
    for record in verified:
        if record.unit_index_id in result or record.verdict != "VERIFIED" or record.content_revision != revisions[record.unit_index_id]:
            continue
        active_id = primary_by_unit.get(record.unit_index_id)
        if not active_id:
            continue
        if record.assignment_id == active_id or record.assignment_id is None and store.read_json(record.record_ref).get("primary_assignment_id") == active_id:
            result[record.unit_index_id] = record
    return result


async def import_report(db: AsyncSession, store: ContentStore, imported: V13Import) -> dict[str, Any]:
    units = list((await db.scalars(select(V13Unit).where(V13Unit.import_id == imported.id))).all())
    verified_records = await current_verification_records(db, store, units)
    completed = len(verified_records)
    blockers = list(imported.blockers)
    if completed != len(units):
        blockers.append(f"VERIFICATION_INCOMPLETE:{len(units) - completed}")
    batches = (await db.scalars(select(V13Batch).where(V13Batch.import_id == imported.id))).all()
    observations = [row for row in batches if row.workflow_kind == "OBSERVATION" and row.state != "SUPERSEDED"
                    and (not row.parent_id or row.sample_ledger.get("purpose") == "REPLACEMENT")]
    expansions = [row for row in batches if row.workflow_kind == "OBSERVATION" and row.state != "SUPERSEDED"
                  and row.parent_id and row.sample_ledger.get("purpose") != "REPLACEMENT"]
    observed_datasets = {row.dataset for row in observations}
    for dataset in sorted({unit.dataset for unit in units} - observed_datasets):
        blockers.append("OBSERVATION_MISSING:" + dataset)
    n = sum(len(row.selected_ids) for row in observations)
    pairs = 0
    quality_summaries = []
    expansion_pairs = 0
    policy = ["EXTERNAL_ALIGNMENT_NOT_CONFIRMED", "POLICY_J1_C1_PENDING"]
    for batch in [*observations, *expansions]:
        is_expansion = batch in expansions
        if batch.sample_ledger.get("shortfall", 0):
            blockers.append("OBSERVATION_SAMPLE_SHORTFALL:" + batch.dataset)
        if batch.quality_ref:
            quality = store.read_json(batch.quality_ref)
            if is_expansion:
                expansion_pairs += int(quality.get("pair_count", 0))
            else:
                pairs += int(quality.get("pair_count", 0))
            quality_summaries.append({"batch_id": batch.id, "dataset": batch.dataset, "quality_ref": batch.quality_ref,
                                      "scope_kind": "EXPANSION" if is_expansion else "INITIAL", **quality})
            if quality.get("action") == "RETURN_TO_S2":
                blockers.append("RETURNED_TO_S2")
            elif quality.get("action") in {"EXPAND_CALIBRATE", "UNDEFINED"}:
                policy.append("QUALITY_POLICY_PENDING:" + batch.dataset)
        else:
            blockers.append(("EXPANSION_INCOMPLETE:" + batch.id) if is_expansion else "OBSERVATION_NOT_CALCULATED:" + batch.dataset)
    if pairs != n:
        blockers.append("OBSERVATION_PAIRS_INCOMPLETE")
    observed_batches = [*observations, *expansions]
    observed_assignments = (await db.scalars(select(V13Assignment).where(
        V13Assignment.batch_id.in_([batch.id for batch in observed_batches]), V13Assignment.active.is_(True)))).all()
    observed_reviews = (await db.scalars(select(V13Submission).where(V13Submission.assignment_id.in_(
        [assignment.id for assignment in observed_assignments]), V13Submission.phase == "REVIEW"))).all()
    observed_by_id = {assignment.id: assignment for assignment in observed_assignments}
    actions = (await db.scalars(select(V13QualityAction).where(V13QualityAction.batch_id.in_(
        [batch.id for batch in observed_batches]), V13QualityAction.kind == "DISAGREEMENT_REVIEW"))).all()
    retained: set[tuple[str, str, str]] = set()
    for action in actions:
        value = store.read_json(action.record_ref)
        evidence = value.get("evidence", {})
        if evidence.get("resolution") == "KEEP_SOURCE":
            retained.add((action.batch_id, evidence.get("unit_index_id", ""), evidence.get("content_revision", "")))
    findings: set[str] = set()
    by_id = {unit.id: unit for unit in units}
    for review in observed_reviews:
        value = store.read_json(review.payload_ref)
        if value.get("verdict") == "VERIFIED":
            continue
        assignment = observed_by_id[review.assignment_id]
        unit = by_id[assignment.unit_index_id]
        revised = unit.id in verified_records and unit.final_revision and unit.final_revision != assignment.content_revision
        if not revised and (assignment.batch_id, unit.id, assignment.content_revision) not in retained:
            findings.add(unit.id)
    if findings:
        blockers.append(f"OBSERVATION_CONTENT_FINDINGS:{len(findings)}")
    issues = await db.scalar(select(func.count()).select_from(V13Issue).where(V13Issue.import_id == imported.id,
                                                                              V13Issue.status == "OPEN"))
    if issues:
        blockers.append(f"OPEN_MATERIAL_ISSUES:{issues}")
    revisions = (await db.scalars(select(V13Revision).where(V13Revision.unit_index_id.in_([unit.id for unit in units])))).all()
    current_revisions = {unit.id: unit.final_revision or unit.content_revision for unit in units}
    unresolved = sum(row.status == "PENDING" or row.status == "FAIL" and row.source_revision == current_revisions[row.unit_index_id]
                     for row in revisions)
    if unresolved:
        blockers.append(f"UNRESOLVED_REVISIONS:{unresolved}")
    returned = imported.status == "RETURNED_TO_S2" or "RETURNED_TO_S2" in blockers
    if returned:
        blockers.append("RETURNED_TO_S2")
    content_ready = bool(units) and not blockers
    readiness = ("RETURNED_TO_S2" if returned else "WAITING_VERIFICATION" if completed < len(units)
                 else "WAITING_EVIDENCE" if blockers else "WAITING_POLICY")
    return {"import_id": imported.id, "N": len(units), "n": n,
            "verification_completed": completed, "observation_completed": pairs,
            "expanded_observation_count": sum(len(row.selected_ids) for row in expansions),
            "expanded_observation_completed": expansion_pairs,
            "observation_scope_count": len({identity for batch in observed_batches for identity in batch.selected_ids}),
            "expansions": [{"batch_id": batch.id, "parent_id": batch.parent_id, "state": batch.state,
                             "sample_count": len(batch.selected_ids), "selected_ids": batch.selected_ids,
                             "quality_ref": batch.quality_ref} for batch in expansions],
            "verification_remaining": len(units) - completed, "readiness": readiness,
            "content_ready": content_ready, "demo_ready": content_ready and imported.mode == "demo",
            "blockers": sorted(set(blockers + policy)), "content_blockers": sorted(set(blockers)),
            "policy_blockers": sorted(set(policy)), "quality": quality_summaries,
            "mode": imported.mode, "external_alignment": "NOT_ALIGNED",
            "contract_version": "openkb.s4-s5.v2"}


async def verification_record(db: AsyncSession, store: ContentStore, unit: V13Unit,
                               actor: User, assignment: V13Assignment | None,
                               payload: dict[str, Any], revision: str) -> V13Verification:
    record = {"unit_id": unit.unit_id, "content_revision": revision, "annotator": actor.id,
              "person_id": actor.person_id, "verdict": payload["verdict"],
              "verified_at": now().isoformat(), "review_ref": store.put_json(payload),
              "assignment_id": assignment.id if assignment else None,
              "primary_assignment_id": assignment.id if assignment else payload.get("primary_assignment_id"),
              "review_version": "openkb.s4-review.v3"}
    row = V13Verification(import_id=unit.import_id, unit_index_id=unit.id,
                          assignment_id=assignment.id if assignment else None, actor_id=actor.id,
                          content_revision=revision, verdict=payload["verdict"], record_ref=store.put_json(record))
    db.add(row)
    return row


async def read_draft(db: AsyncSession, store: ContentStore, assignment_id: str,
                      phase: str) -> dict[str, Any] | None:
    draft = await db.scalar(select(V13Draft).where(V13Draft.assignment_id == assignment_id, V13Draft.phase == phase))
    return {"version": draft.version, "payload": store.read_json(draft.payload_ref)} if draft else None


def frozen_hash(units: list[V13Unit], profile_version: str, manual_version: str,
                revision_map: dict[str, str] | None = None) -> str:
    from ..domain.v13 import QUOTAS, SPECIALIZED_FIELDS, ReviewV3
    return canonical_sha256({"units": sorted((unit.unit_id, (revision_map or {}).get(unit.unit_id, unit.content_revision)) for unit in units),
                             "profile_version": profile_version, "manual_version": manual_version,
                             "review_version": "openkb.s4-review.v3", "review_schema": ReviewV3.model_json_schema(),
                             "quotas": QUOTAS, "specialized_fields": SPECIALIZED_FIELDS,
                             "profile_state": "LOCAL_BASELINE_PENDING_EXTERNAL_APPROVAL"})
