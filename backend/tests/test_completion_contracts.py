from copy import deepcopy

import pytest
from helpers import demo_payload
from test_domain import formal_payload

from openkb_s4.domain.contracts import validate_import
from openkb_s4.domain.errors import DomainError
from openkb_s4.security import ApiError
from openkb_s4.services.common import validate_final_gold, validate_review


def review(unit):
    docs = unit["gold"]["gold_doc_ids"]
    return {
        "review_version": "openkb.s4-review.v2",
        "point_labels": {"P001": "correct", "P002": "wrong"},
        "point_reasons": {
            "P001": "test source supports first",
            "P002": "test source contradicts second",
        },
        "point_evidence": {
            p: [{"doc_id": docs[0], "start": 0, "end": 5}] for p in ["P001", "P002"]
        },
        "evidence_labels": {d: 2 for d in docs},
        "evidence_reasons": {d: "synthetic source directly supports answer" for d in docs},
        "answerable": "answerable",
        "answerable_reason": "synthetic source contains answer",
        "reason": "test-only structured review",
        "suggested_points": [],
        "evidence_changes": [],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(suggested_points=True),
        lambda p: p.update(
            evidence_changes=[
                {
                    "change_id": "C1",
                    "action": "invalid",
                    "doc_id": "not-source",
                    "reason": "",
                    "locators": [],
                }
            ]
        ),
        lambda p: p.pop("point_reasons"),
        lambda p: p["point_evidence"]["P001"][0].update(end=100000),
        lambda p: p["evidence_labels"].update({"doc-0": True}),
        lambda p: p.update(secret="unknown"),
    ],
)
def test_v2_review_rejects_invalid_structured_fields(mutation):
    unit = demo_payload()["units"][0]
    payload = review(unit)
    mutation(payload)
    with pytest.raises(ApiError):
        validate_review(unit, payload)


def test_d4_evidence_grade_three_rejected():
    unit = deepcopy(demo_payload()["units"][0])
    unit["dataset"] = "QA-D4"
    unit["gold"]["answer_points"] = []
    with pytest.raises(ApiError):
        validate_review(
            unit, {"reason": "test", "evidence_labels": {"doc-0": 3}, "answerable": "no_answer"}
        )


def test_specialized_boolean_rejected():
    with pytest.raises(ApiError):
        validate_review({"dataset": "SEC-D1"}, {"reason": "test", "specialized_review": True})


@pytest.mark.parametrize(
    "gold",
    [
        {"answer_points": [], "gold_doc_ids": [], "answerable": "answerable"},
        {
            "answer_points": ["test"],
            "gold_doc_ids": ["doc-0"],
            "answerable": "answerable",
            "gold_spans": [{"doc_id": "doc-0", "start": 8, "end": 2}],
        },
        {
            "answer_points": ["test"],
            "gold_doc_ids": ["doc-0"],
            "answerable": "answerable",
            "unknown": True,
        },
    ],
)
def test_final_gold_uses_complete_candidate_cross_validation(gold):
    with pytest.raises(ApiError):
        validate_final_gold(demo_payload()["units"][0], gold)


def test_import_rejects_out_of_bounds_gold_span():
    payload = demo_payload()
    payload["units"][0]["gold"]["gold_spans"] = [{"doc_id": "doc-0", "start": 0, "end": 10000}]
    with pytest.raises(DomainError):
        validate_import(payload)


def test_formal_s3_aggregate_pass_cannot_replace_original_point_evidence():
    payload = formal_payload()
    for item in payload["s3_report"]["unit_results"]:
        item.pop("point_results", None)
    with pytest.raises(DomainError, match="point_results"):
        validate_import(payload)


@pytest.mark.parametrize(
    "label,scope,accepted",
    [
        ("wrong", ["doc-0"], True),
        ("correct", ["doc-0"], False),
        ("partial", ["doc-0"], False),
        ("wrong", [], False),
        ("wrong", ["unknown"], False),
        ("wrong", ["doc-0", "doc-0"], False),
    ],
)
def test_no_support_requires_wrong_label_and_explicit_valid_search_scope(label, scope, accepted):
    unit = demo_payload()["units"][0]
    payload = review(unit)
    payload["point_labels"]["P001"] = label
    payload["point_evidence"]["P001"] = []
    payload["point_search_scope"] = {"P001": scope}
    if accepted:
        validate_review(unit, payload)
    else:
        with pytest.raises(ApiError):
            validate_review(unit, payload)


@pytest.mark.parametrize(
    "locator",
    [
        {"doc_id": "unknown", "span": "section"},
        {"doc_id": "doc-0"},
        {"doc_id": "doc-0", "start": True, "end": 4},
        {"doc_id": "doc-0", "start": 0, "end": 2, "page": False},
        {"doc_id": "doc-0", "span": " "},
        {"doc_id": "doc-0", "span": "section", "context_version": "wrong"},
        {"doc_id": "doc-0", "span": "section", "context_sha256": "0" * 64},
        {"doc_id": "doc-0", "start": 4, "end": 2},
        {"doc_id": "doc-0", "page": 2},
    ],
)
def test_locators_reject_invalid_source_version_range_and_page(locator):
    from openkb_s4.domain.review import validate_locator

    unit = demo_payload()["units"][0]
    unit["contexts"][0]["page"] = 1
    with pytest.raises(ApiError):
        validate_locator(unit, locator)


