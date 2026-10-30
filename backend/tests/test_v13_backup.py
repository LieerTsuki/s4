"""Restore must include recursively referenced private content, not only SQL indexes."""
from pathlib import Path

import pytest

from openkb_s4.services.content_store import ContentStore


def test_backup_inventory_follows_nested_sealed_references(tmp_path: Path) -> None:
    from openkb_s4.services.content_inventory import verify_controlled_graph

    store = ContentStore(tmp_path)
    review = store.put_json({"reason": "independent finding"})
    record = store.put_json({"review_ref": review})
    assert verify_controlled_graph(store, [record]) == 2
    (tmp_path / review["object_key"]).unlink()
    with pytest.raises(ValueError):
        verify_controlled_graph(store, [record])


def test_database_reference_without_corresponding_file_is_not_recoverable(tmp_path: Path) -> None:
    from openkb_s4.services.content_inventory import verify_controlled_graph

    with pytest.raises(ValueError):
        verify_controlled_graph(ContentStore(tmp_path), [{"object_key": "objects/aa/" + "a" * 64 + ".json", "sha256": "a" * 64}])
