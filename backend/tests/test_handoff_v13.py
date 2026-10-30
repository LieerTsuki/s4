"""v2 handoff keeps N human verifications separate from n IAA units."""
import json
from pathlib import Path
from typing import Any

import pytest


def _rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    units = [{"unit_id": f"U-{i}", "content_revision": f"r-{i}"} for i in range(12)]
    verified = [{"unit_id": f"U-{i}", "content_revision": f"r-{i}", "verdict": "VERIFIED", "annotator": "human-main"} for i in range(12)]
    iaa = [{"unit_id": f"U-{i}", "content_revision": f"r-{i}", "annotator_a": "human-a", "annotator_b": "human-b", "grades_a": ["correct", "wrong"], "grades_b": ["correct", "wrong"]} for i in range(8)]
    return units, verified, iaa


def test_new_package_counts_and_revision_sets_are_independent(tmp_path: Path) -> None:
    from openkb_s4.services.handoffs_v13 import publish_package, verify_package

    units, verified, iaa = _rows()
    result = publish_package(tmp_path, "snapshot-1", units, verified, units[:8], iaa, {"mode": "demo", "blockers": ["J1_C1_POLICY_UNCONFIRMED"]}, [])
    assert result["contract_version"] == "openkb.s4-s5.v2"
    assert result["unit_count"] == 12 and result["sample_count"] == 8
    assert result["formal_credential"] is False
    assert "labeled.jsonl" not in result["files"]
    assert result["files"]["verified_annotations.jsonl"]["line_count"] == 12
    assert result["files"]["iaa_records.jsonl"]["line_count"] == 8
    assert "s4_handoff_manifest.json" not in result["files"]
    verify_package(tmp_path / "snapshot-1", result)
    assert publish_package(tmp_path, "snapshot-1", units, verified, units[:8], iaa, {"mode": "demo", "blockers": ["J1_C1_POLICY_UNCONFIRMED"]}, []) == result


@pytest.mark.parametrize("defect", ["missing_verification", "duplicate_verification", "wrong_revision", "same_observer", "missing_pair", "out_of_scope", "not_verified"])
def test_package_never_uses_observation_to_fill_verification_gaps(tmp_path: Path, defect: str) -> None:
    from openkb_s4.services.handoffs_v13 import publish_package

    units, verified, iaa = _rows()
    if defect == "missing_verification":
        verified.pop()
    elif defect == "duplicate_verification":
        verified[-1] = verified[0]
    elif defect == "wrong_revision":
        verified[0]["content_revision"] = "old"
    elif defect == "same_observer":
        iaa[0]["annotator_b"] = iaa[0]["annotator_a"]
    elif defect == "missing_pair":
        iaa.pop()
    elif defect == "out_of_scope":
        iaa[0]["unit_id"] = "outside"
    else:
        verified[0]["verdict"] = "NEEDS_REVISION"
    with pytest.raises(ValueError):
        publish_package(tmp_path, "invalid", units, verified, units[:8], iaa, {"mode": "demo"}, [])
    assert not (tmp_path / "invalid" / "s4_handoff_manifest.json").exists()


def test_receiver_detects_content_or_manifest_tamper(tmp_path: Path) -> None:
    from openkb_s4.services.handoffs_v13 import publish_package, verify_package

    units, verified, iaa = _rows()
    manifest = publish_package(tmp_path, "sealed", units, verified, units[:8], iaa, {"mode": "demo"}, [])
    path = tmp_path / "sealed" / "verified_annotations.jsonl"
    path.write_text(json.dumps(verified[0]), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_package(tmp_path / "sealed", manifest)


def test_returned_scope_cannot_be_relabelled_ready(tmp_path: Path) -> None:
    from openkb_s4.services.handoffs_v13 import publish_package

    units, verified, iaa = _rows()
    with pytest.raises(ValueError):
        publish_package(tmp_path, "returned", units, verified, units[:8], iaa, {"mode": "demo", "state": "RETURNED_TO_S2"}, [])


def test_receiver_recomputes_declared_unit_set_digest(tmp_path: Path) -> None:
    from openkb_s4.services.handoffs_v13 import publish_package, verify_package

    units, verified, iaa = _rows()
    manifest = publish_package(tmp_path, "set-digest", units, verified, units[:8], iaa, {"mode": "demo"}, [])
    manifest["unit_ids_sha256"] = "f" * 64
    (tmp_path / "set-digest" / "s4_handoff_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_package(tmp_path / "set-digest", manifest)