def test_v2_suggestions_changes_and_specialty_are_typed_and_source_scoped():
    unit = demo_payload()["units"][0]
    payload = review(unit)
    unit["contexts"].append({"doc_id": "extra", "text": "synthetic new evidence"})
    payload["suggested_points"] = [
        {
            "suggestion_id": "S1",
            "text": "synthetic added point",
            "reason": "new source claim",
            "evidence": [{"doc_id": "extra", "span": "section 1"}],
        }
    ]
    payload["evidence_changes"] = [
        {
            "change_id": "C1",
            "action": "add",
            "doc_id": "extra",
            "reason": "source supports addition",
            "locators": [{"doc_id": "extra", "start": 0, "end": 5}],
        }
    ]
    validate_review(unit, payload)
    payload["suggested_points"].append(deepcopy(payload["suggested_points"][0]))
    with pytest.raises(ApiError):
        validate_review(unit, payload)


def test_specialized_v2_requires_every_registered_observation():
    from openkb_s4.domain.profiles import specialized_fields

    unit = {"dataset": "SEC-D1", "contexts": [{"doc_id": "doc", "text": "synthetic acl source"}]}
    observation = {
        "observation": "test behavior",
        "reason": "test source check",
        "evidence": [{"doc_id": "doc", "span": "scope"}],
    }
    payload = {
        "review_version": "openkb.s4-review.v2",
        "reason": "synthetic review",
        "specialized_review": {
            field: deepcopy(observation) for field in specialized_fields("SEC-D1")
        },
    }
    validate_review(unit, payload)
    payload["specialized_review"]["acl_scope"] = True
    with pytest.raises(ApiError):
        validate_review(unit, payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kappa_strategy", "injected_strategy"),
        ("point_labels", ["new-label"]),
        ("blind_fields", ["gold"]),
        ("formal_enabled", True),
    ],
)
def test_profile_cannot_override_registered_core_rules(field, value):
    from openkb_s4.domain.profiles import baseline_snapshot, validate_profile_snapshot

    profile = baseline_snapshot("QA-D4")
    profile[field] = value
    with pytest.raises(DomainError):
        validate_profile_snapshot("QA-D4", profile)


def test_profile_unsafe_schema_rejected_and_registered_schema_passes():
    from openkb_s4.domain.profiles import baseline_snapshot, validate_profile_snapshot

    profile = baseline_snapshot("QA-D1")
    validate_profile_snapshot("QA-D1", profile)
    profile["input_schema"] = {"$ref": "https://untrusted.example/schema"}
    with pytest.raises(DomainError):
        validate_profile_snapshot("QA-D1", profile)


@pytest.mark.parametrize("dataset", ["QA-D2", "QA-D3", "QA-D4", "QA-D5", "QA-D7"])
def test_v2_specialized_qa_observations_cannot_be_omitted(dataset):
    unit = demo_payload()["units"][0]
    unit["dataset"] = dataset
    if dataset == "QA-D4":
        unit["gold"]["answer_points"] = []
        unit["gold"]["answerable"] = "no_answer"
    payload = review(unit)
    if dataset == "QA-D4":
        payload["point_labels"] = {}
        payload["point_reasons"] = {}
        payload["point_evidence"] = {}
        payload["answerable"] = "no_answer"
    with pytest.raises(ApiError):
        validate_review(unit, payload)


def test_specialty_material_is_finite_and_visible_only_after_review():
    from openkb_s4.services.common import safe_material

    unit = demo_payload()["units"][0]
    unit["dataset"] = "QA-D3"
    unit["metadata"].update(
        {
            "reasoning_chain": [{"hop": 1, "doc_id": "doc-0", "reason": "synthetic hop"}],
            "private_validation_secret": "hidden",
        }
    )
    assert "reasoning_chain" not in safe_material(unit, "BLIND")
    visible = safe_material(unit, "REVIEW")
    assert visible["reasoning_chain"][0]["hop"] == 1
    assert "private_validation_secret" not in str(visible)


def test_d5_key_facts_from_gold_are_review_only():
    from openkb_s4.services.common import safe_material

    unit = demo_payload()["units"][0]
    unit["dataset"] = "QA-D5"
    unit["gold"]["key_facts"] = ["one", "two", "three"]
    assert "key_facts" not in safe_material(unit, "BLIND")
    assert safe_material(unit, "REVIEW")["key_facts"] == ["one", "two", "three"]


def test_profile_cannot_approve_a_custom_schema_that_runtime_would_ignore():
    from openkb_s4.domain.profiles import baseline_snapshot, validate_profile_snapshot

    profile = baseline_snapshot("QA-D1")
    profile["input_schema"] = {"type": "object", "required": ["unimplemented_field"]}
    with pytest.raises(DomainError):
        validate_profile_snapshot("QA-D1", profile)


def test_d5_final_gold_key_facts_cannot_hide_invalid_type_behind_top_level_facts():
    unit = demo_payload()["units"][0]
    unit["dataset"] = "QA-D5"
    unit["unit_id"] = "QA-D5-0000"
    unit["key_facts"] = ["fact1", "fact2", "fact3"]
    gold = deepcopy(unit["gold"])
    gold["key_facts"] = True
    with pytest.raises(ApiError):
        validate_final_gold(unit, gold)
