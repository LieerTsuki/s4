"""v1.3 contract regression cases: records, observation and special materials."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from openkb_s4.domain.errors import DomainError


def qa_unit(index: int = 0, dataset: str = "QA-D1") -> dict[str, Any]:
    text = "合成😀材料明确支持一个正确要点。"
    return {
        "unit_id": f"{dataset}-{index:04d}", "dataset": dataset,
        "difficulty": ["easy", "medium", "hard"][index % 3],
        "question": "合成材料支持什么？", "domain": "synthetic",
        "contexts": [{"doc_id": f"doc-{index}", "text": text}],
        "gold": {"answer_points": ["合成正确要点", "合成错误要点"],
                 "gold_doc_ids": [f"doc-{index}"],
                 "relevance_grades": {f"doc-{index}": 3},
                 "ranking_annotations": {}, "expected_refusal": False,
                 "absence_reason": None},
        "metadata": {"generation_model": "synthetic-demo"},
    }


def envelope(count: int = 12) -> dict[str, Any]:
    return {"contract_version": "openkb.s3-s4.v2", "mode": "demo",
            "batch_id": "V13-DEMO", "source_revision": "r1",
            "units": [qa_unit(index) for index in range(count)]}


def review(unit: dict[str, Any]) -> dict[str, Any]:
    doc = unit["contexts"][0]
    loc = {"doc_id": doc["doc_id"], "start": 0, "end": 2,
           "context_sha256": sha256(doc["text"].encode()).hexdigest(), "quote": "合成"}
    return {"review_version": "openkb.s4-review.v3", "workflow_kind": "VERIFICATION",
            "verdict": "NEEDS_REVISION", "point_labels": {"P001": "correct", "P002": "wrong"},
            "point_reasons": {"P001": "原文支持", "P002": "已查原文无支持"},
            "point_evidence": {"P001": [loc], "P002": []},
            "point_search_scope": {"P002": [doc["doc_id"]]},
            "evidence_assessments": {doc["doc_id"]: {"grade": 3, "reason": "直接支持",
                "locators": [loc], "intent": "KEEP_GOLD"}},
            "expected_refusal": False, "absence_reason": None,
            "expected_refusal_reason": "材料足以回答"}


def test_v13_contract_does_not_promote_legacy_labels() -> None:
    from openkb_s4.domain.v13 import validate_envelope
    result = validate_envelope(envelope())
    assert result["units"][0]["gold"]["relevance_grades"] == {"doc-0": 3}
    legacy = envelope()
    legacy["units"][0]["gold"]["answerable"] = "answerable"
    with pytest.raises(DomainError):
        validate_envelope(legacy)


@pytest.mark.parametrize("grade", [0, 1, True, "3"])
def test_gold_rejects_non_gold_grades(grade: object) -> None:
    from openkb_s4.domain.v13 import validate_unit
    unit = qa_unit()
    unit["gold"]["relevance_grades"]["doc-0"] = grade
    with pytest.raises(DomainError):
        validate_unit(unit)


@pytest.mark.parametrize("mutation", ["overlap", "missing", "ranking_high", "chinese_difficulty", "string_bool", "numeric_bool"])
def test_strict_partitions_and_storage_enums(mutation: str) -> None:
    from openkb_s4.domain.v13 import validate_unit
    unit = qa_unit()
    if mutation == "overlap":
        unit["gold"]["ranking_annotations"] = {"doc-0": 1}
    elif mutation == "missing":
        unit["gold"]["relevance_grades"] = {}
    elif mutation == "ranking_high":
        unit["gold"]["ranking_annotations"] = {"doc-other": 2}
    elif mutation == "chinese_difficulty":
        unit["difficulty"] = "简单"
    else:
        unit["gold"]["expected_refusal"] = "false" if mutation == "string_bool" else 0
    with pytest.raises(DomainError):
        validate_unit(unit)


def test_d4_refusal_has_no_fabricated_answer_points() -> None:
    from openkb_s4.domain.v13 import validate_unit
    unit = qa_unit(dataset="QA-D4")
    unit["gold"].update(answer_points=[], gold_doc_ids=[], relevance_grades={}, expected_refusal=True,
                        absence_reason="库内无答案")
    validate_unit(unit)
    unit["gold"]["expected_refusal"] = False
    with pytest.raises(DomainError):
        validate_unit(unit)
    unit = qa_unit(dataset="QA-D4C")
    unit["gold"]["expected_refusal"] = True
    unit["gold"]["absence_reason"] = "库内无答案"
    with pytest.raises(DomainError):
        validate_unit(unit)


def test_review_per_point_scope_and_unicode_quote() -> None:
    from openkb_s4.domain.v13 import validate_review
    unit = qa_unit()
    payload = review(unit)
    validate_review(unit, payload)
    bad = deepcopy(payload)
    bad["point_search_scope"] = {}
    with pytest.raises(DomainError):
        validate_review(unit, bad)
    bad = deepcopy(payload)
    bad["point_evidence"]["P001"][0].update(start=2, end=3, quote="😀")
    validate_review(unit, bad)
    bad["point_evidence"]["P001"][0]["end"] = 4
    with pytest.raises(DomainError):
        validate_review(unit, bad)


def test_review_covers_gold_and_ranking_documents_and_moves_explicitly() -> None:
    from openkb_s4.domain.v13 import validate_review
    unit = qa_unit()
    unit["contexts"].append({"doc_id": "background", "text": "背景"})
    unit["gold"]["ranking_annotations"] = {"background": 1}
    payload = review(unit)
    with pytest.raises(DomainError):
        validate_review(unit, payload)
    payload["evidence_assessments"]["background"] = {
        "grade": 1, "reason": "背景相关", "locators": [{"doc_id": "background", "start": 0, "end": 2}],
        "intent": "KEEP_RANKING"}
    validate_review(unit, payload)
    payload["evidence_assessments"]["doc-0"].update(grade=1, intent="KEEP_GOLD")
    with pytest.raises(DomainError):
        validate_review(unit, payload)
    payload["evidence_assessments"]["doc-0"]["intent"] = "MOVE_TO_RANKING"
    validate_review(unit, payload)


def test_s3_preserves_denominator_and_requires_current_passes() -> None:
    from openkb_s4.domain.v13 import validate_envelope
    body = envelope(8)
    body["mode"] = "formal"
    body["s3_report"] = {
        "checked": 100, "passed": 92, "failed": 8, "pass_rate": 0.92,
        "unit_results": [{"unit_id": unit["unit_id"], "status": "PASS"} for unit in body["units"]],
        "failed_ids": [f"rejected-{i}" for i in range(8)], "replacements": [],
        "model_versions": {"nli": "bge-reranker-v1"}, "threshold_version": "t1",
        "calibration_version": "cal1", "score_semantics": "calibrated_relevance",
        "nli_backend": "local", "no_llm_fallback": True,
    }
    validate_envelope(body)
    washed = deepcopy(body)
    washed["s3_report"]["pass_rate"] = 1.0
    with pytest.raises(DomainError):
        validate_envelope(washed)
    failed = deepcopy(body)
    failed["s3_report"]["unit_results"][0]["status"] = "FAIL"
    with pytest.raises(DomainError):
        validate_envelope(failed)
    low = deepcopy(body)
    low["s3_report"].update(passed=89, failed=11, pass_rate=0.89,
                            failed_ids=[f"bad-{i}" for i in range(11)])
    with pytest.raises(DomainError):
        validate_envelope(low)


def test_sampling_small_dataset_shortfall_and_deterministic_strata() -> None:
    from openkb_s4.domain.v13 import sample_units
    small = sample_units(envelope(2)["units"], 42)
    assert small["actual_count"] == 2 and small["required_count"] == 8 and small["shortfall"] == 6
    units = envelope(100)["units"]
    first = sample_units(units, 42)
    assert len(first["selected_ids"]) == 10
    assert first == sample_units(list(reversed(units)), 42)
    assert first["selected_ids"] != sample_units(units, 43)["selected_ids"]
    assert {row["difficulty"] for row in first["strata"]} == {"easy", "medium", "hard"}


def test_sampling_applies_minimum_per_dataset_not_per_difficulty() -> None:
    from openkb_s4.domain.v13 import sample_units
    units = envelope(12)["units"] + [qa_unit(index, "QA-D2") for index in range(10)]
    ledger = sample_units(units, 10)
    assert ledger["required_count"] == 16 and ledger["actual_count"] == 16


def test_quality_actions_use_exact_boundaries_and_undefined_not_one() -> None:
    from openkb_s4.domain.v13 import observation_result
    assert observation_result([], [])["action"] == "UNDEFINED"
    assert observation_result(["correct"], ["correct"])["kappa"] is None
    left = ["correct"] * 10 + ["wrong"] * 10
    right = left.copy()
    right[0], right[10] = "wrong", "correct"
    assert observation_result(left, right)["action"] == "NORMAL"
    right[1], right[11] = "wrong", "correct"
    value = observation_result(left, right)
    assert value["kappa"] == 0.6 and value["action"] == "EXPAND_CALIBRATE"
    right[2] = "wrong"
    assert observation_result(left, right)["action"] == "RETURN_TO_S2"
    assert "verdict" not in value


def test_d4_pairing_reports_missing_side_na_and_strata_mismatch() -> None:
    from openkb_s4.domain.v13 import batch_constraints
    unit = qa_unit(dataset="QA-D4")
    value = batch_constraints({"units": [unit]})
    assert value["d4_pairing"]["metrics_status"] == "N/A"
    assert "D4_PAIR_MISSING_SIDE" in value["blocked_reasons"]
    other = qa_unit(dataset="QA-D4C")
    other["difficulty"] = "hard"
    value = batch_constraints({"units": [unit, other]})
    assert "D4_PAIR_STRATA_MISMATCH" in value["blocked_reasons"]


def d6_unit() -> dict[str, Any]:
    text = "😀甲公司位于北京"
    return {"unit_id": "QA-D6-0001", "dataset": "QA-D6", "difficulty": "easy",
            "text": text, "text_digest": sha256(text.encode()).hexdigest(),
            "corpus_id": "synthetic", "schema_version": "1.0", "contexts": [],
            "gold": {"gold_entities": [{"entity_id": "e1", "name": "甲公司", "type": "ORG", "span": [1, 4]},
                                       {"entity_id": "e2", "name": "北京", "type": "LOC", "span": [6, 8]}],
                     "gold_relations": [{"head": "e1", "tail": "e2", "type": "LOCATED_IN"}]}}


def test_d6_span_digest_and_relation_references_without_invented_vocabulary() -> None:
    from openkb_s4.domain.v13 import source_blockers, validate_unit
    unit = d6_unit()
    validate_unit(unit)
    assert "D6_VOCABULARY_UNCONFIRMED" in source_blockers({"units": [unit], "mode": "demo"})
    for mutation in ("digest", "utf16", "dangling"):
        invalid = deepcopy(unit)
        if mutation == "digest":
            invalid["text_digest"] = "0" * 64
        elif mutation == "utf16":
            invalid["gold"]["gold_entities"][0]["span"] = [2, 5]
        else:
            invalid["gold"]["gold_relations"][0]["head"] = "missing"
        with pytest.raises(DomainError):
            validate_unit(invalid)


def test_d6_trusted_vocabulary_hook_rejects_unknown_types() -> None:
    from openkb_s4.domain.v13 import validate_unit
    dictionary = {"version": "synthetic-v1", "entity_types": ["ORG", "LOC", "OTHER"],
                  "relation_types": ["LOCATED_IN", "OTHER_REL"]}
    unit = d6_unit()
    validate_unit(unit, vocabulary=dictionary)
    unit["gold"]["gold_entities"][0]["type"] = "invented"
    with pytest.raises(DomainError):
        validate_unit(unit, vocabulary=dictionary)


def test_sec_effect_and_poison_baseline_materials() -> None:
    from openkb_s4.domain.v13 import validate_unit
    base: dict[str, Any] = {"unit_id": "SEC-D2-0001", "dataset": "SEC-D2", "difficulty": "easy",
                           "payload": "合成静态载荷", "expected_behavior": "拦截", "contexts": [],
                           "attack_type_detail": "pending-source", "expected_effect": {"kind": "marker", "marker_string": "SYNTH"}}
    validate_unit(base)
    base["expected_effect"] = {"kind": "marker", "description": "wrong"}
    with pytest.raises(DomainError):
        validate_unit(base)
    now = datetime.now(UTC)
    poison = {**base, "unit_id": "SEC-D3-0001", "dataset": "SEC-D3", "expected_effect": None,
              "target_claim": "合成错误结论", "baseline_answer": "合成正确结论",
              "baseline_captured_at": (now - timedelta(days=1)).isoformat(),
              "injection_started_at": now.isoformat(), "baseline_unpoisoned": True,
              "inject_plan": {"doc_id_hint": "poison-doc", "rollback": {"residual": 0, "evidence": "synthetic-audit"}},
              "detection_signals": []}
    validate_unit(poison)
    poison["baseline_captured_at"] = (now + timedelta(seconds=3)).isoformat()
    with pytest.raises(DomainError):
        validate_unit(poison)


def test_rank_uses_position_and_absence_is_n_plus_one() -> None:
    from openkb_s4.domain.v13 import membership_rank, validate_unit
    assert membership_rank([{"doc_id": "a", "score": 0.0001}, {"doc_id": "b", "score": 999}], "b", 10) == 2
    assert membership_rank([], "a", 10) == 11
    unit: dict[str, Any] = {"unit_id": "SEC-D4-0001", "dataset": "SEC-D4", "difficulty": "easy",
        "payload": "合成成员推理", "expected_behavior": "不泄露成员信息", "contexts": [],
        "member_doc_id": "a", "nonmember_doc_id": "b", "pair_controls": {"length": True, "style": True, "domain": True},
        "top_n": 10, "match_field": "score"}
    validate_unit(unit)
    normalized = envelope(0)
    normalized["units"] = [unit]
    from openkb_s4.domain.v13 import validate_envelope
    result = validate_envelope(normalized)
    assert "match_field" not in result["units"][0]
    assert "LEGACY_MATCH_FIELD_IGNORED" in result["warnings"]


def test_d7_requires_human_same_intent_and_max_source_k() -> None:
    from openkb_s4.domain.v13 import validate_unit
    unit = qa_unit(dataset="QA-D7")
    source = qa_unit(index=10)
    source["evaluation_k"] = 5
    unit.update(source_case_ids=[source["unit_id"]], resolved_sources=[source], evaluation_k=5,
                same_intent_confirmation={"confirmed": True, "person_id": "synthetic-human", "reason": "核对同一查询意图"})
    unit["gold"].update(gold_doc_ids=["doc-10"], relevance_grades={"doc-10": 3})
    unit["contexts"] = source["contexts"]
    validate_unit(unit)
    unit["evaluation_k"] = 10
    with pytest.raises(DomainError):
        validate_unit(unit)
    unit["evaluation_k"] = 5
    unit["same_intent_confirmation"]["confirmed"] = False
    with pytest.raises(DomainError):
        validate_unit(unit)


def test_verified_cannot_hide_findings_or_changes() -> None:
    from openkb_s4.domain.v13 import validate_review
    unit = qa_unit()
    payload = review(unit)
    payload["verdict"] = "VERIFIED"
    with pytest.raises(DomainError):
        validate_review(unit, payload)
    payload["point_labels"]["P002"] = "correct"
    payload["point_evidence"]["P002"] = payload["point_evidence"]["P001"]
    validate_review(unit, payload)
    payload["evidence_assessments"]["doc-0"]["grade"] = 2
    with pytest.raises(DomainError):
        validate_review(unit, payload)


def test_specialized_review_is_finite_and_missing_dictionary_blocks_verified() -> None:
    from openkb_s4.domain.v13 import validate_review
    unit = d6_unit()
    payload = {"workflow_kind": "VERIFICATION", "verdict": "NEEDS_REVISION",
               "extraction": unit["gold"], "specialized_review": {
                   field: {"observation": "pass", "reason": "合成材料核对", "evidence": []}
                   for field in ("entity_spans", "entity_types", "relation_links")}}
    validate_review(unit, payload)
    payload["specialized_review"]["entity_types"]["observation"] = "invented"
    with pytest.raises(DomainError):
        validate_review(unit, payload)


def test_d6_missing_gold_rejected() -> None:
    from openkb_s4.domain.v13 import validate_unit
    unit = d6_unit()
    unit.pop("gold")
    with pytest.raises(DomainError):
        validate_unit(unit)


def test_d6_can_record_zero_entities_without_invented_presence_gate() -> None:
    from openkb_s4.domain.v13 import validate_unit
    unit = d6_unit()
    unit["gold"] = {"gold_entities": [], "gold_relations": []}
    validate_unit(unit)


@pytest.mark.parametrize("left,right", [(None, []), ("correct", []), ([{}], [{}]), ([True], [True])])
def test_quality_rejects_malformed_vectors_safely(left: Any, right: Any) -> None:
    from openkb_s4.domain.v13 import observation_result
    with pytest.raises(DomainError):
        observation_result(left, right)


def test_gold_span_checks_frozen_document_and_quote() -> None:
    from openkb_s4.domain.v13 import validate_unit
    unit = qa_unit()
    unit["gold"]["gold_spans"] = [{"doc_id": "not-authorized", "start": 0, "end": 1}]
    with pytest.raises(DomainError):
        validate_unit(unit)


def test_specialized_statistic_never_uses_empty_vector_as_perfect_agreement() -> None:
    from openkb_s4.domain.v13 import source_blockers
    assert "SPECIALIZED_STATISTICS_UNCONFIRMED" in source_blockers({"units": [d6_unit()]})


def test_published_v13_schemas_and_synthetic_examples_match_runtime() -> None:
    import json

    from openkb_s4.domain.v13 import (
        ReviewV3,
        SourceEnvelope,
        Unit,
        validate_envelope,
        validate_review,
    )
    root = Path(__file__).resolve().parents[2] / "contracts" / "v13"
    for model, name in ((SourceEnvelope, "source-envelope"), (Unit, "unit"), (ReviewV3, "review")):
        schema = json.loads((root / f"{name}.schema.json").read_text(encoding="utf-8"))
        schema.pop("$schema")
        assert schema == model.model_json_schema()
    source = json.loads((root / "examples" / "demo-import.json").read_text(encoding="utf-8"))
    payload = json.loads((root / "examples" / "review-needs-revision.json").read_text(encoding="utf-8"))
    SourceEnvelope.model_validate(source)
    ReviewV3.model_validate(payload)
    validate_envelope(source)
    validate_review(source["units"][0], payload)
