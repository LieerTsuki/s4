"""Frozen Unicode source locations and finite structured review validation."""

from typing import Any, NoReturn

from pydantic import ValidationError

from ..schemas import Locator, ReviewV2
from ..security import ApiError


def reject(path: str, code: str = "REVIEW_INVALID") -> NoReturn:
    raise ApiError(422, code, f"字段无效或缺少逐项依据：{path}")


def validate_locator(unit: dict[str, Any], locator: dict[str, Any], path: str = "locator") -> None:
    try:
        value = Locator.model_validate(locator)
    except ValidationError as exc:
        reject(path + "." + ".".join(str(part) for part in exc.errors()[0]["loc"]))
    doc = next((d for d in unit.get("contexts", []) if d["doc_id"] == value.doc_id), None)
    if doc is None:
        reject(path + ".doc_id", "LOCATOR_DOCUMENT_UNKNOWN")
    if value.context_version is not None and value.context_version != doc.get("version"):
        reject(path + ".context_version", "LOCATOR_VERSION_CONFLICT")
    if value.context_sha256 is not None:
        from hashlib import sha256

        if value.context_sha256 != sha256(doc["text"].encode("utf-8")).hexdigest():
            reject(path + ".context_sha256", "LOCATOR_DIGEST_CONFLICT")
    if value.start is not None or value.end is not None:
        if (
            value.start is None
            or value.end is None
            or not 0 <= value.start < value.end <= len(doc["text"])
        ):
            reject(path + ".start/end", "LOCATOR_OUT_OF_BOUNDS")
    elif value.page is None and value.span is None:
        reject(path, "LOCATOR_LOCATION_REQUIRED")
    if value.page is not None and doc.get("page") is not None and value.page != doc["page"]:
        reject(path + ".page", "LOCATOR_PAGE_CONFLICT")
    if value.span is not None and not value.span.strip():
        reject(path + ".span")


def validate_review_v2(unit: dict[str, Any], payload: dict[str, Any]) -> None:
    try:
        review = ReviewV2.model_validate(payload, strict=True)
    except ValidationError as exc:
        reject(".".join(str(part) for part in exc.errors()[0]["loc"]))
    qa = unit["dataset"].startswith("QA") and unit["dataset"] != "QA-D6"
    expected = {
        f"P{i + 1:03d}" for i, _ in enumerate(unit.get("gold", {}).get("answer_points", []))
    }
    docs = set(unit.get("gold", {}).get("gold_doc_ids", []))
    if qa:
        for field in ("point_reasons", "point_evidence", "point_labels"):
            if set(getattr(review, field)) != expected:
                reject(field)
        if not set(review.point_search_scope) <= expected:
            reject("point_search_scope")
        for point in expected:
            if not review.point_reasons[point].strip():
                reject("point_reasons/point_evidence." + point)
            if not review.point_evidence[point]:
                scope = review.point_search_scope.get(point)
                known = {doc["doc_id"] for doc in unit.get("contexts", [])}
                if (
                    review.point_labels[point] != "wrong"
                    or not scope
                    or len(scope) != len(set(scope))
                    or not set(scope) <= known
                ):
                    reject("point_search_scope." + point)
            for index, location in enumerate(review.point_evidence[point]):
                validate_locator(
                    unit, location.model_dump(exclude_none=True), f"point_evidence.{point}.{index}"
                )
        if set(review.evidence_reasons) != docs or any(
            not reason.strip() for reason in review.evidence_reasons.values()
        ):
            reject("evidence_reasons")
        if not review.answerable_reason or not review.answerable_reason.strip():
            reject("answerable_reason")
    elif (
        review.point_reasons
        or review.point_evidence
        or review.evidence_reasons
        or review.suggested_points
        or review.evidence_changes
    ):
        reject("specialized_review")
    from .profiles import specialized_fields

    if specialized_fields(unit["dataset"]):
        validate_specialized(unit, review.specialized_review, True)
    ids: set[str] = set()
    for index, suggestion in enumerate(review.suggested_points):
        if (
            suggestion.suggestion_id in ids
            or not suggestion.text.strip()
            or not suggestion.reason.strip()
        ):
            reject(f"suggested_points.{index}")
        ids.add(suggestion.suggestion_id)
        for location in suggestion.evidence:
            validate_locator(
                unit, location.model_dump(exclude_none=True), f"suggested_points.{index}.evidence"
            )
    ids = set()
    for index, change in enumerate(review.evidence_changes):
        if change.change_id in ids or not change.reason.strip():
            reject(f"evidence_changes.{index}")
        ids.add(change.change_id)
        if change.action == "remove" and change.doc_id not in docs:
            reject(f"evidence_changes.{index}.doc_id")
        if change.action == "add" and change.doc_id in docs:
            reject(f"evidence_changes.{index}.doc_id")
        for location in change.locators:
            if location.doc_id != change.doc_id:
                reject(f"evidence_changes.{index}.locators.doc_id")
            validate_locator(
                unit, location.model_dump(exclude_none=True), f"evidence_changes.{index}.locators"
            )


def validate_specialized(unit: dict[str, Any], value: object, strict: bool) -> None:
    if not isinstance(value, dict) or not value:
        reject("specialized_review", "SPECIALIZED_REVIEW_REQUIRED")
    if not strict:
        return
    from .profiles import specialized_fields

    expected = set(specialized_fields(unit["dataset"]))
    if set(value) != expected:
        reject("specialized_review")
    for name, observation in value.items():
        if not isinstance(observation, dict) or set(observation) != {
            "observation",
            "reason",
            "evidence",
        }:
            reject("specialized_review." + name)
        if any(
            not isinstance(observation.get(key), str) or not observation[key].strip()
            for key in ("observation", "reason")
        ):
            reject("specialized_review." + name)
        evidence = observation["evidence"]
        if not isinstance(evidence, list) or not evidence:
            reject("specialized_review." + name + ".evidence")
        for location in evidence:
            validate_locator(unit, location, "specialized_review." + name + ".evidence")
