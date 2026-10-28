"""Narrow mutation schemas; unknown keys cannot add identity or role claims."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Grade = Annotated[int, Field(strict=True, ge=0, le=2)]

Role = Literal["admin", "lead", "annotator", "arbitrator", "auditor", "verifier"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class UserCreate(Login):
    display_name: str = Field(min_length=1, max_length=100)
    person_id: str = Field(min_length=1, max_length=100)
    roles: list[Role] = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("密码至少12位")
        return value


class UserUpdate(StrictModel):
    active: bool | None = None
    roles: list[Role] | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=12, max_length=200)


class BatchCreate(StrictModel):
    profile_revision_id: str | None = None
    due_at: datetime | None = None
    reminder_interval_minutes: int = Field(default=60, ge=1, le=10080)
    import_id: str
    dataset: str
    annotator_a: str
    annotator_b: str
    seed: int = Field(ge=0, le=2_147_483_647)


class DraftInput(StrictModel):
    phase: Literal["BLIND", "REVIEW"]
    version: int = Field(ge=0)
    payload: dict[str, Any]


class SubmitInput(StrictModel):
    profile_hash: str | None = None
    phase: Literal["BLIND", "REVIEW"]
    content_revision: str
    profile_version: str
    payload: dict[str, Any]


class Decision(StrictModel):
    unit_id: str
    final_gold: dict[str, Any]
    reason: str = Field(min_length=1, max_length=5000)


class FinalizeInput(StrictModel):
    decisions: list[Decision] = Field(min_length=1, max_length=5000)


class ArbitrationInput(Decision):
    batch_id: str


class ReasonInput(StrictModel):
    reason: str = Field(min_length=1, max_length=5000)


class RoundInput(ReasonInput):
    source_import_id: str | None = None
    calibration_id: str | None = None
    manual_version: str | None = None
    profile_revision_id: str | None = None
    batch_id: str
    annotator_a: str
    annotator_b: str
    seed: int = Field(ge=0, le=2_147_483_647)


class HandoffInput(StrictModel):
    import_id: str


class ReceiptInput(ReasonInput):
    status: Literal["S5_ACCEPTED", "S5_REJECTED"]
    snapshot_hash: str
    contract_version: Literal["openkb.s4-s5.v1"]


class Locator(StrictModel):
    doc_id: str = Field(min_length=1, max_length=160)
    context_version: str | None = None
    context_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    start: int | None = Field(default=None, strict=True, ge=0)
    end: int | None = Field(default=None, strict=True, ge=1)
    page: int | None = Field(default=None, strict=True, ge=1)
    span: str | None = Field(default=None, min_length=1, max_length=30000)


class SuggestedPoint(StrictModel):
    suggestion_id: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=30000)
    reason: str = Field(min_length=1, max_length=5000)
    evidence: list[Locator] = Field(min_length=1, max_length=200)


class EvidenceChange(StrictModel):
    change_id: str = Field(min_length=1, max_length=160)
    action: Literal["add", "remove"]
    doc_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=5000)
    locators: list[Locator] = Field(min_length=1, max_length=200)


class ReviewV2(StrictModel):
    review_version: Literal["openkb.s4-review.v2"]
    point_labels: dict[str, Literal["correct", "partial", "wrong"]] = Field(default_factory=dict)
    point_reasons: dict[str, Nonblank] = Field(default_factory=dict)
    point_evidence: dict[str, list[Locator]] = Field(default_factory=dict)
    point_search_scope: dict[str, list[str]] = Field(default_factory=dict)
    evidence_labels: dict[str, Grade] = Field(default_factory=dict)
    evidence_reasons: dict[str, Nonblank] = Field(default_factory=dict)
    answerable: Literal["answerable", "no_answer", "expired", "out_of_scope"] | None = None
    answerable_reason: Nonblank | None = None
    reason: str = Field(min_length=1, max_length=5000)
    suggested_points: list[SuggestedPoint] = Field(default_factory=list, max_length=200)
    evidence_changes: list[EvidenceChange] = Field(default_factory=list, max_length=200)
    specialized_review: dict[str, Any] | None = None


class VersionReason(ReasonInput):
    version: int = Field(ge=1)


class SeatReplace(VersionReason):
    seat: Literal["A", "B"]
    new_annotator_id: str


class IssueInput(ReasonInput):
    assignment_id: str
    issue_type: Literal[
        "MISSING_SOURCE",
        "INVALID_LOCATOR",
        "VERSION_CONFLICT",
        "EARLY_EXPOSURE",
        "INSUFFICIENT_SCOPE",
        "OTHER",
    ]
    locators: list[Locator] = Field(default_factory=list)


class ResolveIssue(VersionReason):
    disposition: Literal["UNCHANGED", "NEW_REVISION"]
    revision_ref: str | None = None


class ProfileInput(StrictModel):
    dataset: str
    version: str = Field(min_length=1, max_length=80)
    manual_version: str = Field(min_length=1, max_length=80)
    snapshot: dict[str, Any]
    reason: str = Field(min_length=1, max_length=5000)


class ProfileReview(VersionReason):
    evidence: dict[str, Any] = Field(default_factory=dict)


class CalibrationInput(ReasonInput):
    batch_id: str
    meeting_at: datetime
    participant_ids: list[str] = Field(min_length=1)
    case_refs: list[str] = Field(min_length=1)
    decisions: str = Field(min_length=1)
    manual_version: str = Field(min_length=1, max_length=80)
    training_refs: list[str] = Field(min_length=1)


class QualificationInput(ReasonInput):
    user_id: str
    dataset: str
    available: bool = True
    valid_until: datetime
    evidence: dict[str, Any]


class ValidationInput(ReasonInput):
    batch_id: str
    unit_id: str
    final_gold: dict[str, Any]
    content_hash: str = Field(pattern="^[0-9a-f]{64}$")
    profile_hash: str = Field(pattern="^[0-9a-f]{64}$")
    evidence: dict[str, Any]


class ValidationCandidateInput(Decision):
    batch_id: str
    verifier_id: str


class ImportUpload(StrictModel):
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.jsonl$")
    units_jsonl: str = Field(min_length=1, max_length=20000000)
    envelope: dict[str, Any]
    source_index: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ProfilePatch(ProfileInput):
    expected_revision: int = Field(ge=1)
