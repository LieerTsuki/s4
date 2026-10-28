"""Strict local S3→S4 inline contract, with evidence and source digest checks."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from datetime import datetime
from fractions import Fraction
from hashlib import sha256
from typing import Any, NoReturn
from urllib.parse import urlsplit

from .errors import DomainError
from .profiles import ANSWERABILITY, DIFFICULTIES, SOURCE_TYPES, get_profile

CONTRACT_VERSION = "openkb.s3-s4.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOP_FIELDS = {
    "contract_version",
    "mode",
    "batch_id",
    "source_revision",
    "units",
    "s3_report",
    "source_manifest",
    "checksums",
}
_UNIT_FIELDS = {
    "unit_id",
    "dataset",
    "difficulty",
    "source_type",
    "seed_id",
    "question",
    "gold",
    "metadata",
    "contexts",
    "payload",
    "expected_behavior",
    "acl_context",
    "inject_plan",
    "chunk",
    "quality_metrics",
    "key_facts",
    "source_case_ids",
    "evaluation_k",
    "time_context",
    "access_context",
}
_CONTEXT_FIELDS = {
    "doc_id",
    "text",
    "title",
    "license",
    "source_url",
    "version",
    "sha256",
    "page",
    "start",
    "end",
    "valid_from",
    "valid_until",
    "acl_context",
}
_GOLD_FIELDS = {
    "answer_points",
    "gold_doc_ids",
    "gold_spans",
    "answerable",
    "relevance_grades",
    "key_facts",
}


def canonical_sha256(value: object) -> str:
    """Hash finite canonical UTF-8 JSON without platform-dependent whitespace."""
    try:
        serialized = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        encoded = serialized.encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise DomainError("INVALID_JSON", "内容必须是有限、可序列化的JSON。") from exc
    return sha256(encoded).hexdigest()


def _fail(code: str, field: str) -> NoReturn:
    raise DomainError(code, f"输入契约字段无效或缺少证据：{field}。")


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail("INVALID_OBJECT", field)
    return value


def _array(value: object, field: str, *, minimum: int = 0, maximum: int = 100000) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _fail("INVALID_ARRAY", field)
    return value


def _string(value: object, field: str, *, maximum: int = 30000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail("INVALID_STRING", field)
    return value


def _identifier(value: object, field: str) -> str:
    text = _string(value, field, maximum=160)
    if not _IDENTIFIER.fullmatch(text):
        _fail("INVALID_IDENTIFIER", field)
    return text


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail("INVALID_COUNT", field)
    return value


def _hash(value: object, field: str) -> str:
    text = _string(value, field, maximum=64)
    if not _SHA256.fullmatch(text):
        _fail("INVALID_SHA256", field)
    return text


def _timestamp(value: object, field: str) -> None:
    text = _string(value, field, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("INVALID_TIMESTAMP", field)
        return
    if parsed.tzinfo is None:
        _fail("INVALID_TIMESTAMP", field)


def _only_fields(value: dict[str, Any], allowed: set[str], field: str) -> None:
    if value.keys() - allowed:
        _fail("UNKNOWN_FIELDS", field)


def _ids(value: object, field: str, *, minimum: int = 0) -> list[str]:
    result = [_identifier(item, field) for item in _array(value, field, minimum=minimum)]
    if len(result) != len(set(result)):
        _fail("DUPLICATE_IDENTIFIER", field)
    return result


def _validate_context(context: dict[str, Any], formal: bool) -> None:
    _only_fields(context, _CONTEXT_FIELDS, "contexts")
    _identifier(context.get("doc_id"), "contexts.doc_id")
    text = _string(context.get("text"), "contexts.text", maximum=500000)
    if "sha256" in context or formal:
        if (
            _hash(context.get("sha256"), "contexts.sha256")
            != sha256(text.encode("utf-8")).hexdigest()
        ):
            _fail("CONTEXT_DIGEST_MISMATCH", "contexts.sha256")
    for name in ("title", "license", "version"):
        if name in context:
            _string(context[name], f"contexts.{name}", maximum=30000 if name == "title" else 160)
    for name in ("valid_from", "valid_until"):
        if name in context:
            _timestamp(context[name], f"contexts.{name}")
    if formal:
        license_name = _string(context.get("license"), "contexts.license", maximum=160)
        if license_name.strip().lower() in {"unknown", "none", "unlicensed"}:
            _fail("SOURCE_LICENSE_MISSING", "contexts.license")
        _string(context.get("version"), "contexts.version", maximum=160)
    if "source_url" in context or formal:
        source_url = _string(context.get("source_url"), "contexts.source_url", maximum=2000)
        try:
            parsed = urlsplit(source_url)
        except ValueError:
            _fail("INVALID_SOURCE_URL", "contexts.source_url")
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            _fail("INVALID_SOURCE_URL", "contexts.source_url")
    if "page" in context:
        _integer(context["page"], "contexts.page", minimum=1)
    if "start" in context or "end" in context:
        start = _integer(context.get("start"), "contexts.start")
        end = _integer(context.get("end"), "contexts.end")
        if end <= start:
            _fail("INVALID_SOURCE_RANGE", "contexts.start/end")


def _validate_gold(unit: dict[str, Any], context_ids: set[str]) -> None:
    dataset = unit["dataset"]
    gold = _mapping(unit.get("gold"), "gold")
    _only_fields(gold, _GOLD_FIELDS, "gold")
    points = _array(gold.get("answer_points"), "gold.answer_points", maximum=200)
    for point in points:
        _string(point, "gold.answer_points")
    if dataset == "QA-D4":
        if points or gold.get("answerable") == "answerable":
            _fail("D4_REQUIRES_EMPTY_POINTS", "gold")
    elif not points:
        _fail("MISSING_ANSWER_POINTS", "gold.answer_points")
    if gold.get("answerable") not in ANSWERABILITY:
        _fail("INVALID_ANSWERABILITY", "gold.answerable")
    doc_ids = _ids(
        gold.get("gold_doc_ids"), "gold.gold_doc_ids", minimum=0 if dataset == "QA-D4" else 1
    )
    if not set(doc_ids) <= context_ids:
        _fail("GOLD_DOCUMENT_NOT_IN_SCOPE", "gold.gold_doc_ids")
    for raw_span in _array(gold.get("gold_spans", []), "gold.gold_spans", maximum=500):
        span = _mapping(raw_span, "gold.gold_spans")
        _only_fields(span, {"doc_id", "span", "start", "end", "page"}, "gold.gold_spans")
        if span.get("doc_id") not in doc_ids:
            _fail("SPAN_DOCUMENT_NOT_IN_GOLD", "gold.gold_spans.doc_id")
        if "span" in span:
            _string(span["span"], "gold.gold_spans.span")
        elif "start" not in span or "end" not in span:
            _fail("SPAN_LOCATION_MISSING", "gold.gold_spans")
        if "start" in span or "end" in span:
            start = _integer(span.get("start"), "gold.gold_spans.start")
            end = _integer(span.get("end"), "gold.gold_spans.end")
            if end <= start:
                _fail("INVALID_SOURCE_RANGE", "gold.gold_spans.start/end")
        if "page" in span:
            _integer(span["page"], "gold.gold_spans.page", minimum=1)
    from ..security import ApiError
    from .review import validate_locator

    for index, span in enumerate(gold.get("gold_spans", [])):
        try:
            validate_locator(unit, span, f"gold.gold_spans.{index}")
        except ApiError as exc:
            raise DomainError(exc.code, exc.message) from exc
    if "key_facts" in gold:
        facts = _array(
            gold["key_facts"],
            "gold.key_facts",
            minimum=3 if dataset == "QA-D5" else 0,
            maximum=5 if dataset == "QA-D5" else 200,
        )
        for fact in facts:
            _string(fact, "gold.key_facts")
    if "relevance_grades" in gold:
        grades = _mapping(gold["relevance_grades"], "gold.relevance_grades")
        if not set(grades) <= set(doc_ids):
            _fail("GRADE_DOCUMENT_NOT_IN_GOLD", "gold.relevance_grades")
        if any(type(grade) is not int or grade not in {0, 1, 2} for grade in grades.values()):
            _fail("INVALID_RELEVANCE_GRADE", "gold.relevance_grades")


def _validate_unit(unit: dict[str, Any], formal: bool) -> list[str]:
    _only_fields(unit, _UNIT_FIELDS, "units")
    unit_id = _identifier(unit.get("unit_id"), "unit_id")
    dataset = _string(unit.get("dataset"), "dataset", maximum=16)
    profile = get_profile(dataset)
    if not unit_id.startswith(f"{dataset}-"):
        _fail("UNIT_DATASET_MISMATCH", "unit_id")
    if unit.get("difficulty") not in DIFFICULTIES:
        _fail("INVALID_DIFFICULTY", "difficulty")
    if "source_type" in unit or formal:
        if unit.get("source_type") not in SOURCE_TYPES:
            _fail("INVALID_SOURCE_TYPE", "source_type")
    if "seed_id" in unit or formal:
        _identifier(unit.get("seed_id"), "seed_id")
    metadata = _mapping(unit.get("metadata", {}), "metadata")
    if formal:
        for name in ("lang", "domain", "generation_model"):
            _string(metadata.get(name), f"metadata.{name}")
        _timestamp(metadata.get("created_at"), "metadata.created_at")
    contexts = [
        _mapping(context, "contexts")
        for context in _array(unit.get("contexts", []), "contexts", maximum=500)
    ]
    context_ids: set[str] = set()
    for context in contexts:
        _validate_context(context, formal)
        if context["doc_id"] in context_ids:
            _fail("DUPLICATE_CONTEXT", "contexts.doc_id")
        context_ids.add(context["doc_id"])
    blockers: list[str] = list(profile["blocked_reasons"])
    if profile["kind"] == "security":
        if "gold" in unit or "question" in unit:
            _fail("SEC_HAS_NO_QA_GOLD", "units")
        for name in ("payload", "expected_behavior"):
            value = unit.get(name)
            if not isinstance(value, dict):
                _string(value, name)
            elif not value:
                _fail("INVALID_OBJECT", name)
        if not _mapping(unit.get("acl_context"), "acl_context"):
            _fail("SEC_SCOPE_REQUIRED", "acl_context")
        if dataset == "SEC-D3":
            _mapping(unit.get("inject_plan"), "inject_plan")
            if formal:
                rollback = _mapping(metadata.get("rollback_evidence"), "metadata.rollback_evidence")
                if type(rollback.get("residual")) is not int or rollback["residual"] != 0:
                    _fail("SEC_RESIDUAL_NOT_ZERO", "metadata.rollback_evidence.residual")
    elif profile["kind"] == "chunk_quality":
        if "gold" in unit:
            _fail("D6_HAS_NO_QA_GOLD", "gold")
        _string(unit.get("chunk"), "chunk", maximum=500000)
        _mapping(unit.get("quality_metrics"), "quality_metrics")
    else:
        _string(unit.get("question"), "question")
        if not contexts:
            _fail("CONTEXT_SCOPE_REQUIRED", "contexts")
        _validate_gold(unit, context_ids)
        if dataset == "QA-D5" and formal:
            facts = _array(
                unit.get("key_facts", unit["gold"].get("key_facts")),
                "key_facts",
                minimum=3,
                maximum=5,
            )
            for fact in facts:
                _string(fact, "key_facts")
        if dataset == "QA-D7":
            _ids(unit.get("source_case_ids"), "source_case_ids", minimum=1)
            _integer(unit.get("evaluation_k"), "evaluation_k", minimum=1)
            # The versioned local policy has no confirmed multiplier formula.
            # An importer-supplied approval cannot change that configuration.
            blockers.append("D7_K_RULE_REQUIRES_APPROVAL")
    return blockers


def _validate_nli(result: dict[str, Any], report: dict[str, Any]) -> None:
    reverse = _mapping(result.get("reverse_validation"), "unit_results.reverse_validation")
    if reverse.get("status") != "PASS" or reverse.get("model") != report["validator_model"]:
        _fail("REVERSE_VALIDATION_MISSING", "unit_results.reverse_validation")
    nli = _mapping(result.get("nli"), "unit_results.nli")
    score = nli.get("score")
    if (
        not isinstance(score, (float, int))
        or isinstance(score, bool)
        or not 0 <= score <= 1
        or not math.isfinite(score)
    ):
        _fail("INVALID_NLI_SCORE", "unit_results.nli.score")
    if nli.get("model") != report["nli_model"] or nli.get("version") != report["nli_version"]:
        _fail("NLI_VERSION_MISMATCH", "unit_results.nli")
    if score < 0.45:
        _fail("NLI_REJECTED", "unit_results.nli")
    if 0.45 <= score <= 0.65:
        fallback = _mapping(result.get("fallback"), "unit_results.fallback")
        _string(report.get("fallback_model"), "s3_report.fallback_model")
        _string(report.get("fallback_version"), "s3_report.fallback_version")
        if (
            fallback.get("status") != "PASS"
            or fallback.get("model") != report["fallback_model"]
            or fallback.get("version") != report["fallback_version"]
        ):
            _fail("NLI_FALLBACK_MISSING", "unit_results.fallback")


def _validate_formal(payload: dict[str, Any], units: list[dict[str, Any]]) -> None:
    report = _mapping(payload.get("s3_report"), "s3_report")
    checked = _integer(report.get("checked_count"), "s3_report.checked_count", minimum=1)
    passed = _integer(report.get("passed_count"), "s3_report.passed_count")
    failed = _integer(report.get("failed_count"), "s3_report.failed_count")
    if passed + failed != checked:
        _fail("S3_COUNT_MISMATCH", "s3_report")
    if Fraction(passed, checked) < Fraction(93, 100):
        _fail("S3_PASS_RATE_BELOW_93", "s3_report")
    if _integer(report.get("unresolved_failure_count"), "s3_report.unresolved_failure_count") != 0:
        _fail("UNRESOLVED_S3_FAILURES", "s3_report")
    generator = _string(report.get("generation_model"), "s3_report.generation_model")
    validator = _string(report.get("validator_model"), "s3_report.validator_model")
    if generator.strip().casefold() == validator.strip().casefold():
        _fail("S3_MODEL_SELF_VALIDATION", "s3_report")
    for name in ("validator_version", "nli_model", "nli_version"):
        _string(report.get(name), f"s3_report.{name}")
    if "bart" not in report["nli_model"].lower() or "mnli" not in report["nli_model"].lower():
        _fail("S3_NLI_MODEL_NOT_BART_MNLI", "s3_report.nli_model")
    original = _array(
        report.get("original_results"),
        "s3_report.original_results",
        minimum=checked,
        maximum=checked,
    )
    originals: dict[str, str] = {}
    original_seeds: dict[str, str] = {}
    for raw in original:
        item = _mapping(raw, "s3_report.original_results")
        unit_id = _identifier(item.get("unit_id"), "s3_report.original_results.unit_id")
        status = _string(item.get("status"), "s3_report.original_results.status")
        if unit_id in originals or status not in {"PASS", "FAIL"}:
            _fail("INVALID_ORIGINAL_RESULTS", "s3_report.original_results")
        originals[unit_id] = status
        if "seed_id" in item:
            original_seeds[unit_id] = _identifier(item["seed_id"], "original_results.seed_id")
    if sum(status == "PASS" for status in originals.values()) != passed:
        _fail("S3_ORIGINAL_COUNTS_MISMATCH", "s3_report.original_results")
    failed_ids = {unit_id for unit_id, status in originals.items() if status == "FAIL"}
    archive = set(_ids(report.get("archived_failures"), "s3_report.archived_failures"))
    if archive != failed_ids:
        _fail("S3_FAILURE_ARCHIVE_MISMATCH", "s3_report.archived_failures")
    selected = {unit["unit_id"]: unit for unit in units}
    replacements: dict[str, str] = {}
    for raw in _array(report.get("replacement_lineage"), "s3_report.replacement_lineage"):
        link = _mapping(raw, "s3_report.replacement_lineage")
        replacement_id = _identifier(
            link.get("replacement_unit_id"), "replacement_lineage.replacement_unit_id"
        )
        failed_id = _identifier(link.get("failed_unit_id"), "replacement_lineage.failed_unit_id")
        if (
            failed_id not in failed_ids
            or replacement_id not in selected
            or replacement_id in replacements
        ):
            _fail("INVALID_REPLACEMENT_LINEAGE", "s3_report.replacement_lineage")
        if link.get("seed_id") != selected[replacement_id].get("seed_id"):
            _fail("REPLACEMENT_SEED_MISMATCH", "replacement_lineage.seed_id")
        if original_seeds.get(failed_id) != selected[replacement_id].get("seed_id"):
            _fail("REPLACEMENT_ORIGINAL_SEED_MISMATCH", "replacement_lineage.seed_id")
        _string(link.get("validation_revision"), "replacement_lineage.validation_revision")
        replacements[replacement_id] = failed_id
    final_results = _array(
        report.get("unit_results"), "s3_report.unit_results", minimum=len(units), maximum=len(units)
    )
    final_ids: set[str] = set()
    for raw in final_results:
        item = _mapping(raw, "s3_report.unit_results")
        unit_id = _identifier(item.get("unit_id"), "unit_results.unit_id")
        if unit_id not in selected or unit_id in final_ids or item.get("status") != "PASS":
            _fail("FINAL_SELECTION_NOT_PASS", "s3_report.unit_results")
        final_ids.add(unit_id)
        unit = selected[unit_id]
        if originals.get(unit_id) != "PASS" and unit_id not in replacements:
            _fail("FINAL_SELECTION_LINEAGE_MISSING", "s3_report.unit_results")
        if _hash(item.get("content_sha256"), "unit_results.content_sha256") != canonical_sha256(
            unit
        ):
            _fail("UNIT_DIGEST_MISMATCH", "unit_results.content_sha256")
        if unit["metadata"]["generation_model"] != generator:
            _fail("GENERATION_MODEL_MISMATCH", "metadata.generation_model")
        _validate_nli(item, report)
        if unit.get("gold", {}).get("answer_points"):
            point_results = _array(
                item.get("point_results"),
                "unit_results.point_results",
                minimum=len(unit["gold"]["answer_points"]),
                maximum=len(unit["gold"]["answer_points"]),
            )
            expected_points = {
                f"P{index + 1:03d}": point
                for index, point in enumerate(unit["gold"]["answer_points"])
            }
            seen_points: set[str] = set()
            for raw_point in point_results:
                evidence = _mapping(raw_point, "unit_results.point_results")
                _only_fields(
                    evidence,
                    {
                        "point_key",
                        "point_sha256",
                        "content_sha256",
                        "reverse_validation",
                        "nli",
                        "fallback",
                    },
                    "unit_results.point_results",
                )
                key = _identifier(evidence.get("point_key"), "unit_results.point_results.point_key")
                if key not in expected_points or key in seen_points:
                    _fail("S3_POINT_COVERAGE_MISMATCH", "unit_results.point_results.point_key")
                seen_points.add(key)
                if evidence.get("point_sha256") != canonical_sha256(
                    expected_points[key]
                ) or evidence.get("content_sha256") != canonical_sha256(unit):
                    _fail("S3_POINT_DIGEST_MISMATCH", "unit_results.point_results")
                reverse = _mapping(
                    evidence.get("reverse_validation"),
                    "unit_results.point_results.reverse_validation",
                )
                if (
                    reverse.get("version") != report["validator_version"]
                    or type(reverse.get("coverage")) is not int
                    or reverse["coverage"] != 1
                ):
                    _fail(
                        "S3_POINT_REVERSE_COVERAGE_MISSING",
                        "unit_results.point_results.reverse_validation",
                    )
                _validate_nli(evidence, report)

    contexts = [context for unit in units for context in unit.get("contexts", [])]
    checksums = _mapping(payload.get("checksums"), "checksums")
    manifest = _mapping(payload.get("source_manifest"), "source_manifest")
    if (
        manifest.get("batch_id") != payload["batch_id"]
        or manifest.get("source_revision") != payload["source_revision"]
    ):
        _fail("SOURCE_REVISION_MISMATCH", "source_manifest")
    if _integer(manifest.get("selected_count"), "source_manifest.selected_count") != len(units):
        _fail("SOURCE_SELECTED_COUNT_MISMATCH", "source_manifest.selected_count")
    _timestamp(manifest.get("generated_at"), "source_manifest.generated_at")
    _string(manifest.get("code_version"), "source_manifest.code_version")
    for field, content in (("units_sha256", units), ("contexts_sha256", contexts)):
        actual_hash = canonical_sha256(content)
        if (
            _hash(checksums.get(field), f"checksums.{field}") != actual_hash
            or _hash(manifest.get(field), f"source_manifest.{field}") != actual_hash
        ):
            _fail("SOURCE_DIGEST_MISMATCH", field)


def validate_import(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate local input and return an independent snapshot plus blockers.

    Invalid evidence raises DomainError. Material can be schema-valid while
    formal delivery remains blocked by external alignment or unapproved rules.
    This distinction never converts a self-declared formal flag into approval.
    """
    data = _mapping(payload, "payload")
    _only_fields(data, _TOP_FIELDS, "payload")
    canonical_sha256(data)
    if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > 32 * 1024 * 1024:
        _fail("IMPORT_TOO_LARGE", "payload")
    if data.get("contract_version") != CONTRACT_VERSION:
        _fail("UNSUPPORTED_CONTRACT", "contract_version")
    if data.get("mode") not in ("demo", "formal"):
        _fail("INVALID_IMPORT_MODE", "mode")
    _identifier(data.get("batch_id"), "batch_id")
    _identifier(data.get("source_revision"), "source_revision")
    raw_units = _array(data.get("units"), "units", minimum=1, maximum=2200)
    formal = data["mode"] == "formal"
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    snapshots: dict[tuple[str, str], str] = {}
    blockers: list[str] = []
    for raw in raw_units:
        unit = _mapping(raw, "units")
        blockers.extend(_validate_unit(unit, formal))
        if unit["unit_id"] in seen:
            _fail("DUPLICATE_UNIT_ID", "unit_id")
        seen.add(unit["unit_id"])
        for context in unit.get("contexts", []):
            key = (context["doc_id"], context.get("version", ""))
            text_hash = sha256(context["text"].encode("utf-8")).hexdigest()
            if key in snapshots and snapshots[key] != text_hash:
                _fail("CONTEXT_VERSION_CONFLICT", "contexts")
            snapshots[key] = text_hash
        units.append(unit)
    if formal:
        _validate_formal(data, units)
        blockers.append("EXTERNAL_CONTRACT_NOT_ALIGNED")
    result = deepcopy(data)
    result["blocked_reasons"] = sorted(set(blockers))
    return result


def validate_candidate(unit: dict[str, Any]) -> None:
    """Validate a complete final candidate using the same import cross checks."""
    _validate_unit(unit, False)
    if unit["dataset"] == "QA-D5":
        facts = _array(
            unit.get("key_facts", unit.get("gold", {}).get("key_facts")),
            "key_facts",
            minimum=3,
            maximum=5,
        )
        for fact in facts:
            _string(fact, "key_facts")
