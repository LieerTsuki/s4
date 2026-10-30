"""Worker reconciliation catches lost files and retains transaction orphans."""
import subprocess
import sys
from pathlib import Path

from openkb_s4.services.content_store import ContentStore


def test_periodic_file_check_reports_damaged_object_without_body(tmp_path: Path) -> None:
    from openkb_s4.services.reconcile_v13 import inspect_objects

    store = ContentStore(tmp_path)
    ref = store.put_json({"secret_material": "must never appear in finding"})
    assert inspect_objects(store, [ref])["valid"] is True
    (tmp_path / ref["object_key"]).unlink()
    result = inspect_objects(store, [ref])
    assert result["valid"] is False
    assert "must never" not in str(result)


def test_periodic_orphan_report_never_deletes_sealed_objects(tmp_path: Path) -> None:
    from openkb_s4.services.reconcile_v13 import inspect_objects

    store = ContentStore(tmp_path)
    ref = store.put_json({"orphan_after_rollback": True})
    report = inspect_objects(store, [])
    assert report["retained_unreferenced_objects"] == 1
    assert store.read_json(ref) == {"orphan_after_rollback": True}


def test_worker_can_import_reconciliation_without_importing_http_app() -> None:
    process = subprocess.run([sys.executable, "-c", "from openkb_s4.services import reconcile_v13; from openkb_s4.models import Base; assert 'v13_imports' in {t.name for t in Base.metadata.sorted_tables}"], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
