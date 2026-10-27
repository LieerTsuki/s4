"""All-or-nothing snapshot export and independent local integrity verification."""
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..domain.contracts import canonical_sha256
from ..models import (
    Agreement,
    AnnotationBatch,
    Arbitration,
    Assignment,
    FinalDecision,
    Handoff,
    SourceImport,
    Submission,
)
from ..security import ApiError

FILES = {"units_for_s5.jsonl", "labeled.jsonl", "iaa_records.jsonl", "s4_report.json", "arbitration_log.jsonl", "s4_handoff_manifest.json"}


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(encoded(row) + b"\n" for row in rows)


def verify_snapshot(directory: Path, manifest: dict[str, Any], *, allow_missing_manifest: bool = False) -> None:
    """Recompute every declared digest and line count before consumption."""
    declared = manifest.get("files", {})
    manifest_path = directory / "s4_handoff_manifest.json"
    if manifest_path.exists():
        try:
            actual_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ApiError(409, "MANIFEST_MISMATCH", "冻结交接清单无法读取或已损坏") from exc
        if canonical_sha256(actual_manifest) != canonical_sha256(manifest):
            raise ApiError(409, "MANIFEST_MISMATCH", "交接清单与已发布冻结版本不一致")
    elif not allow_missing_manifest:
        raise ApiError(409, "MANIFEST_MISMATCH", "冻结交接清单缺失")
    if set(declared) != FILES - {"s4_handoff_manifest.json"}:
        raise ApiError(409, "MANIFEST_FILES_INVALID", "交接文件集合不完整")
    for name, metadata in declared.items():
        path = directory / name
        if Path(name).name != name or not path.is_file():
            raise ApiError(409, "EXPORT_INCOMPLETE", "导出文件不完整")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
            raise ApiError(409, "CHECKSUM_MISMATCH", "导出文件摘要不一致，禁止接收")
        if name.endswith(".jsonl") and len(data.splitlines()) != metadata["line_count"]:
            raise ApiError(409, "LINE_COUNT_MISMATCH", "导出行数不一致")
    full = [json.loads(row) for row in (directory / "units_for_s5.jsonl").read_text(encoding="utf-8").splitlines()]
    labeled = [json.loads(row) for row in (directory / "labeled.jsonl").read_text(encoding="utf-8").splitlines()]
    records = [json.loads(row) for row in (directory / "iaa_records.jsonl").read_text(encoding="utf-8").splitlines()]
    full_ids, labeled_ids, record_ids = ([row["unit_id"] for row in rows] for rows in (full, labeled, records))
    if len(full_ids) != len(set(full_ids)) or len(labeled_ids) != len(set(labeled_ids)) or set(labeled_ids) != set(record_ids) or len(labeled_ids) != len(record_ids) or not set(labeled_ids).issubset(full_ids):
        raise ApiError(409, "UNIT_SET_MISMATCH", "全量与抽检单元集合不一致")
    if len(full) != manifest["unit_count"] or len(labeled) != manifest["sample_count"]:
        raise ApiError(409, "COUNT_MISMATCH", "交接清单数量不一致")
    if canonical_sha256(sorted(full_ids)) != manifest["unit_ids_sha256"]:
        raise ApiError(409, "UNIT_SET_MISMATCH", "全量单元集合摘要不一致")


