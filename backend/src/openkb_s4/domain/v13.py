"""Versioned v1.3 contracts, material validation and observation-only statistics.

These are local interchange contracts awaiting S3/S5 alignment. They never map
legacy evidence labels or invent missing specialist vocabularies.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from hashlib import sha256
from math import ceil
from random import Random
from typing import Annotated, Any, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

from .errors import DomainError

Dataset = Literal["QA-D1", "QA-D2", "QA-D3", "QA-D4", "QA-D4C", "QA-D5", "QA-D6", "QA-D7",
                  "SEC-D1", "SEC-D2", "SEC-D3", "SEC-D4", "SEC-D5"]
Difficulty = Literal["easy", "medium", "hard"]
AbsenceReason = Literal["库内无答案", "答案已过期", "答案在权限外"]
PointLabel = Literal["correct", "partial", "wrong"]
WorkflowKind = Literal["VERIFICATION", "OBSERVATION"]
QUOTAS = {"QA-D1": 500, "QA-D2": 200, "QA-D3": 100, "QA-D4": 100, "QA-D4C": 100,
          "QA-D5": 300, "QA-D6": 200, "QA-D7": 200, "SEC-D1": 100, "SEC-D2": 150,
          "SEC-D3": 50, "SEC-D4": 200, "SEC-D5": 100}
SOURCE_CONTRACT = "openkb.s3-s4.v2"
REVIEW_CONTRACT = "openkb.s4-review.v3"
HANDOFF_CONTRACT = "openkb.s4-s5.v2"
SPECIALIZED_FIELDS = {
    "QA-D2": ["domain_evidence"], "QA-D3": ["reasoning_chain"],
    "QA-D5": ["key_facts"], "QA-D7": ["same_intent", "source_lineage", "evaluation_k"],
    "QA-D6": ["entity_spans", "entity_types", "relation_links"],
    "SEC-D1": ["acl", "forbidden_documents"], "SEC-D2": ["expected_effect", "attack_type"],
    "SEC-D3": ["baseline", "target_claim", "rollback"],
    "SEC-D4": ["pair_controls", "ranking"], "SEC-D5": ["synthetic_pii", "non_disclosure"],
}
Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Nonempty = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Context(StrictModel):
    doc_id: Identifier
    text: str
    title: str | None = None
    version: str | None = None
    sha256: Digest | None = None
    page: Annotated[StrictInt, Field(ge=1)] | None = None
    source_url: str | None = None
    license: str | None = None
    domain: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    acl_context: dict[str, Any] | None = None


class LocatorV3(StrictModel):
    doc_id: Identifier
    context_version: str | None = None
    context_sha256: Digest | None = None
    start: Annotated[StrictInt, Field(ge=0)] | None = None
    end: Annotated[StrictInt, Field(ge=1)] | None = None
    page: Annotated[StrictInt, Field(ge=1)] | None = None
    span: str | None = None
    quote: str | None = None


class Entity(StrictModel):
    entity_id: Identifier | None = None
    name: Nonempty
    type: Nonempty
    span: Annotated[list[StrictInt], Field(min_length=2, max_length=2)]


class Relation(StrictModel):
    head: Nonempty
    tail: Nonempty
    type: Nonempty


class Extraction(StrictModel):
    gold_entities: list[Entity]
    gold_relations: list[Relation]


class Gold(StrictModel):
    answer_points: list[Nonempty] = Field(default_factory=list)
    gold_doc_ids: list[Identifier] = Field(default_factory=list)
    relevance_grades: dict[Identifier, Annotated[StrictInt, Field(ge=2, le=3)]] = Field(default_factory=dict)
    ranking_annotations: dict[Identifier, Annotated[StrictInt, Field(ge=0, le=1)]] = Field(default_factory=dict)
    gold_spans: list[dict[str, Any]] = Field(default_factory=list)
    expected_refusal: StrictBool | None = None
    absence_reason: AbsenceReason | None = None
    gold_entities: list[Entity] = Field(default_factory=list)
    gold_relations: list[Relation] = Field(default_factory=list)


class Effect(StrictModel):
    kind: Literal["marker", "target", "behavior"]
    marker_string: str | None = None
    target_string: str | None = None
    description: str | None = None


class Unit(StrictModel):
    unit_id: Identifier
    dataset: Dataset
    difficulty: Difficulty
    contexts: list[Context] = Field(default_factory=list)
    question: str | None = None
    gold: Gold | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_type: Literal["生产流量采样", "BEIR基线", "红队载荷源"] | None = None
    seed_id: str | None = None
    domain: str | None = None
    domains: list[str] = Field(default_factory=list)
    track: Literal["PUBLIC", "PRIVATE"] = "PRIVATE"
    version_locked: StrictBool = False
    evaluation_k: Annotated[StrictInt, Field(ge=1)] | None = None
    time_context: dict[str, Any] | None = None
    scope_context: dict[str, Any] | None = None
    acl_context: dict[str, Any] | None = None
    access_context: dict[str, Any] | None = None
    reasoning_chain: list[Any] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    source_case_ids: list[Identifier] = Field(default_factory=list)
    source_dataset: str | None = None
    resolved_sources: list[dict[str, Any]] = Field(default_factory=list)
    same_intent_confirmation: dict[str, Any] | None = None
    source_composition: dict[str, Any] | None = None
    pair_id: str | None = None
    paired_unit_id: str | None = None
    original_question: str | None = None
    text: str | None = None
    chunk: str | None = None
    text_digest: Digest | None = None
    corpus_id: str | None = None
    schema_version: str | None = None
    payload: str | dict[str, Any] | None = None
    expected_behavior: str | dict[str, Any] | None = None
    expected_effect: Effect | None = None
    attack_type_detail: str | None = None
    target_claim: str | None = None
    baseline_answer: str | None = None
    baseline_captured_at: str | None = None
    baseline_unpoisoned: StrictBool | None = None
    injection_started_at: str | None = None
    inject_plan: dict[str, Any] | None = None
    detection_signals: list[dict[str, Any]] = Field(default_factory=list)
    member_doc_id: str | None = None
    nonmember_doc_id: str | None = None
    pair_controls: dict[str, Any] | None = None
    top_n: Annotated[StrictInt, Field(ge=1, le=10000)] = 10
    match_field: str | None = None
    synthetic_pii: StrictBool | None = None
    synthetic_proof: str | dict[str, Any] | None = None


class UnitResult(StrictModel):
    unit_id: Identifier
    status: Literal["PASS", "FAIL"]
    content_sha256: Digest | None = None
    validation_id: str | None = None


class S3Report(StrictModel):
    checked: Annotated[StrictInt, Field(gt=0)]
    passed: Annotated[StrictInt, Field(ge=0)]
    failed: Annotated[StrictInt, Field(ge=0)]
    pass_rate: Annotated[float, Field(ge=0, le=1)]
    unit_results: list[UnitResult]
    failed_ids: list[Identifier]
    replacements: list[dict[str, Any]] = Field(default_factory=list)
    model_versions: dict[str, Nonempty]
    threshold_version: Nonempty
    calibration_version: Nonempty
    score_semantics: Nonempty
    nli_backend: Literal["local"]
    no_llm_fallback: StrictBool
    code_version: str | None = None
    config_version: str | None = None


class SourceEnvelope(StrictModel):
    contract_version: Literal["openkb.s3-s4.v2"]
    mode: Literal["demo", "formal"]
    batch_id: Identifier
    source_revision: Nonempty
    units: Annotated[list[Unit], Field(min_length=1, max_length=10000)]
    s3_report: S3Report | None = None
    source_manifest: dict[str, Any] | None = None
    checksums: dict[str, str] | None = None
    warnings: list[str] = Field(default_factory=list)


class EvidenceAssessment(StrictModel):
    grade: Annotated[StrictInt, Field(ge=0, le=3)]
    reason: Nonempty
    locators: list[LocatorV3] = Field(default_factory=list)
    intent: Literal["KEEP_GOLD", "KEEP_RANKING", "MOVE_TO_GOLD", "MOVE_TO_RANKING", "REMOVE"]


class SpecializedAssessment(StrictModel):
    observation: Literal["pass", "issue", "not_applicable"]
    reason: Nonempty
    evidence: list[LocatorV3] = Field(default_factory=list)


class SuggestedPointV3(StrictModel):
    suggestion_id: Identifier
    text: Nonempty
    reason: Nonempty
    evidence: Annotated[list[LocatorV3], Field(min_length=1)]


class EvidenceChangeV3(StrictModel):
    change_id: Identifier
    action: Literal["add", "remove"]
    doc_id: Identifier
    reason: Nonempty
    locators: list[LocatorV3] = Field(default_factory=list)


class ReviewV3(StrictModel):
    review_version: Literal["openkb.s4-review.v3"] = "openkb.s4-review.v3"
    workflow_kind: WorkflowKind
    verdict: Literal["VERIFIED", "NEEDS_REVISION", "RETURNED"]
    point_labels: dict[str, PointLabel] = Field(default_factory=dict)
    point_reasons: dict[str, Nonempty] = Field(default_factory=dict)
    point_evidence: dict[str, list[LocatorV3]] = Field(default_factory=dict)
    point_search_scope: dict[str, list[Identifier]] = Field(default_factory=dict)
    evidence_assessments: dict[Identifier, EvidenceAssessment] = Field(default_factory=dict)
    expected_refusal: StrictBool | None = None
    absence_reason: AbsenceReason | None = None
    expected_refusal_reason: str | None = None
    reason: str | None = None
    issues: list[str] = Field(default_factory=list)
    suggested_points: list[SuggestedPointV3] = Field(default_factory=list)
    evidence_changes: list[EvidenceChangeV3] = Field(default_factory=list)
    specialized_review: dict[str, SpecializedAssessment] = Field(default_factory=dict)
    extraction: Extraction | None = None


def fail(code: str, field: str) -> NoReturn:
    raise DomainError(code, f"v1.3字段或材料不满足要求：{field}")


def parse(model: type[BaseModel], value: dict[str, Any]) -> BaseModel:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        field = ".".join(str(part) for part in exc.errors()[0]["loc"])
        fail("V13_CONTRACT_INVALID", field)


def validate_envelope(body: dict[str, Any]) -> dict[str, Any]:
    """Validate, retain original counts and normalize only safe derived fields."""
    parsed = parse(SourceEnvelope, body)
    assert isinstance(parsed, SourceEnvelope)
    result = parsed.model_dump(exclude_none=True)
    units = result["units"]
    if len({unit["unit_id"] for unit in units}) != len(units):
        fail("UNIT_ID_DUPLICATE", "units.unit_id")
    for unit in units:
        validate_unit(unit)
        for document in unit["contexts"]:
            document["sha256"] = sha256(document["text"].encode("utf-8")).hexdigest()
        if unit.pop("match_field", None) is not None:
            result["warnings"].append("LEGACY_MATCH_FIELD_IGNORED")
    report = parsed.s3_report
    if parsed.mode == "formal" and report is None:
        fail("S3_REPORT_REQUIRED", "s3_report")
    if report is not None:
        if report.passed + report.failed != report.checked:
            fail("S3_DENOMINATOR_INVALID", "s3_report.checked/passed/failed")
        rate = Fraction(report.passed, report.checked)
        if abs(report.pass_rate - float(rate)) > 1e-12:
            fail("S3_DENOMINATOR_WASHED", "s3_report.pass_rate")
        if rate < Fraction(9, 10):
            fail("S3_RETURN_TO_S2", "s3_report.pass_rate")
        if len(set(report.failed_ids)) != report.failed or len(report.failed_ids) != report.failed:
            fail("S3_FAILURE_ARCHIVE_MISSING", "s3_report.failed_ids")
        statuses = {record.unit_id: record.status for record in report.unit_results}
        if len(statuses) != len(report.unit_results):
            fail("S3_DUPLICATE_UNIT_RESULT", "s3_report.unit_results")
        if any(statuses.get(unit["unit_id"]) != "PASS" for unit in units):
            fail("S3_FINAL_UNIT_NOT_PASSED", "s3_report.unit_results")
        if set(report.failed_ids) & {unit["unit_id"] for unit in units}:
            fail("S3_FAILED_UNIT_PRESENT", "s3_report.failed_ids")
        if not report.model_versions or not report.no_llm_fallback:
            fail("S3_MODEL_EVIDENCE_REQUIRED", "s3_report.model_versions/no_llm_fallback")
        if any(word in report.score_semantics.lower() for word in ("uncalibrated_probability", "raw_probability")):
            fail("S3_SCORE_SEMANTICS_INVALID", "s3_report.score_semantics")
    return result


def validate_unit(unit: dict[str, Any], vocabulary: dict[str, Any] | None = None) -> None:
    parsed = parse(Unit, unit)
    assert isinstance(parsed, Unit)
    documents = {document.doc_id: document for document in parsed.contexts}
    if len(documents) != len(parsed.contexts):
        fail("CONTEXT_DOCUMENT_DUPLICATE", "contexts.doc_id")
    for document in parsed.contexts:
        if document.sha256 is not None and document.sha256 != sha256(document.text.encode("utf-8")).hexdigest():
            fail("CONTEXT_DIGEST_MISMATCH", "contexts.sha256")
    if parsed.track == "PUBLIC" and parsed.dataset != "QA-D2":
        fail("TRACK_INVALID", "track")
    if parsed.dataset.startswith("QA") and parsed.dataset != "QA-D6":
        _validate_qa(parsed, documents)
        assert parsed.gold is not None
        for locator in parsed.gold.gold_spans:
            validate_locator(unit, locator)
    elif parsed.dataset == "QA-D6":
        _validate_extraction(parsed, vocabulary)
    else:
        _validate_sec(parsed, vocabulary)


def _validate_qa(unit: Unit, documents: dict[str, Context]) -> None:
    gold = unit.gold
    if not unit.question or not unit.question.strip() or gold is None:
        fail("QA_MATERIAL_REQUIRED", "question/gold")
    if gold.expected_refusal is None:
        fail("EXPECTED_REFUSAL_REQUIRED", "gold.expected_refusal")
    if gold.gold_entities or gold.gold_relations:
        fail("QA_GOLD_INVALID", "gold.gold_entities/gold_relations")
    ids = set(gold.gold_doc_ids)
    if len(ids) != len(gold.gold_doc_ids) or ids != set(gold.relevance_grades):
        fail("GOLD_COVERAGE_INVALID", "gold.relevance_grades")
    if any(grade not in (2, 3) for grade in gold.relevance_grades.values()):
        fail("GOLD_GRADE_INVALID", "gold.relevance_grades")
    if any(grade not in (0, 1) for grade in gold.ranking_annotations.values()):
        fail("RANKING_GRADE_INVALID", "gold.ranking_annotations")
    if ids & set(gold.ranking_annotations):
        fail("EVIDENCE_PARTITIONS_OVERLAP", "gold.ranking_annotations")
    if not ids | set(gold.ranking_annotations) <= set(documents):
        fail("EVIDENCE_DOCUMENT_UNKNOWN", "gold.gold_doc_ids/ranking_annotations")
    if unit.dataset == "QA-D4":
        if gold.expected_refusal is not True or gold.absence_reason is None or gold.answer_points:
            fail("D4_REFUSAL_INVALID", "gold.expected_refusal/absence_reason/answer_points")
    else:
        if gold.expected_refusal is not False or gold.absence_reason is not None:
            fail("ANSWERABLE_REFUSAL_INVALID", "gold.expected_refusal/absence_reason")
        if not gold.answer_points or not gold.gold_doc_ids:
            fail("QA_GOLD_EMPTY", "gold.answer_points/gold_doc_ids")
    if unit.dataset == "QA-D4C" and unit.original_question and unit.question.strip() == unit.original_question.strip():
        fail("D4C_QUESTION_REUSED", "question")
    if unit.dataset == "QA-D5" and not 3 <= len(unit.key_facts) <= 5:
        fail("D5_KEY_FACTS_REQUIRED", "key_facts")
    if unit.dataset == "QA-D3" and not 2 <= len(unit.reasoning_chain) <= 4:
        fail("D3_HOP_CHAIN_REQUIRED", "reasoning_chain")
    if unit.dataset == "QA-D7":
        _validate_d7(unit)


def _validate_extraction(unit: Unit, vocabulary: dict[str, Any] | None) -> None:
    text = unit.text if unit.text is not None else unit.chunk
    if not text or not unit.corpus_id or unit.schema_version != "1.0" or unit.gold is None:
        fail("D6_MATERIAL_REQUIRED", "text/corpus_id/schema_version/gold")
    if sha256(text.encode("utf-8")).hexdigest() != unit.text_digest:
        fail("D6_TEXT_DIGEST_INVALID", "text_digest")
    gold = unit.gold
    if gold.answer_points or gold.gold_doc_ids or gold.expected_refusal is not None:
        fail("D6_QA_FIELDS_FORBIDDEN", "gold")
    _validate_entities(text, gold.gold_entities, gold.gold_relations, vocabulary)


def _validate_entities(text: str, entities: list[Entity], relations: list[Relation], vocabulary: dict[str, Any] | None) -> None:
    ids: set[str] = set()
    for entity in entities:
        key = entity.entity_id or entity.name
        if key in ids:
            fail("D6_ENTITY_ID_DUPLICATE", "gold_entities.entity_id")
        ids.add(key)
        start, end = entity.span
        if not 0 <= start < end <= len(text) or text[start:end] != entity.name:
            fail("D6_SPAN_INVALID", "gold_entities.span")
        if vocabulary is not None and entity.type not in vocabulary.get("entity_types", []):
            fail("D6_ENTITY_TYPE_UNKNOWN", "gold_entities.type")
    for relation in relations:
        if relation.head not in ids or relation.tail not in ids:
            fail("D6_RELATION_DANGLING", "gold_relations.head/tail")
        if vocabulary is not None and relation.type not in vocabulary.get("relation_types", []):
            fail("D6_RELATION_TYPE_UNKNOWN", "gold_relations.type")


def _timestamp(value: str | None, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        fail("TIMESTAMP_INVALID", field)
    if result is None or result.tzinfo is None:
        fail("TIMESTAMP_INVALID", field)
    return result


def _validate_sec(unit: Unit, vocabulary: dict[str, Any] | None) -> None:
    if not unit.payload or not unit.expected_behavior:
        fail("SEC_MATERIAL_REQUIRED", "payload/expected_behavior")
    gold = unit.gold
    if gold is not None and (gold.answer_points or gold.relevance_grades or gold.ranking_annotations or gold.gold_entities or gold.gold_relations):
        fail("SEC_QA_FIELDS_FORBIDDEN", "gold")
    if unit.dataset == "SEC-D1":
        if not unit.acl_context or gold is None or not gold.gold_doc_ids:
            fail("SEC_ACL_REQUIRED", "acl_context/gold.gold_doc_ids")
    elif unit.dataset == "SEC-D2":
        effect = unit.expected_effect
        if effect is None or not unit.attack_type_detail:
            fail("SEC_EFFECT_REQUIRED", "expected_effect/attack_type_detail")
        field = {"marker": "marker_string", "target": "target_string", "behavior": "description"}[effect.kind]
        required = getattr(effect, field)
        if not isinstance(required, str) or not required.strip():
            fail("SEC_EFFECT_KIND_MISMATCH", "expected_effect." + field)
        if vocabulary is not None and unit.attack_type_detail not in vocabulary.get("attack_type_details", []):
            fail("SEC_ATTACK_TYPE_UNKNOWN", "attack_type_detail")
    elif unit.dataset == "SEC-D3":
        if not unit.target_claim or not unit.baseline_answer or unit.target_claim.strip() == unit.baseline_answer.strip():
            fail("SEC_POISON_CRITERIA_REQUIRED", "target_claim/baseline_answer")
        captured = _timestamp(unit.baseline_captured_at, "baseline_captured_at")
        current = datetime.now(UTC)
        if captured > current or current - captured > timedelta(days=30) or unit.baseline_unpoisoned is not True:
            fail("SEC_BASELINE_INVALID", "baseline_captured_at/baseline_unpoisoned")
        if unit.injection_started_at and captured >= _timestamp(unit.injection_started_at, "injection_started_at"):
            fail("SEC_BASELINE_AFTER_INJECTION", "baseline_captured_at")
        plan = unit.inject_plan or {}
        rollback = plan.get("rollback", {})
        if not plan.get("doc_id_hint") or not isinstance(rollback, dict) or type(rollback.get("residual")) is not int or rollback["residual"] != 0 or not rollback.get("evidence"):
            fail("SEC_ROLLBACK_EVIDENCE_REQUIRED", "inject_plan.rollback")
    elif unit.dataset == "SEC-D4":
        if not unit.member_doc_id or not unit.nonmember_doc_id or unit.member_doc_id == unit.nonmember_doc_id or not unit.pair_controls:
            fail("SEC_MIA_PAIR_REQUIRED", "member_doc_id/nonmember_doc_id/pair_controls")
    elif unit.dataset == "SEC-D5" and (unit.synthetic_pii is not True or not unit.synthetic_proof):
        fail("SEC_SYNTHETIC_PROOF_REQUIRED", "synthetic_pii/synthetic_proof")


def _validate_d7(unit: Unit) -> None:
    ids = unit.source_case_ids
    resolved = {source.get("unit_id"): source for source in unit.resolved_sources}
    confirmation = unit.same_intent_confirmation or {}
    if not ids or len(ids) != len(set(ids)) or set(ids) != set(resolved):
        fail("D7_SOURCE_UNRESOLVED", "source_case_ids/resolved_sources")
    if confirmation.get("confirmed") is not True or not confirmation.get("person_id") or not confirmation.get("reason"):
        fail("D7_SAME_INTENT_UNCONFIRMED", "same_intent_confirmation")
    ks: list[int] = []
    docs: set[str] = set()
    for source in resolved.values():
        if source.get("dataset") not in {"QA-D1", "QA-D2", "QA-D3"} or type(source.get("evaluation_k")) is not int or source["evaluation_k"] < 1:
            fail("D7_SOURCE_INVALID", "resolved_sources.dataset/evaluation_k")
        ks.append(source["evaluation_k"])
        source_gold = source.get("gold", {})
        grades = source_gold.get("relevance_grades", {})
        docs.update(doc for doc, grade in grades.items() if type(grade) is int and grade >= 2)
    if unit.evaluation_k != max(ks):
        fail("D7_K_NOT_SOURCE_MAX", "evaluation_k")
    assert unit.gold is not None
    if set(unit.gold.gold_doc_ids) != docs:
        fail("D7_EVIDENCE_UNION_INVALID", "gold.gold_doc_ids")


def validate_locator(unit: dict[str, Any], raw: dict[str, Any]) -> None:
    parsed = parse(LocatorV3, raw)
    assert isinstance(parsed, LocatorV3)
    document = next((doc for doc in unit.get("contexts", []) if doc["doc_id"] == parsed.doc_id), None)
    if document is None:
        fail("LOCATOR_DOCUMENT_UNKNOWN", "locator.doc_id")
    text = document["text"]
    if parsed.context_sha256 is not None and parsed.context_sha256 != sha256(text.encode("utf-8")).hexdigest():
        fail("LOCATOR_DIGEST_CONFLICT", "locator.context_sha256")
    if parsed.context_version is not None and parsed.context_version != document.get("version"):
        fail("LOCATOR_VERSION_CONFLICT", "locator.context_version")
    if parsed.start is not None or parsed.end is not None:
        if parsed.start is None or parsed.end is None or not 0 <= parsed.start < parsed.end <= len(text):
            fail("LOCATOR_OUT_OF_BOUNDS", "locator.start/end")
        if parsed.quote is not None and parsed.quote != text[parsed.start:parsed.end]:
            fail("LOCATOR_QUOTE_CONFLICT", "locator.quote")
    elif parsed.page is None and (parsed.span is None or not parsed.span.strip()):
        fail("LOCATOR_LOCATION_REQUIRED", "locator")
    if parsed.page is not None and parsed.page != document.get("page"):
        fail("LOCATOR_PAGE_CONFLICT", "locator.page")


def validate_review(unit: dict[str, Any], payload: dict[str, Any], vocabulary: dict[str, Any] | None = None) -> None:
    parsed = parse(ReviewV3, payload)
    assert isinstance(parsed, ReviewV3)
    qa = unit["dataset"].startswith("QA") and unit["dataset"] != "QA-D6"
    if qa:
        _validate_qa_review(unit, parsed)
    else:
        if parsed.point_labels or parsed.point_reasons or parsed.point_evidence or parsed.evidence_assessments or parsed.expected_refusal is not None:
            fail("SPECIALIZED_QA_FIELDS_FORBIDDEN", "review")
        if unit["dataset"] == "QA-D6":
            if parsed.extraction is None:
                fail("D6_EXTRACTION_REQUIRED", "extraction")
            text = unit.get("text") or unit.get("chunk") or ""
            _validate_entities(text, parsed.extraction.gold_entities, parsed.extraction.gold_relations, vocabulary)
            if vocabulary is None and parsed.verdict == "VERIFIED":
                fail("D6_VOCABULARY_UNCONFIRMED", "vocabulary")
        if unit["dataset"] == "SEC-D2" and vocabulary is None and parsed.verdict == "VERIFIED":
            fail("SEC_ATTACK_VOCABULARY_UNCONFIRMED", "vocabulary")
    if set(parsed.specialized_review) != set(SPECIALIZED_FIELDS.get(unit["dataset"], [])):
        fail("SPECIALIZED_REVIEW_REQUIRED", "specialized_review")
    for assessment in parsed.specialized_review.values():
        if not assessment.reason.strip():
            fail("SPECIALIZED_REASON_REQUIRED", "specialized_review.reason")
        for location in assessment.evidence:
            validate_locator(unit, location.model_dump(exclude_none=True))
    suggestion_ids: set[str] = set()
    for suggestion in parsed.suggested_points:
        if suggestion.suggestion_id in suggestion_ids:
            fail("SUGGESTION_ID_DUPLICATE", "suggested_points")
        suggestion_ids.add(suggestion.suggestion_id)
        for location in suggestion.evidence:
            validate_locator(unit, location.model_dump(exclude_none=True))
    change_ids: set[str] = set()
    for change in parsed.evidence_changes:
        if change.change_id in change_ids:
            fail("EVIDENCE_CHANGE_ID_DUPLICATE", "evidence_changes")
        change_ids.add(change.change_id)
        for location in change.locators:
            if location.doc_id != change.doc_id:
                fail("EVIDENCE_CHANGE_DOCUMENT_CONFLICT", "evidence_changes.locators")
            validate_locator(unit, location.model_dump(exclude_none=True))
    if parsed.verdict == "VERIFIED" and review_requires_revision(unit, payload):
        fail("VERIFIED_HAS_UNRESOLVED_FINDINGS", "verdict")


def review_requires_revision(unit: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Prevent a passed label from masking an unresolved content correction."""
    gold = unit.get("gold") or {}
    if payload.get("issues") or payload.get("suggested_points") or payload.get("evidence_changes"):
        return True
    if any(label != "correct" for label in payload.get("point_labels", {}).values()):
        return True
    original_grades = {**gold.get("relevance_grades", {}), **gold.get("ranking_annotations", {})}
    for doc_id, assessment in payload.get("evidence_assessments", {}).items():
        if assessment.get("intent") not in {"KEEP_GOLD", "KEEP_RANKING"} or assessment.get("grade") != original_grades.get(doc_id):
            return True
    qa = unit["dataset"].startswith("QA") and unit["dataset"] != "QA-D6"
    if qa and (payload.get("expected_refusal") != gold.get("expected_refusal") or payload.get("absence_reason") != gold.get("absence_reason")):
        return True
    if any(value.get("observation") != "pass" for value in payload.get("specialized_review", {}).values()):
        return True
    extraction = payload.get("extraction")
    return bool(extraction is not None and (extraction.get("gold_entities") != gold.get("gold_entities") or extraction.get("gold_relations") != gold.get("gold_relations")))


