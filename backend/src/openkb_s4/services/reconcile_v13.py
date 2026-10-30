"""Periodic index/file reconciliation; never repairs history or deletes objects."""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models_v13  # noqa: F401 -- worker also needs the referenced tables registered.
from ..config import Settings
from ..models import AuditEvent, Base
from ..models_handoff_v13 import V13Handoff
from .content_inventory import verify_controlled_graph
from .content_store import ContentStore
from .handoffs_v13 import verify_package


def inspect_objects(store: ContentStore, references: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        referenced = verify_controlled_graph(store, references)
        retained = len(store.inventory())
        return {"valid": True, "referenced_objects": referenced, "retained_objects": retained,
                "retained_unreferenced_objects": retained - referenced, "automatic_deletion": False}
    except (OSError, ValueError, TypeError, KeyError):
        return {"valid": False, "error_code": "CONTROLLED_OBJECT_INVALID", "automatic_deletion": False}


async def reconcile_v13(db: AsyncSession, settings: Settings) -> dict[str, Any]:
    if not await db.scalar(text("SELECT to_regclass('public.v13_imports')")):
        return {"supported": False, "reason": "V13_MIGRATION_PENDING", "findings": []}
    references = []
    malformed = False
    for table in Base.metadata.sorted_tables:
        if not table.name.startswith("v13_"):
            continue
        for column in table.columns:
            if not column.name.endswith("_ref"):
                continue
            values = (await db.scalars(select(column).where(column.is_not(None)))).all()
            for value in values:
                if value is None:
                    continue
                if not isinstance(value, dict) or set(value) != {"object_key", "sha256"}:
                    malformed = True
                else:
                    references.append(value)
    for details in (await db.scalars(select(AuditEvent.details).where(AuditEvent.action == "V13_IMPORT_FILE_UPLOADED"))).all():
        value = details.get("raw_file_ref")
        if not isinstance(value, dict) or set(value) != {"object_key", "sha256"}:
            malformed = True
        else:
            references.append(value)
    store = ContentStore(settings.data_dir / "controlled")
    inventory = await asyncio.to_thread(inspect_objects, store, references)
    if malformed:
        inventory = {"valid": False, "error_code": "CONTROLLED_REFERENCE_INVALID", "automatic_deletion": False}
    findings = []
    if not inventory["valid"]:
        findings.append({"kind": "V13_CONTROLLED_OBJECT_INVALID", "object_type": "v13_storage",
                         "object_id": "controlled", "details": {"error_code": inventory["error_code"]}, "severity": "ERROR"})
    handoffs = (await db.scalars(select(V13Handoff))).all()
    for row in handoffs:
        try:
            manifest = await asyncio.to_thread(store.read_json, row.manifest_ref)
            await asyncio.to_thread(verify_package, settings.data_dir / "exports-v13" / row.id, manifest)
        except (OSError, ValueError, KeyError, TypeError):
            findings.append({"kind": "V13_PUBLISHED_SNAPSHOT_INVALID", "object_type": "v13_handoff",
                             "object_id": row.id, "details": {"error_code": "SNAPSHOT_INVALID"}, "severity": "ERROR"})
    published = {row.id for row in handoffs}
    export_root = settings.data_dir / "exports-v13"
    if export_root.is_dir():
        for path in export_root.iterdir():
            if path.is_dir() and path.name not in published:
                findings.append({"kind": "V13_UNPUBLISHED_PARTIAL" if path.name.endswith(".partial") else "V13_ORPHAN_SNAPSHOT",
                                 "object_type": "v13_storage", "object_id": "unpublished",
                                 "details": {"automatic_deletion": False}, "severity": "WARNING"})
    return {"supported": True, "objects": inventory, "handoffs_checked": len(handoffs), "findings": findings}