async def export_snapshot(db: AsyncSession, settings: Settings, imported: SourceImport) -> Handoff:
    """Publish only complete quality-approved batches; unsampled units remain present."""
    if imported.mode == "formal" and (not settings.external_alignment_confirmed or imported.blocked_reasons):
        raise ApiError(409, "EXTERNAL_CONTRACT_NOT_ALIGNED", "正式外部证据或接口尚未对齐，不能签发正式交接")
    batches = (await db.scalars(select(AnnotationBatch).where(AnnotationBatch.import_id == imported.id, AnnotationBatch.state != "SUPERSEDED").with_for_update())).all()
    datasets = {unit["dataset"] for unit in imported.payload["units"]}
    if {batch.dataset for batch in batches} != datasets or any(batch.state != "S4_READY" or batch.blocked_reasons for batch in batches):
        raise ApiError(409, "ALL_BATCHES_REQUIRED", "全部应完成数据集批次须通过质量门并完成内容定稿")
    units = copy.deepcopy(imported.payload["units"])
    by_id = {unit["unit_id"]: unit for unit in units}
    labeled: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    arbitration_log: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    snapshot_inputs: list[Any] = []
    for batch in batches:
        agreement = await db.scalar(select(Agreement).where(Agreement.batch_id == batch.id))
        if not agreement or agreement.result["verdict"] not in {"ACCEPT", "ARBITRATE"} or agreement.result["kappa"] is None:
            raise ApiError(409, "QUALITY_GATE_CLOSED", "有效原始质量结论缺失或拒绝")
        decisions = (await db.scalars(select(FinalDecision).where(FinalDecision.batch_id == batch.id))).all()
        decisions_by_id = {decision.unit_id: decision for decision in decisions}
        if set(decisions_by_id) != set(batch.selected_ids):
            raise ApiError(409, "FINAL_SCOPE_MISMATCH", "抽检最终内容不完整")
        arbiters = (await db.scalars(select(Arbitration).where(Arbitration.batch_id == batch.id))).all()
        arb_by_id = {item.unit_id: item for item in arbiters}
        if agreement.result["verdict"] == "ARBITRATE" and any(unit_id not in arb_by_id or not arb_by_id[unit_id].confirmed for unit_id in agreement.result.get("disagreement_unit_ids", [])):
            raise ApiError(409, "ARBITRATION_INCOMPLETE", "仲裁尚未闭环")
        assignments = (await db.scalars(select(Assignment).where(Assignment.batch_id == batch.id))).all()
        assignments_by_key = {(a.unit_id, a.seat): a for a in assignments}
        submissions = (await db.scalars(select(Submission).where(Submission.assignment_id.in_([a.id for a in assignments]), Submission.phase == "REVIEW"))).all()
        by_assignment = {item.assignment_id: item for item in submissions}
        for unit_id in batch.selected_ids:
            decision = decisions_by_id[unit_id]
            original_hash = canonical_sha256(by_id[unit_id])
            by_id[unit_id]["gold"] = decision.final_gold
            by_id[unit_id].setdefault("metadata", {})["s4_revision"] = {"source_content_sha256": original_hash, "decision_id": decision.id, "batch_id": batch.id, "round": batch.round}
            labeled.append({**by_id[unit_id], "annotation_batch_id": batch.id, "round": batch.round})
            a, b = assignments_by_key[(unit_id, "A")], assignments_by_key[(unit_id, "B")]
            if a.id not in by_assignment or b.id not in by_assignment:
                raise ApiError(409, "PAIR_INCOMPLETE", "原始配对记录缺失")
            records.append({"unit_id": unit_id, "annotator_a": batch.annotator_a, "annotator_b": batch.annotator_b,
                            "grades_a": by_assignment[a.id].payload, "grades_b": by_assignment[b.id].payload,
                            "κ": agreement.result["kappa"], "verdict": agreement.result["verdict"],
                            "agreement_id": agreement.id, "annotation_batch_id": batch.id, "round": batch.round,
                            "arbitrator": arb_by_id[unit_id].arbitrator_id if unit_id in arb_by_id else None,
                            "decided_at": decision.created_at.isoformat()})
        arbitration_log.extend({"unit_id": item.unit_id, "batch_id": batch.id, "arbitrator_id": item.arbitrator_id,
                                "reason": item.reason, "final_gold": item.final_gold, "confirmed": item.confirmed,
                                "confirmed_by": item.confirmed_by} for item in arbiters)
        gates.append({"batch_id": batch.id, "dataset": batch.dataset, "round": batch.round, **agreement.result, "sample_ledger": batch.sample_ledger})
        snapshot_inputs.append({"batch_id": batch.id, "agreement": agreement.input_hash,
                                "decisions": [{"id": item.id, "gold": item.final_gold} for item in decisions]})
    snapshot_hash = canonical_sha256({"import_hash": imported.content_hash, "scopes": snapshot_inputs})
    existing = await db.scalar(select(Handoff).where(Handoff.snapshot_hash == snapshot_hash))
    if existing:
        verify_snapshot(settings.data_dir / "exports" / existing.id, existing.manifest)
        return existing
    handoff = Handoff(id=str(uuid5(NAMESPACE_URL, "openkb-s4:" + snapshot_hash)), import_id=imported.id, mode=imported.mode, status="DEMO_READY" if imported.mode == "demo" else "S4_READY",
                      manifest={}, blocked_reasons=[], snapshot_hash=snapshot_hash)
    db.add(handoff)
    await db.flush()
    report = {"contract_version": "openkb.s4-s5.v1", "mode": imported.mode, "import_id": imported.id,
              "unit_count": len(units), "sample_count": len(labeled), "gates": gates,
              "source_hash": imported.content_hash, "external_status": "NOT_ALIGNED",
              "unsampled_status": "not_human_reviewed", "production_acceptance": False}
    contents = {"units_for_s5.jsonl": jsonl(units), "labeled.jsonl": jsonl(labeled),
                "iaa_records.jsonl": jsonl(records), "arbitration_log.jsonl": jsonl(arbitration_log), "s4_report.json": encoded(report)}
    manifest = {"contract_version": "openkb.s4-s5.v1", "handoff_id": handoff.id, "mode": imported.mode,
                "batch_id": imported.batch_id, "source_revision": imported.source_revision, "snapshot_hash": snapshot_hash,
                "unit_count": len(units), "sample_count": len(labeled), "unit_ids_sha256": canonical_sha256(sorted(by_id)),
                "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "line_count": len(data.splitlines()) if name.endswith(".jsonl") else 1}
                          for name, data in contents.items()}}
    export_root = settings.data_dir / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    temporary = export_root / (handoff.id + ".partial")
    target = export_root / handoff.id
    temporary.mkdir(exist_ok=True)
    for name, data in contents.items():
        with (temporary / name).open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    # Previous interrupted work may have left an old manifest at the staging path.
    staging_manifest = temporary / "s4_handoff_manifest.json"
    if staging_manifest.exists():
        staging_manifest.unlink()
    verify_snapshot(temporary, manifest, allow_missing_manifest=True)
    (temporary / "s4_handoff_manifest.json").write_bytes(encoded(manifest))
    if target.exists():
        previous_manifest = json.loads((target / "s4_handoff_manifest.json").read_text(encoding="utf-8"))
        verify_snapshot(target, previous_manifest)
        if canonical_sha256(previous_manifest) != canonical_sha256(manifest):
            raise ApiError(409, "EXPORT_PATH_CONFLICT", "已有导出与当前冻结版本不一致，需对账")
    else:
        temporary.rename(target)
    handoff.manifest = manifest
    return handoff
