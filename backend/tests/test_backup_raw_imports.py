"""Raw upload archives are restored by controlled audit identity, never host paths."""
import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

import pytest


def backup_module() -> dict[str, Any]:
    return runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "backup_restore.py"), run_name="raw_backup_test")


def test_raw_import_inventory_deduplicates_identical_upload_audits() -> None:
    module = backup_module()
    digest = "a" * 64
    details = {"file_ref": digest + ".jsonl", "raw_file_sha256": digest}
    assert module["raw_import_manifest"]([{"details": details}, {"details": details}]) == {digest + ".jsonl": digest}
    assert module["raw_import_manifest"]([{"details": json.dumps(details)}]) == {digest + ".jsonl": digest}
    assert module["raw_import_manifest"]([]) == {}


@pytest.mark.parametrize("reference", ["../secret.jsonl", "C:/secret.jsonl", "/etc/passwd", "imports/" + "a" * 64 + ".jsonl", "b" * 64 + ".jsonl"])
def test_raw_import_inventory_rejects_paths_and_hash_identity_conflicts(reference: str) -> None:
    module = backup_module()
    with pytest.raises(ValueError, match="controlled"):
        module["raw_import_manifest"]([{"details": {"file_ref": reference, "raw_file_sha256": "a" * 64}}])


def test_raw_import_archives_require_original_bytes_and_exact_inventory(tmp_path: Path) -> None:
    module = backup_module()
    content = b'{"synthetic":"uploaded JSONL bytes"}\n'
    digest = hashlib.sha256(content).hexdigest()
    expected = {digest + ".jsonl": digest}
    with pytest.raises(ValueError, match="missing"):
        module["verify_raw_import_files"](tmp_path, expected)
    archive = tmp_path / "imports"
    archive.mkdir()
    target = archive / (digest + ".jsonl")
    target.write_bytes(content)
    module["verify_raw_import_files"](tmp_path, expected)
    target.write_bytes(content + b"tamper")
    with pytest.raises(ValueError, match="digest"):
        module["verify_raw_import_files"](tmp_path, expected)
    target.write_bytes(content)
    (archive / ("b" * 64 + ".jsonl")).write_bytes(b"unreferenced")
    with pytest.raises(ValueError, match="inventory"):
        module["verify_raw_import_files"](tmp_path, expected)


def test_legacy_backup_without_uploads_needs_no_import_directory(tmp_path: Path) -> None:
    module = backup_module()
    module["verify_raw_import_files"](tmp_path, {})


def test_raw_import_source_can_hold_extra_unreferenced_files_but_archives_cannot(tmp_path: Path) -> None:
    module = backup_module()
    archive = tmp_path / "imports"
    archive.mkdir()
    (archive / ("b" * 64 + ".jsonl")).write_bytes(b"not bound to the snapshot")
    module["verify_raw_import_files"](tmp_path, {}, strict_inventory=False)
    with pytest.raises(ValueError, match="inventory"):
        module["verify_raw_import_files"](tmp_path, {})


def test_malformed_raw_import_audit_cannot_be_silently_skipped(tmp_path: Path) -> None:
    module = backup_module()
    with pytest.raises(TypeError, match="controlled"):
        module["raw_import_manifest"]([{"details": []}])
    with pytest.raises(TypeError, match="controlled"):
        module["verify_raw_import_files"](tmp_path, [])
