"""Versioned S4 process packages; S5 owns the final dataset six-file output."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

FILES_V2 = frozenset({"units_for_s5.jsonl", "verified_annotations.jsonl",
                      "observation_units.jsonl", "iaa_records.jsonl", "s4_report.json",
                      "quality_actions.jsonl"})


def _encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {row["unit_id"]: row for row in rows}
    if len(rows) != len(result):
        raise ValueError("Duplicate unit identity")
    return result


def _validate_sets(units: list[dict[str, Any]], verified: list[dict[str, Any]],
                   observed: list[dict[str, Any]], iaa: list[dict[str, Any]]) -> None:
    full, records, sample, pairs = map(_index, (units, verified, observed, iaa))
    if not full or set(full) != set(records):
        raise ValueError("Every final unit requires one human verification")
    if not sample or set(sample) != set(pairs) or not set(sample).issubset(full):
        raise ValueError("Observation scope and IAA pairs differ")
    for identity, unit in full.items():
        record = records[identity]
        if not unit.get("content_revision") or record.get("content_revision") != unit.get("content_revision"):
            raise ValueError("Verification revision differs from final unit")
        if record.get("verdict") != "VERIFIED" or not record.get("annotator"):
            raise ValueError("Human verification is not complete")
    for identity, pair in pairs.items():
        # Observation is bound to its frozen source revision. A later verified
        # final revision must not overwrite the original observation labels.
        if pair.get("content_revision") != sample[identity].get("content_revision"):
            raise ValueError("Observation frozen revisions differ")
        a, b = pair.get("annotator_a"), pair.get("annotator_b")
        if not a or not b or a == b or "grades_a" not in pair or "grades_b" not in pair:
            raise ValueError("Two distinct original observers are required")


def verify_package(directory: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("contract_version") != "openkb.s4-s5.v2":
        raise ValueError("Wrong handoff protocol")
    declared = manifest.get("files", {})
    if set(declared) != FILES_V2:
        raise ValueError("Handoff file inventory differs")
    manifest_file = directory / "s4_handoff_manifest.json"
    if not manifest_file.is_file() or manifest_file.is_symlink():
        raise ValueError("Published manifest missing")
    if json.loads(manifest_file.read_bytes()) != manifest:
        raise ValueError("Published manifest differs")
    rows: dict[str, list[dict[str, Any]]] = {}
    for name, expected in declared.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Published controlled file missing")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError("Handoff digest mismatch")
        if name.endswith(".jsonl"):
            values = [json.loads(line) for line in data.splitlines()]
            if len(values) != expected["line_count"]:
                raise ValueError("Handoff line count mismatch")
            rows[name] = values
    _validate_sets(rows["units_for_s5.jsonl"], rows["verified_annotations.jsonl"],
                   rows["observation_units.jsonl"], rows["iaa_records.jsonl"])
    if len(rows["units_for_s5.jsonl"]) != manifest["unit_count"] or len(rows["observation_units.jsonl"]) != manifest["sample_count"]:
        raise ValueError("Manifest N/n counts differ")
    actual_ids = sorted(row["unit_id"] for row in rows["units_for_s5.jsonl"])
    if hashlib.sha256(_encode(actual_ids)).hexdigest() != manifest["unit_ids_sha256"]:
        raise ValueError("Manifest unit set digest differs")
    if manifest.get("formal_credential") is not False or manifest.get("mode") != "demo":
        raise ValueError("Unaligned package cannot carry formal credentials")


def publish_package(root: Path, identity: str, units: list[dict[str, Any]],
                    verified: list[dict[str, Any]], observed: list[dict[str, Any]],
                    iaa: list[dict[str, Any]], report: dict[str, Any],
                    actions: list[dict[str, Any]]) -> dict[str, Any]:
    _validate_sets(units, verified, observed, iaa)
    if report.get("mode") != "demo":
        raise ValueError("Formal external protocol and policy are not aligned")
    if report.get("state") == "RETURNED_TO_S2" or report.get("readiness") == "RETURNED_TO_S2":
        raise ValueError("Returned scope cannot be handed off")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identity):
        raise ValueError("Invalid opaque snapshot identity")
    contents = {"units_for_s5.jsonl": units, "verified_annotations.jsonl": verified,
                "observation_units.jsonl": observed, "iaa_records.jsonl": iaa,
                "quality_actions.jsonl": actions}
    data = {name: b"".join(_encode(row) + b"\n" for row in values) for name, values in contents.items()}
    data["s4_report.json"] = _encode(report)
    manifest = {"contract_version": "openkb.s4-s5.v2", "handoff_id": identity,
                "mode": "demo", "formal_credential": False,
                "external_alignment": "NOT_ALIGNED", "unit_count": len(units),
                "sample_count": len(observed),
                **({"raw_evidence_ref": report["raw_evidence_ref"]} if "raw_evidence_ref" in report else {}),
                "unit_ids_sha256": hashlib.sha256(_encode(sorted(row["unit_id"] for row in units))).hexdigest(),
                "files": {name: {"sha256": hashlib.sha256(value).hexdigest(),
                                  **({"line_count": len(contents[name])} if name in contents else {})}
                          for name, value in data.items()}}
    root.mkdir(parents=True, exist_ok=True)
    destination = root / identity
    if destination.exists():
        verify_package(destination, manifest)
        return manifest
    temporary = root / f".{identity}.{uuid4().hex}.partial"
    temporary.mkdir()
    # A partial directory is retained if IO fails, but is never published.
    for name, value in {**data, "s4_handoff_manifest.json": _encode(manifest)}.items():
        with (temporary / name).open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    verify_package(temporary, manifest)
    try:
        temporary.rename(destination)
    except FileExistsError:
        verify_package(destination, manifest)
    verify_package(destination, manifest)
    return manifest


async def export_snapshot_v13(db: Any, settings: Any, import_id: str, actor_id: str) -> Any:
    """Read frozen source/verification/observation objects and publish via worker."""
    from uuid import NAMESPACE_URL, uuid5

    from sqlalchemy import select

    from ..db import lock_scope
    from ..domain.contracts import canonical_sha256
    from ..models_handoff_v13 import V13Handoff
    from ..models_v13 import (
        V13Assignment,
        V13Batch,
        V13Import,
        V13QualityAction,
        V13Submission,
        V13Unit,
    )
    from ..security import ApiError
    from .content_store import ContentStore
    from .workflow_v13 import current_verification_records, import_report

    await lock_scope(db, "v13-handoff:" + import_id)
    imported = await db.scalar(select(V13Import).where(V13Import.id == import_id).with_for_update())
    if not imported:
        raise ApiError(404, "NOT_FOUND", "来源不存在")
    store = ContentStore(settings.data_dir / "controlled")
    report = await import_report(db, store, imported)
    if imported.mode != "demo":
        raise ApiError(409, "EXTERNAL_CONTRACT_NOT_ALIGNED", "正式交接协议与适用规则待协作方确认")
    if not report["demo_ready"]:
        raise ApiError(409, "VERIFICATION_EVIDENCE_INCOMPLETE", "全量核实、观测或材料闭环尚未完成")
    units = (await db.scalars(select(V13Unit).where(V13Unit.import_id == import_id).order_by(V13Unit.unit_id))).all()
    records = await current_verification_records(db, store, units)
    final_units, verified = [], []
    for unit in units:
        revision = unit.final_revision or unit.content_revision
        candidate = dict(store.read_json(unit.final_ref or unit.source_ref))
        candidate["content_revision"] = revision
        candidate["source_content_revision"] = unit.content_revision
        final_units.append(candidate)
        verified.append(store.read_json(records[unit.id].record_ref))
    batches = (await db.scalars(select(V13Batch).where(V13Batch.import_id == import_id).order_by(V13Batch.dataset, V13Batch.workflow_kind, V13Batch.round, V13Batch.id))).all()
    observed: list[dict[str, Any]] = []
    iaa: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    by_id = {unit.unit_id: unit for unit in units}
    for batch in batches:
        batch_actions = (await db.scalars(select(V13QualityAction).where(V13QualityAction.batch_id == batch.id).order_by(V13QualityAction.created_at, V13QualityAction.id))).all()
        actions.extend(store.read_json(action.record_ref) for action in batch_actions)
        assignments = (await db.scalars(select(V13Assignment).where(V13Assignment.batch_id == batch.id).order_by(V13Assignment.id))).all()
        submissions = (await db.scalars(select(V13Submission).where(V13Submission.assignment_id.in_([row.id for row in assignments])).order_by(V13Submission.assignment_id, V13Submission.phase, V13Submission.id))).all()
        raw.extend({"assignment_id": row.assignment_id, "phase": row.phase, "payload_hash": row.payload_hash,
                    "payload": store.read_json(row.payload_ref)} for row in submissions)
        if (batch.workflow_kind != "OBSERVATION" or batch.state == "SUPERSEDED"
                or (batch.parent_id and batch.sample_ledger.get("purpose") != "REPLACEMENT")):
            continue
        quality = store.read_json(batch.quality_ref)
        mapping = {(row.unit_index_id, row.seat): row for row in assignments if row.active}
        reviews = {row.assignment_id: row for row in submissions if row.phase == "REVIEW"}
        for unit_id in batch.selected_ids:
            unit = by_id[unit_id]
            a, b = mapping[(unit.id, "A")], mapping[(unit.id, "B")]
            original = dict(store.read_json(unit.source_ref))
            original["content_revision"] = a.content_revision
            observed.append(original)
            iaa.append({"unit_id": unit_id, "content_revision": a.content_revision,
                        "observation_batch_id": batch.id, "round": batch.round,
                        "annotator_a": a.user_id, "annotator_b": b.user_id,
                        "grades_a": store.read_json(reviews[a.id].payload_ref),
                        "grades_b": store.read_json(reviews[b.id].payload_ref),
                        "kappa": quality.get("kappa"), "sampled_at": batch.created_at.isoformat(),
                        "profile_version": batch.profile_version, "manual_version": batch.manual_version,
                        "quality_ref": batch.quality_ref})
    raw.sort(key=lambda row: (row["assignment_id"], row["phase"]))
    actions.sort(key=canonical_sha256)
    iaa.sort(key=lambda row: row["unit_id"])
    observed.sort(key=lambda row: row["unit_id"])
    for key in ("quality", "expansions"):
        if isinstance(report.get(key), list):
            report[key] = sorted(report[key], key=canonical_sha256)
    report["raw_evidence_ref"] = store.put_json({"contract_version": "openkb.s4-evidence.v3", "submissions": raw,
                                                 "source_ref": imported.source_ref})
    report["source_sha256"] = imported.content_hash
    snapshot_hash = canonical_sha256({"units": final_units, "verified": verified, "observed": observed,
                                      "iaa": iaa, "actions": actions, "report": report})
    existing = await db.scalar(select(V13Handoff).where(V13Handoff.snapshot_hash == snapshot_hash))
    if existing:
        manifest = store.read_json(existing.manifest_ref)
        verify_package(settings.data_dir / "exports-v13" / existing.id, manifest)
        return existing
    identity = str(uuid5(NAMESPACE_URL, "openkb.s4-s5.v2:" + snapshot_hash))
    import asyncio
    manifest = await asyncio.to_thread(publish_package, settings.data_dir / "exports-v13", identity,
                                       final_units, verified, observed, iaa, report, actions)
    row = V13Handoff(id=identity, import_id=import_id, creator_id=actor_id,
                     snapshot_hash=snapshot_hash, manifest_ref=store.put_json(manifest), status="EXPORTED_DEMO")
    db.add(row)
    await db.flush()
    return row
