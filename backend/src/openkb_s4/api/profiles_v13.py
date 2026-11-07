"""Independent local v1.3 profile lifecycle; approval cannot enable formal export."""
import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import lock_scope
from ..domain import profiles_v13 as domain
from ..domain.contracts import canonical_sha256
from ..domain.errors import DomainError
from ..models import User, now
from ..models_v13 import V13ProfileEvent, V13ProfileRevision
from ..schemas_v13 import StrictModel
from ..security import Actor, ApiError, Db, require_role
from ..services.common import audit
from ..services.content_store import ContentStore
from ..services.workflow_v13 import store_for

router = APIRouter()


class V13ProfileCreate(StrictModel):
    dataset: str
    version: str = Field(min_length=1, max_length=100)
    manual_version: str = Field(min_length=1, max_length=100)
    snapshot: dict[str, Any]
    reason: str = Field(min_length=1, max_length=50000)


class V13ProfilePatch(V13ProfileCreate):
    expected_revision: int = Field(ge=1)


class V13ProfileAction(StrictModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=50000)
    signature: str = Field(default="", max_length=5000)
    evidence: dict[str, Any] = Field(default_factory=dict)


def version_matches(item: V13ProfileRevision, expected: int) -> None:
    if item.revision != expected:
        raise ApiError(409, "VERSION_CONFLICT", "记录已变化，请刷新后再操作")


async def profile_record(db: AsyncSession, profile_id: str, lock: bool = False) -> V13ProfileRevision:
    if lock:
        await lock_scope(db, "v13-profile:" + profile_id)
    query = select(V13ProfileRevision).where(V13ProfileRevision.id == profile_id)
    item = await db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "配置不存在")
    return item


def profile_view(item: V13ProfileRevision, store: ContentStore) -> dict[str, Any]:
    return {"id": item.id, "dataset": item.dataset, "version": item.version,
            "manual_version": item.manual_version, "state": item.state, "revision": item.revision,
            "canonical_hash": item.canonical_hash, "creator_id": item.creator_id,
            "approver_id": item.approver_id, "created_at": item.created_at.isoformat(),
            "snapshot": store.read_json(item.snapshot_ref),
            "approval": store.read_json(item.approval_ref) if item.approval_ref else None}


async def seal_snapshot(item: V13ProfileRevision, snapshot: dict[str, Any], store: ContentStore) -> None:
    item.snapshot_ref = await asyncio.to_thread(store.put_json, snapshot)
    item.manual_ref = await asyncio.to_thread(store.put_json, {"version": snapshot["manual_version"], "text": snapshot["manual_text"]})
    item.vocabulary_ref = await asyncio.to_thread(store.put_json, snapshot["vocabulary"])
    item.canonical_hash = canonical_sha256(snapshot)


async def event(db: AsyncSession, request: Request, actor: User, item: V13ProfileRevision,
                action: str, reason: str, store: ContentStore, **details: Any) -> None:
    record_ref = await asyncio.to_thread(store.put_json, {
        "profile_revision_id": item.id, "revision": item.revision, "action": action,
        "actor_id": actor.id, "person_id": actor.person_id, "at": now().isoformat(),
        "reason": reason, "snapshot_ref": item.snapshot_ref, **details})
    db.add(V13ProfileEvent(profile_revision_id=item.id, revision=item.revision,
                          action=action, actor_id=actor.id, record_ref=record_ref))
    audit(db, request, actor.id, "V13_PROFILE_" + action.upper(), item.id,
          {"revision": item.revision, "state": item.state, "record_hash": record_ref["sha256"]})


@router.get("/profile-revisions/template")
async def profile_template(actor: Actor, dataset: str) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    return domain.template(dataset)


