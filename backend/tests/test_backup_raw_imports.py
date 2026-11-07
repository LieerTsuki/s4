"""Raw upload archives are restored by controlled audit identity, never host paths."""
import hashlib
import json
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

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


@pytest.mark.parametrize("audit_fails", [True, False])
@pytest.mark.asyncio
async def test_restore_proof_is_published_only_after_completion_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, audit_fails: bool,
) -> None:
    module = backup_module()
    scope = module["run"].__globals__
    archive = tmp_path / "backup"
    (archive / "artifacts").mkdir(parents=True)
    dump = b"synthetic restore fixture; external processes are isolated"
    (archive / "database.dump").write_bytes(dump)
    (archive / "backup-manifest.json").write_text(json.dumps({
        "files": {"database.dump": hashlib.sha256(dump).hexdigest()}, "row_counts": {},
    }), encoding="utf-8")
    connection = SimpleNamespace(execute=AsyncMock(), fetch=AsyncMock(return_value=[]),
                                 fetchval=AsyncMock(return_value=None), close=AsyncMock())
    event = AsyncMock(side_effect=RuntimeError("audit unavailable") if audit_fails else None)
    monkeypatch.setitem(scope, "ROOT", tmp_path)
    monkeypatch.setitem(scope, "dotenv_values", lambda _: {
        "S4_MIGRATION_DATABASE_URL": "postgresql+asyncpg://owner@127.0.0.1/s4_test",
    })
    monkeypatch.setattr(scope["asyncpg"], "connect", AsyncMock(return_value=connection))
    monkeypatch.setitem(scope, "docker", lambda *_: None)
    monkeypatch.setitem(scope, "counts", AsyncMock(return_value={}))
    monkeypatch.setitem(scope, "operation_event", event)
    args = SimpleNamespace(action="restore", env_file=tmp_path / "config", database="s4_test",
                           container="isolated-test-db", backup=archive)
    if audit_fails:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await module["run"](args)
    else:
        await module["run"](args)
    restored = list((tmp_path / "var").glob("s4_restore_*"))
    assert len(restored) == 1  # Retain restored artifacts even when the audit fails.
    proof = restored[0] / "restore-verification.json"
    assert proof.exists() is not audit_fails
    if not audit_fails:
        assert json.loads(proof.read_text(encoding="utf-8"))["operations_audit_recorded"] is True
    event.assert_awaited_once()
