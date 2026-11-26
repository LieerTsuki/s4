"""Offline check of an S3 v2 submission against separately frozen evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, NoReturn

from pydantic import TypeAdapter, ValidationError

from .domain.contracts import canonical_sha256
from .domain.errors import DomainError
from .domain.v13 import Digest, Identifier, StrictModel, Unit, validate_envelope


class Candidate(StrictModel):
    unit: Unit
    unit_revision: Identifier
    seed_id: Identifier
    candidate_ref: str
    validation_round: Identifier


class Freeze(StrictModel):
    batch_id: Identifier
    source_revision: str
    origin_round: Identifier
    candidates: list[Candidate]


class Binding(StrictModel):
    batch_id: Identifier
    source_revision: str
    unit_id: Identifier
    unit_revision: Identifier
    content_sha256: Digest
    validation_id: Identifier
    status: Literal["PASS", "FAIL"]
    validation_round: Identifier


class Ledger(StrictModel):
    issuer_id: Identifier
    bindings: list[Binding]


class Replacement(StrictModel):
    from_binding: Binding
    to_binding: Binding
    seed_id: Identifier
    candidate_ref: str
    reason: str
    validation_round: Identifier


def reject(code: str) -> NoReturn:
    raise DomainError(code, "逐题绑定核对失败")


def index_records(records: list[Binding]) -> dict[str, Binding]:
    indexed: dict[str, Binding] = {}
    for record in records:
        if record.validation_id in indexed:
            reject("BINDING_VALIDATION_ID_DUPLICATE")
        indexed[record.validation_id] = record
    return indexed


def check_replacements(
    links: list[Replacement], records: dict[str, Binding], candidates: dict[str, Candidate], origin_round: str,
) -> set[str]:
    outgoing: dict[str, str] = {}
    destinations: set[str] = set()
    for link in links:
        source_id, target_id = link.from_binding.unit_id, link.to_binding.unit_id
        if source_id in outgoing or target_id in destinations:
            reject("BINDING_REPLACEMENT_DUPLICATE")
        outgoing[source_id] = target_id
        destinations.add(target_id)
    visited: set[str] = set()
    for first in outgoing:
        path: set[str] = set()
        current = first
        while current in outgoing and current not in visited:
            if current in path:
                reject("BINDING_REPLACEMENT_CYCLE")
            path.add(current)
            current = outgoing[current]
        visited.update(path)
    for link in links:
        source, target = link.from_binding, link.to_binding
        if records.get(source.unit_id) != source or records.get(target.unit_id) != target:
            reject("BINDING_LINK_MISMATCH")
        if (source.status != "FAIL" or target.status != "PASS" or source.validation_round != origin_round
                or target.validation_round == origin_round or link.validation_round != target.validation_round):
            reject("BINDING_REPLACEMENT_INVALID")
        if not (candidates[source.unit_id].seed_id == candidates[target.unit_id].seed_id == link.seed_id):
            reject("BINDING_REPLACEMENT_SEED")
        if not link.reason.strip() or link.candidate_ref != candidates[target.unit_id].candidate_ref:
            reject("BINDING_LINK_MISMATCH")
    return destinations


def check_submission(
    envelope: dict[str, Any], freeze: dict[str, Any], verification: dict[str, Any], history: dict[str, Any],
) -> dict[str, int]:
    normalized = validate_envelope(envelope)
    if normalized["mode"] != "formal":
        reject("BINDING_FORMAL_ENVELOPE_REQUIRED")
    report = normalized["s3_report"]
    try:
        frozen = Freeze.model_validate(freeze)
        ledger = Ledger.model_validate(verification)
        prior = Ledger.model_validate(history)
        links = TypeAdapter(list[Replacement]).validate_python(report["replacements"])
    except ValidationError as exc:
        raise DomainError("BINDING_EVIDENCE_INVALID", "逐题绑定台账字段或结构无效") from exc
    scope = (frozen.batch_id, frozen.source_revision)
    if scope != (normalized["batch_id"], normalized["source_revision"]) or ledger.issuer_id != prior.issuer_id:
        reject("BINDING_SOURCE_MISMATCH")

    candidates = {entry.unit.unit_id: entry for entry in frozen.candidates}
    if len(candidates) != len(frozen.candidates) or any(not row.candidate_ref.strip() for row in candidates.values()):
        reject("BINDING_CANDIDATE_SET_INVALID")
    # Same normalization as v2 intake, including recomputed context hashes and defaults.
    frozen_units = validate_envelope({
        "contract_version": normalized["contract_version"], "mode": "demo",
        "batch_id": frozen.batch_id, "source_revision": frozen.source_revision,
        "units": [entry.unit.model_dump() for entry in frozen.candidates],
    })["units"]
    hashes = {unit["unit_id"]: canonical_sha256(unit) for unit in frozen_units}
    previous_by_id = index_records(prior.bindings)
    records = {record.unit_id: record for record in index_records(ledger.bindings).values()}
    if len(records) != len(ledger.bindings) or records.keys() != candidates.keys():
        reject("BINDING_CANDIDATE_SET_MISMATCH")
    projected = {record["unit_id"]: record for record in report["unit_results"]}
    if projected.keys() != records.keys():
        reject("BINDING_PROJECTION_MISMATCH")
    for unit_id, record in records.items():
        candidate = candidates[unit_id]
        if (record.batch_id, record.source_revision) != scope:
            reject("BINDING_SOURCE_MISMATCH")
        if record.unit_revision != candidate.unit_revision or record.validation_round != candidate.validation_round:
            reject("BINDING_REVISION_MISMATCH")
        if record.content_sha256 != hashes[unit_id]:
            reject("BINDING_DIGEST_MISMATCH")
        previous = previous_by_id.get(record.validation_id)
        if previous is not None and previous != record:
            reject("BINDING_VALIDATION_ID_CONFLICT")
        if projected[unit_id] != record.model_dump(include={"unit_id", "status", "content_sha256", "validation_id"}):
            reject("BINDING_PROJECTION_MISMATCH")

    origin = {key: record.status for key, record in records.items() if record.validation_round == frozen.origin_round}
    failed = {key for key, status in origin.items() if status == "FAIL"}
    original_passed = set(origin) - failed
    if (report["checked"], report["passed"], report["failed"], set(report["failed_ids"])) != (
        len(origin), len(original_passed), len(failed), failed,
    ):
        reject("BINDING_ORIGINAL_COUNTS_MISMATCH")
    replacement_passed = check_replacements(links, records, candidates, frozen.origin_round)
    all_passed = {key for key, record in records.items() if record.status == "PASS"}
    submitted = {unit["unit_id"]: canonical_sha256(unit) for unit in normalized["units"]}
    if set(submitted) != all_passed or all_passed != original_passed | replacement_passed:
        reject("BINDING_FINAL_SET_MISMATCH")
    if any(hashes[unit_id] != digest for unit_id, digest in submitted.items()):
        reject("BINDING_FINAL_UNIT_MISMATCH")
    return {"checked": len(origin), "passed": len(original_passed), "failed": len(failed),
            "final_units": len(submitted), "replacement_links": len(links)}


def read_input(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                reject("BINDING_DUPLICATE_JSON_KEY")
            value[key] = item
        return value

    def reject_constant(_: str) -> NoReturn:
        reject("BINDING_NONFINITE_JSON_NUMBER")

    raw = path.read_bytes()
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        reject("BINDING_INPUT_FILE_DIGEST_MISMATCH")
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_keys, parse_constant=reject_constant)
    if not isinstance(value, dict):
        reject("BINDING_EVIDENCE_INVALID")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("envelope", "candidates", "verification", "history"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--candidates-sha256", required=True)
    parser.add_argument("--verification-sha256", required=True)
    parser.add_argument("--history-sha256", required=True)
    args = parser.parse_args()
    try:
        result = check_submission(
            read_input(args.envelope), read_input(args.candidates, args.candidates_sha256),
            read_input(args.verification, args.verification_sha256), read_input(args.history, args.history_sha256),
        )
    except DomainError as exc:
        print(json.dumps({"status": "REJECTED", "error_code": exc.code}))
        return 1
    except (OSError, ValueError):
        print(json.dumps({"status": "REJECTED", "error_code": "BINDING_INPUT_UNREADABLE"}))
        return 1
    print(json.dumps({"status": "BINDING_CHECK_PASSED", **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