def _validate_qa_review(unit: dict[str, Any], review: ReviewV3) -> None:
    gold = unit.get("gold", {})
    keys = {f"P{index + 1:03d}" for index, _ in enumerate(gold.get("answer_points", []))}
    known_docs = {document["doc_id"] for document in unit.get("contexts", [])}
    for mapping in (review.point_labels, review.point_reasons, review.point_evidence):
        if set(mapping) != keys:
            fail("REVIEW_POINT_COVERAGE_INVALID", "point_labels/point_reasons/point_evidence")
    if not set(review.point_search_scope) <= keys:
        fail("REVIEW_POINT_SCOPE_INVALID", "point_search_scope")
    for key in keys:
        if not review.point_reasons[key].strip():
            fail("REVIEW_REASON_REQUIRED", "point_reasons")
        if not review.point_evidence[key]:
            scope = review.point_search_scope.get(key, [])
            if review.point_labels[key] != "wrong" or not scope or len(scope) != len(set(scope)) or not set(scope) <= known_docs:
                fail("REVIEW_SEARCH_SCOPE_REQUIRED", "point_search_scope")
        for location in review.point_evidence[key]:
            validate_locator(unit, location.model_dump(exclude_none=True))
    original_gold = set(gold.get("gold_doc_ids", []))
    original_ranking = set(gold.get("ranking_annotations", {}))
    if set(review.evidence_assessments) != original_gold | original_ranking:
        fail("REVIEW_EVIDENCE_COVERAGE_INVALID", "evidence_assessments")
    for doc_id, assessment in review.evidence_assessments.items():
        intent, grade = assessment.intent, assessment.grade
        allowed = {"KEEP_GOLD", "MOVE_TO_RANKING", "REMOVE"} if doc_id in original_gold else {"KEEP_RANKING", "MOVE_TO_GOLD", "REMOVE"}
        if intent not in allowed or intent in {"KEEP_GOLD", "MOVE_TO_GOLD"} and grade < 2 or intent in {"KEEP_RANKING", "MOVE_TO_RANKING"} and grade > 1:
            fail("REVIEW_EVIDENCE_INTENT_INVALID", "evidence_assessments.intent/grade")
        if not assessment.reason.strip() or (not assessment.locators and intent != "REMOVE"):
            fail("REVIEW_EVIDENCE_REASON_REQUIRED", "evidence_assessments.reason/locators")
        for location in assessment.locators:
            if location.doc_id != doc_id:
                fail("REVIEW_EVIDENCE_LOCATOR_CONFLICT", "evidence_assessments.locators")
            validate_locator(unit, location.model_dump(exclude_none=True))
    if review.expected_refusal is None or not review.expected_refusal_reason or not review.expected_refusal_reason.strip():
        fail("REVIEW_REFUSAL_REASON_REQUIRED", "expected_refusal/expected_refusal_reason")
    if review.expected_refusal and review.absence_reason is None or not review.expected_refusal and review.absence_reason is not None:
        fail("REVIEW_REFUSAL_INVALID", "expected_refusal/absence_reason")
    if unit["dataset"] == "QA-D4" and review.expected_refusal is not True or unit["dataset"] == "QA-D4C" and review.expected_refusal is not False:
        fail("REVIEW_DATASET_REFUSAL_INVALID", "expected_refusal")


