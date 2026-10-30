"""Controlled immutable objects cannot escape their root or hide damaged content."""
import hashlib
import json
from pathlib import Path

import pytest


def test_json_roundtrip_is_canonical_and_deduplicated(tmp_path: Path) -> None:
    from openkb_s4.services.content_store import ContentStore

    store = ContentStore(tmp_path)
    value = {"text": "核实😀", "nested": {"gold": [3, 2]}}
    reference = store.put_json(value)
    assert store.read_json(reference) == value
    assert reference == store.put_json({"nested": {"gold": [3, 2]}, "text": "核实😀"})
    assert set(reference) == {"object_key", "sha256"}
    assert hashlib.sha256((tmp_path / reference["object_key"]).read_bytes()).hexdigest() == reference["sha256"]
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_tampering_and_existing_corruption_cannot_be_published(tmp_path: Path) -> None:
    from openkb_s4.services.content_store import ContentStore, ContentStoreError

    store = ContentStore(tmp_path)
    ref = store.put_json({"answer": "original"})
    path = tmp_path / ref["object_key"]
    path.write_text(json.dumps({"answer": "changed"}), encoding="utf-8")
    with pytest.raises(ContentStoreError, match="digest"):
        store.read_json(ref)
    with pytest.raises(ContentStoreError, match="digest"):
        store.put_json({"answer": "original"})


@pytest.mark.parametrize("key", ["../outside.json", "/etc/passwd", "C:/outside.json", "objects/../../outside", "https://example.org/file", "objects/xx/" + "a" * 64 + ".json"])
def test_untrusted_references_cannot_read_arbitrary_paths(tmp_path: Path, key: str) -> None:
    from openkb_s4.services.content_store import ContentStore, ContentStoreError

    with pytest.raises(ContentStoreError):
        ContentStore(tmp_path).read_json({"object_key": key, "sha256": "a" * 64})


def test_objects_are_not_implicitly_garbage_collected(tmp_path: Path) -> None:
    from openkb_s4.services.content_store import ContentStore

    store = ContentStore(tmp_path)
    ref = store.put_json({"sealed": "retained even if DB transaction rolls back"})
    assert store.inventory() == [ref]
    assert store.verify_references([ref]) == 1


def test_missing_or_invalid_reference_is_explicit(tmp_path: Path) -> None:
    from openkb_s4.services.content_store import ContentStore, ContentStoreError

    with pytest.raises(ContentStoreError):
        ContentStore(tmp_path).read_json({"object_key": "objects/aa/" + "a" * 64 + ".json", "sha256": "a" * 64})
    with pytest.raises(ContentStoreError):
        ContentStore(tmp_path).read_json({"object_key": "", "sha256": "wrong"})
