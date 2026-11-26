from copy import deepcopy
from typing import Any

import pytest

from openkb_s4.domain.contracts import canonical_sha256
from openkb_s4.domain.errors import DomainError
from openkb_s4.domain.v13 import validate_envelope
from openkb_s4.s3_binding_check import check_submission


def submission() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    keys = {"batch_id": "B-SYNTHETIC", "source_revision": "snapshot-1"}
    unit = {"unit_id": "D1-use-01", "dataset": "QA-D1", "difficulty": "easy", "question": "几天办理？",
            "contexts": [{"doc_id": "doc", "text": "五天办理。"}], "gold": {"answer_points": ["五天"],
                "gold_doc_ids": ["doc"], "relevance_grades": {"doc": 3}, "expected_refusal": False}}
    converted = [{**unit, "unit_id": f"D1-synthetic-{i}"} for i in range(11)]
    body = {**keys, "mode": "demo", "contract_version": "openkb.s3-s4.v2", "units": converted}
    normalized = validate_envelope(body)["units"]
    candidates = [{"unit": item, "unit_revision": "r1", "seed_id": f"s{min(i, 9)}",
                   "candidate_ref": f"units.json#{item['unit_id']}",
                   "validation_round": "origin" if i < 10 else "replacement"} for i, item in enumerate(converted)]
    records = [{**keys, "unit_id": item["unit_id"], "unit_revision": "r1", "content_sha256": canonical_sha256(item),
                "validation_id": f"validator-{i}", "status": "FAIL" if i == 9 else "PASS",
                "validation_round": candidates[i]["validation_round"]} for i, item in enumerate(normalized)]
    link = {"from_binding": records[9], "to_binding": records[10], "seed_id": "s9",
            "candidate_ref": candidates[10]["candidate_ref"], "reason": "合成递补", "validation_round": "replacement"}
    envelope = {**body, "mode": "formal", "units": converted[:9] + converted[10:],
                "s3_report": {"checked": 10, "passed": 9, "failed": 1, "pass_rate": .9,
                              "unit_results": [{k: row[k] for k in ("unit_id", "status", "content_sha256", "validation_id")} for row in records],
                              "failed_ids": [records[9]["unit_id"]], "replacements": [link],
                              "model_versions": {"fixture": "synthetic"}, "threshold_version": "fixture",
                              "calibration_version": "fixture", "score_semantics": "fixture", "nli_backend": "local", "no_llm_fallback": True}}
    return (deepcopy(envelope), deepcopy({**keys, "origin_round": "origin", "candidates": candidates}),
            deepcopy({"issuer_id": "S3-synthetic", "bindings": records}), {"issuer_id": "S3-synthetic", "bindings": []})


def test_binding_check_matches_frozen_units_and_preserves_original_denominator() -> None:
    envelope, candidates, verification, history = submission()
    history["bindings"].append(verification["bindings"][0])
    assert check_submission(envelope, candidates, verification, history) == {
        "checked": 10, "passed": 9, "failed": 1, "final_units": 10, "replacement_links": 1}


@pytest.mark.parametrize(("mutation", "code"), [
    ("stale", "BINDING_REVISION_MISMATCH"), ("wrong_digest", "BINDING_DIGEST_MISMATCH"),
    ("changed_unit", "BINDING_FINAL_UNIT_MISMATCH"), ("cross_source", "BINDING_SOURCE_MISMATCH"),
    ("wrong_seed", "BINDING_REPLACEMENT_SEED"), ("missing_pass", "S3_FINAL_UNIT_NOT_PASSED"),
    ("cycle", "BINDING_REPLACEMENT_CYCLE"), ("duplicate", "BINDING_REPLACEMENT_DUPLICATE"),
    ("id_conflict", "BINDING_VALIDATION_ID_CONFLICT"), ("omit_final", "BINDING_FINAL_SET_MISMATCH"),
    ("denominator", "BINDING_ORIGINAL_COUNTS_MISMATCH"), ("detached_link", "BINDING_LINK_MISMATCH"),
])
def test_binding_check_rejects_mismatched_evidence(mutation: str, code: str) -> None:
    envelope, candidates, verification, history = submission()
    report = envelope["s3_report"]
    records = verification["bindings"]
    if mutation == "stale":
        records[-1]["unit_revision"] = "r0"
    elif mutation == "wrong_digest":
        records[-1]["content_sha256"] = report["unit_results"][-1]["content_sha256"] = "0" * 64
    elif mutation == "changed_unit":
        envelope["units"][-1]["question"] = "修改后的题面？"
    elif mutation == "cross_source":
        records[-1]["source_revision"] = "unrelated"
    elif mutation == "wrong_seed":
        report["replacements"][0]["seed_id"] = "wrong"
    elif mutation == "missing_pass":
        records[-1]["status"] = report["unit_results"][-1]["status"] = "FAIL"
    elif mutation == "cycle":
        report["replacements"][0]["to_binding"] = records[-2]
    elif mutation == "duplicate":
        report["replacements"].append(report["replacements"][0])
    elif mutation == "id_conflict":
        history["bindings"].append({**records[-1], "source_revision": "different-snapshot"})
    elif mutation == "omit_final":
        envelope["units"].pop()
    elif mutation == "denominator":
        report.update(checked=20, passed=19, pass_rate=.95)
    elif mutation == "detached_link":
        report["replacements"][0]["candidate_ref"] = "bad-target"
    with pytest.raises(DomainError) as failure:
        check_submission(envelope, candidates, verification, history)
    assert failure.value.code == code
