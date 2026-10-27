"""Domain regressions: independent labels, source evidence, and sample accounting."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest


def module(name: str) -> Any:
    return import_module(f"openkb_s4.domain.{name}")


def digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def unit(index: int, difficulty: str = "简单", dataset: str = "QA-D1") -> dict[str, Any]:
    return {
        "unit_id": f"{dataset}-{index:04d}",
        "dataset": dataset,
        "difficulty": difficulty,
        "source_type": "生产流量采样",
        "seed_id": f"SYNTHETIC-{index:04d}",
        "question": f"合成规则{index}包含哪些步骤？",
        "gold": {
            "answer_points": [f"合成步骤{index}A", f"合成步骤{index}B"],
            "gold_doc_ids": [f"doc-{index}"],
            "gold_spans": [{"doc_id": f"doc-{index}", "span": "§1"}],
            "answerable": "answerable",
        },
        "contexts": [
            {
                "doc_id": f"doc-{index}",
                "text": f"仅用于测试：合成规则{index}包括步骤A和步骤B。",
                "license": "CC0-1.0",
                "source_url": "https://example.org/synthetic-fixture",
                "version": "fixture-v1",
            }
        ],
        "metadata": {
            "lang": "zh",
            "domain": "合成测试",
            "generation_model": "synthetic-generator-v1",
            "created_at": "2026-10-27T00:00:00Z",
        },
    }


def demo_payload(count: int = 8) -> dict[str, Any]:
    return {
        "contract_version": "openkb.s3-s4.v1",
        "mode": "demo",
        "batch_id": "SYNTHETIC-DEMO-001",
        "source_revision": "synthetic-r1",
        "units": [unit(i, ["简单", "中等", "困难"][i % 3]) for i in range(count)],
    }


def formal_payload() -> dict[str, Any]:
    payload = demo_payload()
    payload["mode"] = "formal"
    for item in payload["units"]:
        for context in item["contexts"]:
            context["sha256"] = sha256(context["text"].encode()).hexdigest()
    selected = payload["units"]
    original_results = [
        {
            "unit_id": selected[i]["unit_id"] if i < len(selected) else f"original-{i}",
            "status": "PASS" if i < 95 else "FAIL",
        }
        for i in range(100)
    ]
    final_results = [
        {
            "unit_id": item["unit_id"],
            "status": "PASS",
            "content_sha256": digest(item),
            "reverse_validation": {"status": "PASS", "model": "validator-v1"},
            "nli": {"score": 0.9, "model": "bart-large-mnli", "version": "fixture-v1"},
        }
        for item in selected
    ]
    payload["s3_report"] = {
        "checked_count": 100,
        "passed_count": 95,
        "failed_count": 5,
        "unresolved_failure_count": 0,
        "generation_model": "synthetic-generator-v1",
        "validator_model": "validator-v1",
        "validator_version": "fixture-v1",
        "nli_model": "bart-large-mnli",
        "nli_version": "fixture-v1",
        "original_results": original_results,
        "unit_results": final_results,
        "archived_failures": [f"original-{i}" for i in range(95, 100)],
        "replacement_lineage": [],
    }
    contexts = [context for item in selected for context in item["contexts"]]
    payload["checksums"] = {"units_sha256": digest(selected), "contexts_sha256": digest(contexts)}
    payload["source_manifest"] = {
        "batch_id": payload["batch_id"],
        "source_revision": payload["source_revision"],
        "selected_count": len(selected),
        "units_sha256": digest(selected),
        "contexts_sha256": digest(contexts),
        "generated_at": "2026-10-27T00:00:00Z",
        "code_version": "fixture-code-v1",
    }
    return payload


def test_profiles_keep_specialized_statistics_blocked() -> None:
    profiles = module("profiles").list_profiles()
    assert len(profiles) == 12
    assert sum(p["quota"] for p in profiles if p["dataset"].startswith("QA")) == 1600
    assert sum(p["quota"] for p in profiles if p["dataset"].startswith("SEC")) == 600
    for profile in profiles:
        if profile["dataset"] in {"QA-D4", "QA-D6"} or profile["dataset"].startswith("SEC"):
            assert profile["formal_enabled"] is False
            assert profile["blocked_reasons"]


@pytest.mark.parametrize(
    ("size", "errors", "expected", "verdict"),
    [
        (40, 6, 0.7, "ACCEPT"),
        (20, 4, 0.6, "ARBITRATE"),
        (10000, 1501, 0.6998, "ARBITRATE"),
        (10000, 2001, 0.5998, "REJECT_BATCH"),
    ],
)
def test_raw_kappa_boundaries_are_not_rounded(
    size: int, errors: int, expected: float, verdict: str
) -> None:
    left = ["correct"] * (size // 2) + ["wrong"] * (size // 2)
    right = left.copy()
    for index in range(errors):
        right[index] = "wrong"
    result = module("statistics").calculate_agreement(left, right)
    assert result["kappa"] == pytest.approx(expected)
    assert result["verdict"] == verdict


@pytest.mark.parametrize(
    ("left", "right"), [([], []), (["correct"], []), (["correct"] * 8, ["correct"] * 8)]
)
def test_empty_missing_and_degenerate_vectors_are_blocked(
    left: list[str], right: list[str]
) -> None:
    result = module("statistics").calculate_agreement(left, right)
    assert result["kappa"] is None
    assert result["verdict"] == "BLOCKED"
    assert result["blocked_reasons"]


def test_arbitrary_label_and_bool_are_not_accepted_as_point_labels() -> None:
    error = module("errors").DomainError
    for label in ["accept", "na", True, None]:
        with pytest.raises(error):
            module("statistics").calculate_agreement(["correct", label], ["correct", "wrong"])


def test_kappa_matches_sklearn_for_three_categories() -> None:
    sklearn = pytest.importorskip("sklearn.metrics")
    left = ["correct", "partial", "wrong", "correct", "partial", "wrong"]
    right = ["correct", "wrong", "wrong", "correct", "partial", "partial"]
    result = module("statistics").calculate_agreement(left, right)
    assert result["kappa"] == pytest.approx(sklearn.cohen_kappa_score(left, right))


def test_sampling_is_reproducible_independent_of_input_order_and_covers_minor_strata() -> None:
    units = [unit(i) for i in range(98)] + [unit(98, "中等"), unit(99, "困难")]
    first = module("sampling").sample_units(units, seed=731)
    second = module("sampling").sample_units(list(reversed(units)), seed=731)
    assert first == second
    assert len(first["selected_ids"]) == 10
    assert "QA-D1-0098" in first["selected_ids"]
    assert "QA-D1-0099" in first["selected_ids"]
    assert not first["blocked_reasons"]


def test_sampling_counts_each_dataset_and_reports_small_populations_without_duplication() -> None:
    units = [unit(i) for i in range(12)] + [unit(i, dataset="QA-D2") for i in range(3)]
    result = module("sampling").sample_units(units, seed=13)
    selected = result["selected_ids"]
    assert len([item for item in selected if item.startswith("QA-D1")]) == 8
    assert len([item for item in selected if item.startswith("QA-D2")]) == 3
    assert len(selected) == len(set(selected))
    assert any("QA-D2" in reason for reason in result["blocked_reasons"])


def test_duplicate_unit_ids_are_rejected_before_sampling() -> None:
    with pytest.raises(module("errors").DomainError):
        module("sampling").sample_units([unit(1), unit(1)], seed=13)


def test_demo_import_keeps_teaching_mode_and_independent_original_objects() -> None:
    payload = demo_payload()
    result = module("contracts").validate_import(payload)
    assert result["mode"] == "demo"
    result["units"][0]["gold"]["answer_points"][0] = "changed"
    assert payload["units"][0]["gold"]["answer_points"][0] == "合成步骤0A"


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "unknown_dataset",
        "missing_context",
        "bad_answerability",
        "grade3",
        "path",
        "extra_secret",
    ],
)
def test_invalid_imports_are_rejected_before_persistence(mutation: str) -> None:
    payload = demo_payload()
    if mutation == "duplicate":
        payload["units"].append(deepcopy(payload["units"][0]))
    elif mutation == "unknown_dataset":
        payload["units"][0]["dataset"] = "QA-D8"
    elif mutation == "missing_context":
        payload["units"][0]["contexts"] = []
    elif mutation == "bad_answerability":
        payload["units"][0]["gold"]["answerable"] = "unknown"
    elif mutation == "grade3":
        payload["units"][0]["gold"]["relevance_grades"] = {"doc-0": 3}
    elif mutation == "path":
        payload["units_ref"] = "../../secret.jsonl"
    else:
        payload["units"][0]["admin_token"] = "should-not-be-accepted"
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_declared_formal_pass_is_not_s3_evidence() -> None:
    payload = demo_payload()
    payload.update(mode="formal", s3_report={"passed": True})
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_formal_keeps_original_95_percent_and_blocks_unaligned_external_claims() -> None:
    result = module("contracts").validate_import(formal_payload())
    assert result["s3_report"]["checked_count"] == 100
    assert result["s3_report"]["passed_count"] == 95
    assert result["s3_report"]["failed_count"] == 5
    assert result["s3_report"]["unresolved_failure_count"] == 0
    assert "EXTERNAL_CONTRACT_NOT_ALIGNED" in result["blocked_reasons"]


@pytest.mark.parametrize(
    "mutation",
    [
        "rate",
        "washed_denominator",
        "bad_hash",
        "same_model",
        "missing_nli",
        "unresolved",
        "missing_archive",
        "unit_fail",
        "manifest_count",
        "context_tamper",
        "missing_origin",
    ],
)
def test_formal_rejects_incomplete_or_inconsistent_evidence(mutation: str) -> None:
    payload = formal_payload()
    report = payload["s3_report"]
    if mutation == "rate":
        report["passed_count"], report["failed_count"] = 92, 8
        report["original_results"] = [
            {"unit_id": f"original-{i}", "status": "PASS" if i < 92 else "FAIL"} for i in range(100)
        ]
        report["archived_failures"] = [f"original-{i}" for i in range(92, 100)]
    elif mutation == "washed_denominator":
        report["checked_count"], report["failed_count"] = 95, 0
    elif mutation == "bad_hash":
        report["unit_results"][0]["content_sha256"] = "0" * 64
    elif mutation == "same_model":
        report["validator_model"] = report["generation_model"]
    elif mutation == "missing_nli":
        del report["unit_results"][0]["nli"]
    elif mutation == "unresolved":
        report["unresolved_failure_count"] = 1
    elif mutation == "missing_archive":
        report["archived_failures"] = []
    elif mutation == "unit_fail":
        report["unit_results"][0]["status"] = "FAIL"
    elif mutation == "manifest_count":
        payload["source_manifest"]["selected_count"] = 1
    elif mutation == "context_tamper":
        payload["units"][0]["contexts"][0]["text"] = "tampered"
    else:
        del payload["units"][0]["contexts"][0]["source_url"]
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_specialized_units_do_not_gain_fake_answer_points() -> None:
    payload = demo_payload(1)
    payload["units"] = [
        {
            "unit_id": "SEC-D1-0001",
            "dataset": "SEC-D1",
            "difficulty": "简单",
            "payload": "合成越权请求",
            "expected_behavior": "拒答",
            "acl_context": {"role": "visitor"},
            "contexts": [{"doc_id": "scope", "text": "合成访问作用域"}],
        }
    ]
    result = module("contracts").validate_import(payload)
    assert "gold" not in result["units"][0]
    assert any("SPECIALIZED" in reason for reason in result["blocked_reasons"])
    payload["units"][0]["gold"] = {
        "answer_points": ["invented"],
        "gold_doc_ids": [],
        "answerable": "answerable",
    }
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_d4_keeps_empty_points_and_specialized_profile_blocked() -> None:
    payload = demo_payload(1)
    item = payload["units"][0]
    item["dataset"], item["unit_id"] = "QA-D4", "QA-D4-0001"
    item["gold"]["answer_points"] = []
    item["gold"]["answerable"] = "no_answer"
    result = module("contracts").validate_import(payload)
    assert result["units"][0]["gold"]["answer_points"] == []
    assert result["blocked_reasons"]


def test_d7_never_invents_evaluation_k_multiplier() -> None:
    payload = demo_payload(1)
    item = payload["units"][0]
    item["dataset"], item["unit_id"] = "QA-D7", "QA-D7-0001"
    item["source_case_ids"] = ["QA-D1-0001"]
    item["evaluation_k"] = 20
    result = module("contracts").validate_import(payload)
    assert result["units"][0]["evaluation_k"] == 20
    assert any("D7" in reason for reason in result["blocked_reasons"])


def test_invalid_mode_object_is_a_domain_error_not_an_unhandled_type_error() -> None:
    payload = demo_payload()
    payload["mode"] = []
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_replacement_must_keep_the_failed_original_seed() -> None:
    payload = formal_payload()
    report = payload["s3_report"]
    report["original_results"][0]["unit_id"] = "original-not-selected"
    report["original_results"][95]["seed_id"] = "DIFFERENT-FAILED-SEED"
    report["replacement_lineage"] = [
        {
            "failed_unit_id": "original-95",
            "replacement_unit_id": payload["units"][0]["unit_id"],
            "seed_id": payload["units"][0]["seed_id"],
            "validation_revision": "replacement-validation-v1",
        }
    ]
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_sec_requires_an_explicit_scope() -> None:
    payload = demo_payload(1)
    payload["units"] = [
        {
            "unit_id": "SEC-D1-0001",
            "dataset": "SEC-D1",
            "difficulty": "简单",
            "payload": "合成越权请求",
            "expected_behavior": "拒答",
            "acl_context": {},
        }
    ]
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


@pytest.mark.parametrize("score", [0.45, 0.55, 0.65])
def test_nli_ambiguity_band_requires_a_bound_fallback_model(score: float) -> None:
    payload = formal_payload()
    report = payload["s3_report"]
    report["unit_results"][0]["nli"]["score"] = score
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)
    report.update(fallback_model="fallback-judge-v1", fallback_version="fixture-v1")
    report["unit_results"][0]["fallback"] = {
        "status": "PASS",
        "model": "fallback-judge-v1",
        "version": "fixture-v1",
    }
    result = module("contracts").validate_import(payload)
    assert result["s3_report"]["unit_results"][0]["nli"]["score"] == score


def test_source_hash_rejects_non_finite_values() -> None:
    for number in [float("nan"), float("inf"), float("-inf")]:
        with pytest.raises(module("errors").DomainError):
            module("contracts").canonical_sha256({"score": number})


def test_profile_lookup_returns_an_independent_object() -> None:
    profile = module("profiles").get_profile("QA-D1")
    profile["point_labels"].append("accept")
    assert "accept" not in module("profiles").get_profile("QA-D1")["point_labels"]


@pytest.mark.parametrize("value", [None, 42, {}, "correct"])
def test_invalid_vector_containers_raise_domain_errors(value: Any) -> None:
    with pytest.raises(module("errors").DomainError):
        module("statistics").calculate_agreement(value, ["correct"])


@pytest.mark.parametrize("value", [None, 42, {}, [42]])
def test_invalid_sampling_containers_raise_domain_errors(value: Any) -> None:
    with pytest.raises(module("errors").DomainError):
        module("sampling").sample_units(value, seed=7)


@pytest.mark.parametrize("field", ["version", "source_url", "valid_until"])
def test_malformed_context_attributes_raise_domain_errors(field: str) -> None:
    payload = demo_payload(1)
    payload["units"][0]["contexts"][0][field] = {}
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_invalid_url_parser_input_is_a_domain_error() -> None:
    payload = formal_payload()
    payload["units"][0]["contexts"][0]["source_url"] = "https://[broken"
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_unpaired_unicode_is_a_domain_error() -> None:
    with pytest.raises(module("errors").DomainError):
        module("contracts").canonical_sha256({"text": "\ud800"})


def test_oversized_integer_nli_score_is_rejected_without_overflow() -> None:
    payload = formal_payload()
    payload["s3_report"]["unit_results"][0]["nli"]["score"] = 10**400
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


def test_d7_payload_cannot_approve_its_own_unconfirmed_multiplier_rule() -> None:
    payload = demo_payload(1)
    item = payload["units"][0]
    item.update(dataset="QA-D7", unit_id="QA-D7-0001", source_case_ids=["QA-D1-0001"], evaluation_k=20)
    item["metadata"]["evaluation_k_rule_approval"] = {
        "rule_version": "self-asserted-v1",
        "approved_by": "payload-author",
        "approved_at": "2026-10-27T00:00:00Z",
    }
    result = module("contracts").validate_import(payload)
    assert "D7_K_RULE_REQUIRES_APPROVAL" in result["blocked_reasons"]


def test_published_synthetic_formal_fixture_remains_externally_blocked() -> None:
    path = Path(__file__).resolve().parents[2] / "contracts/examples/synthetic-formal-contract-test.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["batch_id"].startswith("SYNTHETIC-")
    result = module("contracts").validate_import(payload)
    assert result["s3_report"]["checked_count"] == 100
    assert result["s3_report"]["passed_count"] == 95
    assert result["blocked_reasons"] == ["EXTERNAL_CONTRACT_NOT_ALIGNED"]


@pytest.mark.parametrize("filename", ["invalid-formal-assertion.json", "invalid-washed-denominator.json"])
def test_published_failure_fixtures_are_rejected(filename: str) -> None:
    path = Path(__file__).resolve().parents[2] / "contracts/examples" / filename
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("field", ["checked_count", "passed_count", "failed_count", "unresolved_failure_count"])
def test_formal_counts_cannot_be_boolean(field: str) -> None:
    payload = formal_payload()
    payload["s3_report"][field] = True
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)


@pytest.mark.parametrize("reference", ["../../secret.jsonl", "C:\\private\\secret.jsonl", "https://example.org/input.jsonl"])
def test_import_never_accepts_implicit_remote_or_host_file_references(reference: str) -> None:
    payload = demo_payload(1)
    payload["units_ref"] = reference
    with pytest.raises(module("errors").DomainError):
        module("contracts").validate_import(payload)
