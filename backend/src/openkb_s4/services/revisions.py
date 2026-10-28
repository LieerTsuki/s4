"""Immutable material/gold revisions and candidate revision classification."""

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.contracts import canonical_sha256
from ..models import GoldRevision, SourceImport, UnitRevision
from ..security import ApiError


async def ensure_revisions(
    db: AsyncSession, imported: SourceImport
) -> dict[str, tuple[UnitRevision, GoldRevision]]:
    material_rows = (
        await db.scalars(select(UnitRevision).where(UnitRevision.import_id == imported.id))
    ).all()
    by_id = {row.unit_id: row for row in material_rows}
    result: dict[str, tuple[UnitRevision, GoldRevision]] = {}
    gold: GoldRevision | None
    for unit in imported.payload["units"]:
        material = by_id.get(unit["unit_id"])
        if material is None:
            concealed = {"gold", "expected_behavior", "key_facts", "quality_metrics"}
            visible = {key: value for key, value in unit.items() if key not in concealed}
            material = UnitRevision(
                import_id=imported.id,
                unit_id=unit["unit_id"],
                material=visible,
                content_hash=canonical_sha256(visible),
                source_hash=canonical_sha256(unit),
            )
            db.add(material)
            await db.flush()
            gold = GoldRevision(
                unit_revision_id=material.id,
                gold=unit.get("gold", {}),
                review_material={
                    key: value for key, value in unit.items() if key in concealed and key != "gold"
                },
                content_hash=canonical_sha256(
                    {key: value for key, value in unit.items() if key in concealed}
                ),
            )
            db.add(gold)
            await db.flush()
        else:
            gold = await db.scalar(
                select(GoldRevision).where(GoldRevision.unit_revision_id == material.id)
            )
            if gold is None:
                raise ApiError(409, "REVISION_MISSING", "冻结草案revision缺失")
        result[unit["unit_id"]] = (material, gold)
    return result


def final_candidate(unit: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    candidate = deepcopy(unit)
    if unit["dataset"].startswith("QA") and unit["dataset"] != "QA-D6":
        candidate["gold"] = deepcopy(gold)
    return candidate


def change_kind(unit: dict[str, Any], gold: dict[str, Any]) -> str:
    original = unit.get("gold", {})
    if original == gold:
        return "UNCHANGED"
    before = {k: v for k, v in original.items() if k != "gold_spans"}
    after = {k: v for k, v in gold.items() if k != "gold_spans"}
    return "LOCATOR_ONLY" if before == after else "SUBSTANTIVE"


async def resolve_source_cases(
    db: AsyncSession, import_id: str, unit: dict[str, Any]
) -> dict[str, Any]:
    """Resolve only the exact frozen import; missing source families stay explicit."""
    resolved = []
    composition: dict[str, int] = {}
    evidence_union: set[str] = set()
    for case_id in unit.get("source_case_ids", []):
        material = await db.scalar(
            select(UnitRevision).where(
                UnitRevision.import_id == import_id, UnitRevision.unit_id == case_id
            )
        )
        if material is None:
            resolved.append({"unit_id": case_id, "status": "NOT_IN_FROZEN_IMPORT"})
            composition["UNRESOLVED"] = composition.get("UNRESOLVED", 0) + 1
            continue
        gold = await db.scalar(
            select(GoldRevision).where(GoldRevision.unit_revision_id == material.id)
        )
        dataset = material.material["dataset"]
        composition[dataset] = composition.get(dataset, 0) + 1
        docs = gold.gold.get("gold_doc_ids", []) if gold else []
        evidence_union.update(docs)
        resolved.append(
            {
                "unit_id": case_id,
                "status": "RESOLVED",
                "dataset": dataset,
                "source_hash": material.source_hash,
                "unit_revision_id": material.id,
                "gold_doc_ids": docs,
            }
        )
    return {
        "resolved_sources": resolved,
        "source_composition": composition,
        "evidence_union": sorted(evidence_union),
        "k_rule_status": "UNCONFIRMED",
    }
