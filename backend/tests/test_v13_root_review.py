"""Independent integrity review regressions; no live or test database is touched."""
from pathlib import Path
from typing import Any

import pytest

from openkb_s4.services.content_inventory import database_references, verify_controlled_graph
from openkb_s4.services.content_store import ContentStore


def test_duplicate_object_key_cannot_hide_a_conflicting_reference(tmp_path: Path) -> None:
    store = ContentStore(tmp_path)
    valid = store.put_json({"sealed": "actual bytes"})
    invalid = {**valid, "sha256": "0" * 64}
    # The valid item is visited first by the stack; the invalid ref must still
    # be validated rather than skipped just because its object key was seen.
    with pytest.raises(ValueError):
        verify_controlled_graph(store, [invalid, valid])


class MalformedReferenceConnection:
    async def fetch(self, sql: str) -> list[dict[str, Any]]:
        if "information_schema.columns" in sql:
            return [{"table_name": "v13_units", "column_name": "source_ref"}]
        return [{"value": {"sha256": "a" * 64}}]


class UploadAuditConnection:
    def __init__(self, reference: dict[str, Any]) -> None:
        self.reference = reference

    async def fetch(self, sql: str) -> list[dict[str, Any]]:
        if "information_schema.columns" in sql:
            return []
        if "audit_events" in sql:
            return [{"details": {"raw_file_ref": self.reference, "raw_file_sha256": "b" * 64}}]
        return []


@pytest.mark.asyncio
async def test_database_nonnull_reference_shape_is_never_silently_ignored() -> None:
    with pytest.raises(ValueError):
        await database_references(MalformedReferenceConnection())


@pytest.mark.asyncio
async def test_uploaded_original_archive_audit_is_part_of_backup_reference_roots() -> None:
    reference = {"object_key": "objects/aa/" + "a" * 64 + ".json", "sha256": "a" * 64}
    assert await database_references(UploadAuditConnection(reference)) == [reference]


@pytest.mark.asyncio
async def test_malformed_uploaded_original_audit_is_not_silently_ignored() -> None:
    with pytest.raises(ValueError):
        await database_references(UploadAuditConnection({"sha256": "a" * 64}))


def test_export_returned_readiness_is_not_an_accepted_report_alias(tmp_path: Path) -> None:
    from openkb_s4.services.handoffs_v13 import publish_package

    units = [{"unit_id": "u", "content_revision": "rev"}]
    records = [{"unit_id": "u", "content_revision": "rev", "verdict": "VERIFIED", "annotator": "primary"}]
    iaa = [{"unit_id": "u", "content_revision": "rev", "annotator_a": "A", "annotator_b": "B", "grades_a": [], "grades_b": []}]
    with pytest.raises(ValueError):
        publish_package(tmp_path, "returned", units, records, units, iaa,
                        {"mode": "demo", "readiness": "RETURNED_TO_S2"}, [])


def test_handoff_manifest_graph_reaches_its_raw_evidence_archive(tmp_path: Path) -> None:
    from openkb_s4.services.handoffs_v13 import publish_package

    store = ContentStore(tmp_path / "controlled")
    raw = store.put_json({"sealed_original_submissions": ["original"]})
    units = [{"unit_id": "u", "content_revision": "rev"}]
    records = [{"unit_id": "u", "content_revision": "rev", "verdict": "VERIFIED", "annotator": "primary"}]
    iaa = [{"unit_id": "u", "content_revision": "rev", "annotator_a": "A", "annotator_b": "B", "grades_a": [], "grades_b": []}]
    manifest = publish_package(tmp_path / "exports", "demo", units, records, units, iaa,
                               {"mode": "demo", "raw_evidence_ref": raw}, [])
    manifest_ref = store.put_json(manifest)
    (store.root / raw["object_key"]).unlink()
    with pytest.raises(ValueError):
        verify_controlled_graph(store, [manifest_ref])