@router.get("/profile-revisions")
async def profiles(request: Request, actor: Actor, db: Db, offset: int = Query(0, ge=0),
                   limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    rows = (await db.scalars(select(V13ProfileRevision).order_by(V13ProfileRevision.created_at.desc())
                            .offset(offset).limit(limit))).all()
    return {"items": [profile_view(row, store_for(request)) for row in rows],
            "total": await db.scalar(select(func.count()).select_from(V13ProfileRevision))}


@router.get("/profile-revisions/{profile_id}")
async def profile_detail(profile_id: str, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead", "auditor")
    return profile_view(await profile_record(db, profile_id), store_for(request))


def validate_body(body: V13ProfileCreate) -> None:
    domain.validate_snapshot(body.dataset, body.snapshot)
    if body.version != body.snapshot["version"] or body.manual_version != body.snapshot["manual_version"]:
        raise ApiError(422, "PROFILE_VERSION_MISMATCH", "声明版本须与快照一致")
    if not body.reason.strip():
        raise ApiError(422, "REASON_REQUIRED", "须记录配置变更原因")


@router.post("/profile-revisions", status_code=201)
async def create_profile(body: V13ProfileCreate, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    validate_body(body)
    await lock_scope(db, "v13-profile-version:" + body.dataset + ":" + body.version)
    if await db.scalar(select(V13ProfileRevision.id).where(V13ProfileRevision.dataset == body.dataset,
                                                           V13ProfileRevision.version == body.version)):
        raise ApiError(409, "PROFILE_VERSION_EXISTS", "该数据集配置版本已存在，请创建新版本")
    item = V13ProfileRevision(dataset=body.dataset, version=body.version, manual_version=body.manual_version,
                              creator_id=actor.id, contributor_person_ids=[actor.person_id], state="DRAFT", revision=1)
    store = store_for(request)
    await seal_snapshot(item, body.snapshot, store)
    db.add(item)
    await db.flush()
    await event(db, request, actor, item, "create", body.reason, store)
    return profile_view(item, store)


@router.patch("/profile-revisions/{profile_id}")
async def update_profile(profile_id: str, body: V13ProfilePatch, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "lead")
    item = await profile_record(db, profile_id, True)
    version_matches(item, body.expected_revision)
    if item.state != "DRAFT":
        raise ApiError(409, "PROFILE_IMMUTABLE", "提交后的配置不可编辑，请另建版本")
    validate_body(body)
    if body.dataset != item.dataset or body.version != item.version:
        raise ApiError(422, "PROFILE_VERSION_MISMATCH", "草稿标识不能更换")
    store = store_for(request)
    await seal_snapshot(item, body.snapshot, store)
    item.manual_version = body.manual_version
    item.contributor_person_ids = sorted(set([*item.contributor_person_ids, actor.person_id]))
    item.revision += 1
    await event(db, request, actor, item, "update", body.reason, store)
    return profile_view(item, store)


@router.post("/profile-revisions/{profile_id}/{action}")
async def transition_profile(profile_id: str, action: str, body: V13ProfileAction,
                             request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    # Check role before loading state so a reviewer cannot submit through a stale state.
    require_role(actor, *( {"submit": ["lead"], "approve": ["auditor"], "retire": ["lead", "auditor"]}.get(action, ["lead", "auditor"])))
    item = await profile_record(db, profile_id, True)
    if not body.reason.strip():
        raise ApiError(422, "REASON_REQUIRED", "须记录配置操作原因")
    try:
        next_state = domain.transition(item.state, action, item.revision, body.expected_revision,
                                       actor.person_id, item.contributor_person_ids, actor.roles,
                                       body.signature, body.evidence)
    except DomainError as exc:
        raise ApiError(403 if exc.code in {"FORBIDDEN", "INDEPENDENT_APPROVAL_REQUIRED"} else
                       422 if exc.code == "APPROVAL_EVIDENCE_REQUIRED" else 409, exc.code, exc.message) from exc
    store = store_for(request)
    snapshot = store.read_json(item.snapshot_ref)
    domain.validate_snapshot(item.dataset, snapshot)
    if action == "submit":
        item.contributor_person_ids = sorted(set([*item.contributor_person_ids, actor.person_id]))
    if action == "approve":
        item.approver_id = actor.id
        item.approval_ref = await asyncio.to_thread(store.put_json, {
            "actor_id": actor.id, "person_id": actor.person_id, "signature": body.signature,
            "reason": body.reason, "evidence": body.evidence, "at": now().isoformat(),
            "canonical_hash": item.canonical_hash, "snapshot_ref": item.snapshot_ref,
            "scope": "LOCAL_PROFILE_ONLY", "formal_enabled": False})
    item.state = next_state
    item.revision += 1
    await event(db, request, actor, item, action, body.reason, store, approval_ref=item.approval_ref)
    return profile_view(item, store)
