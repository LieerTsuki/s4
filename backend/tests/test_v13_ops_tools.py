"""Management tools must fail closed and never garbage-collect sealed content."""
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from openkb_s4.services.content_store import ContentStore

ROOT = Path(__file__).resolve().parents[2]


def script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["s4_dev", "s4_test", "postgres", "s4_restore_../../prod", "s4_restore_foo;drop"])
def test_migration_rehearsal_never_targets_live_or_test_databases(name: str) -> None:
    with pytest.raises(ValueError):
        script("v13_migration_rehearsal").require_isolated_restore(name)


def test_rehearsal_requires_specific_restore_identity() -> None:
    name = "s4_restore_20261030_142253_251ccf"
    assert script("v13_migration_rehearsal").require_isolated_restore(name) == name


def test_reconcile_reports_orphans_without_deleting(tmp_path: Path) -> None:
    store = ContentStore(tmp_path)
    used = store.put_json({"answer": "sealed"})
    orphan = store.put_json({"answer": "transaction interrupted"})
    report = script("v13_reconcile").inspect_store(store, [used])
    assert report == {"referenced_objects": 1, "retained_objects": 2, "retained_unreferenced_objects": 1, "automatic_deletion": False}
    assert store.read_json(orphan)["answer"] == "transaction interrupted"


def test_reconcile_rejects_missing_referenced_object(tmp_path: Path) -> None:
    store = ContentStore(tmp_path)
    ref = store.put_json({"answer": "sealed"})
    (tmp_path / ref["object_key"]).unlink()
    with pytest.raises(ValueError):
        script("v13_reconcile").inspect_store(store, [ref])