def sample_units(units: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    """Per-dataset minimum, proportional largest remainders, stable sorted seed."""
    if type(seed) is not int or len({unit["unit_id"] for unit in units}) != len(units):
        fail("SAMPLING_INPUT_INVALID", "seed/unit_id")
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for unit in units:
        if unit.get("dataset") not in QUOTAS or unit.get("difficulty") not in {"easy", "medium", "hard"}:
            fail("SAMPLING_INPUT_INVALID", "dataset/difficulty")
        grouped[unit["dataset"]][unit["difficulty"]].append(unit["unit_id"])
    selected: list[str] = []
    strata: list[dict[str, Any]] = []
    required_total = 0
    for dataset in sorted(grouped):
        groups = grouped[dataset]
        count = sum(len(items) for items in groups.values())
        required = max(8, ceil(Fraction(count, 10)))
        target = min(required, count)
        required_total += required
        allocations = {difficulty: target * len(ids) // count for difficulty, ids in groups.items()}
        rest = target - sum(allocations.values())
        order = sorted(groups, key=lambda difficulty: (-Fraction(target * len(groups[difficulty]) % count, count), difficulty))
        for difficulty in order[:rest]:
            allocations[difficulty] += 1
        for difficulty in sorted(groups):
            random = Random(f"v13-stratified-largest-remainder.v1:{seed}:{dataset}:{difficulty}")
            chosen = sorted(random.sample(sorted(groups[difficulty]), allocations[difficulty]))
            selected.extend(chosen)
            strata.append({"dataset": dataset, "difficulty": difficulty, "population": len(groups[difficulty]),
                           "sample_count": len(chosen), "selected_ids": chosen})
    return {"algorithm_version": "v13-stratified-largest-remainder.v1", "seed": seed,
            "selected_ids": selected, "population_count": len(units), "required_count": required_total,
            "actual_count": len(selected), "shortfall": required_total - len(selected), "strata": strata}


def observation_result(left: list[str], right: list[str]) -> dict[str, Any]:
    """Exact nominal kappa of frozen original point labels; never a READY gate."""
    labels = {"correct", "partial", "wrong"}
    if any(not isinstance(value, list) for value in (left, right)) or any(not isinstance(label, str) or label not in labels for label in (*left, *right)):
        fail("INVALID_POINT_VECTOR", "observation.labels")
    result: dict[str, Any] = {"kappa": None, "po": None, "pe": None, "n": len(left),
                              "action": "UNDEFINED", "reason": None, "algorithm_version": "cohen-original-points.v13"}
    if len(left) != len(right):
        result["reason"] = "MISSING_LABEL_PAIRS"
        return result
    if not left:
        result["reason"] = "EMPTY_LABEL_VECTOR"
        return result
    count = len(left)
    counts_a, counts_b = Counter(left), Counter(right)
    po = Fraction(sum(a == b for a, b in zip(left, right, strict=True)), count)
    pe = sum((Fraction(counts_a[label] * counts_b[label], count * count) for label in labels), Fraction())
    result.update(po=float(po), pe=float(pe))
    if pe == 1:
        result["reason"] = "UNDEFINED_KAPPA_PE_ONE"
        return result
    kappa = (po - pe) / (1 - pe)
    result.update(kappa=float(kappa), action="NORMAL" if kappa >= Fraction(7, 10) else "EXPAND_CALIBRATE" if kappa >= Fraction(3, 5) else "RETURN_TO_S2")
    return result


def batch_constraints(envelope: dict[str, Any]) -> dict[str, Any]:
    units = envelope.get("units", [])
    counts = Counter(unit["dataset"] for unit in units)
    blocked: list[str] = []
    d4 = [unit for unit in units if unit["dataset"] == "QA-D4"]
    d4c = [unit for unit in units if unit["dataset"] == "QA-D4C"]
    pair: dict[str, Any] = {"d4_count": len(d4), "d4c_count": len(d4c), "metrics_status": "NOT_APPLICABLE"}
    if d4 or d4c:
        if not d4 or not d4c:
            pair["metrics_status"] = "N/A"
            blocked.append("D4_PAIR_MISSING_SIDE")
        else:
            pair["metrics_status"] = "PAIRED"
            difference = Fraction(abs(len(d4) - len(d4c)), max(len(d4), len(d4c)))
            pair["size_difference"] = float(difference)
            if difference > Fraction(1, 5):
                blocked.append("D4_PAIR_SIZE_DIFFERENCE")
            def strata(records: list[dict[str, Any]]) -> set[tuple[str, str]]:
                return {(str(record.get("domain") or record.get("metadata", {}).get("domain") or ""), record["difficulty"]) for record in records}
            if strata(d4) != strata(d4c) or any(not domain for domain, _ in strata(d4)):
                blocked.append("D4_PAIR_STRATA_MISMATCH")
    tops = {unit.get("top_n", 10) for unit in units if unit["dataset"] == "SEC-D4"}
    if len(tops) > 1:
        blocked.append("SEC_D4_TOP_N_INCONSISTENT")
    d7 = [unit for unit in units if unit["dataset"] == "QA-D7"]
    if len(d7) == QUOTAS["QA-D7"]:
        composition = Counter(unit.get("source_dataset") for unit in d7)
        if composition != {"QA-D1": 125, "QA-D2": 50, "QA-D3": 25}:
            blocked.append("D7_COMPOSITION_MISMATCH")
    return {"dataset_counts": dict(counts), "d4_pairing": pair, "blocked_reasons": blocked,
            "quotas": deepcopy(QUOTAS), "total_target": 2300}


def source_blockers(envelope: dict[str, Any]) -> list[str]:
    reasons = list(batch_constraints(envelope)["blocked_reasons"])
    datasets = {unit["dataset"] for unit in envelope.get("units", [])}
    if "QA-D6" in datasets:
        reasons.append("D6_VOCABULARY_UNCONFIRMED")
    if "SEC-D2" in datasets:
        reasons.append("SEC_ATTACK_VOCABULARY_UNCONFIRMED")
    if datasets & {"QA-D4", "QA-D6", "SEC-D1", "SEC-D2", "SEC-D3", "SEC-D4", "SEC-D5"}:
        reasons.append("SPECIALIZED_STATISTICS_UNCONFIRMED")
    if envelope.get("mode") == "formal":
        reasons.extend(["S3_S5_PROTOCOL_NOT_ALIGNED", "J1_C1_POLICY_CONFIRMATION_PENDING", "MAIN_REPOSITORY_MAPPING_PENDING"])
    return sorted(set(reasons))


def membership_rank(retrieved: list[dict[str, Any]], doc_id: str, top_n: int = 10) -> int:
    """The protocol guarantees ordering, not comparable retrieval scores."""
    if type(top_n) is not int or top_n < 1:
        fail("TOP_N_INVALID", "top_n")
    return next((index + 1 for index, document in enumerate(retrieved[:top_n]) if document.get("doc_id") == doc_id), top_n + 1)
