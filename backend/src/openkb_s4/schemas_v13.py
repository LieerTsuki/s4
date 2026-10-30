"""Versioned HTTP request shapes, independent from historical REVIEW v2."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationBatchCreate(StrictModel):
    import_id: str
    dataset: str
    assignee_ids: list[str] = Field(min_length=1)
    manual_version: str = Field(default="manual-v1.3", min_length=1, max_length=100)
    profile_version: str = Field(default="s4-v1.3", min_length=1, max_length=100)


class ObservationBatchCreate(StrictModel):
    import_id: str
    dataset: str
    annotator_a: str
    annotator_b: str
    seed: int = 42
    manual_version: str = Field(default="manual-v1.3", min_length=1, max_length=100)
    profile_version: str = Field(default="s4-v1.3", min_length=1, max_length=100)
    parent_id: str | None = None
    expanded_count: int | None = Field(default=None, ge=1)


class DraftInput(StrictModel):
    phase: Literal["BLIND", "REVIEW"]
    version: int = Field(ge=0)
    payload: dict[str, Any]


class SubmitInput(StrictModel):
    phase: Literal["BLIND", "REVIEW"]
    content_revision: str
    profile_version: str = "s4-v1.3"
    payload: dict[str, Any]


class QualityActionCreate(StrictModel):
    batch_id: str
    kind: Literal["CALIBRATION", "EXPAND", "RETURN_TO_S2", "S2_ACK", "DISAGREEMENT_REVIEW"]
    reason: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    related_batch_id: str | None = None


class ReplacementInput(StrictModel):
    user_id: str
    reason: str = Field(min_length=1)
    seat: Literal["V", "A", "B"] | None = None


class NewRoundInput(StrictModel):
    reason: str = Field(min_length=1)
    assignee_ids: list[str] = Field(default_factory=list)
    annotator_a: str | None = None
    annotator_b: str | None = None


class IssueCreate(StrictModel):
    unit_index_id: str
    reason: str = Field(min_length=1)


class IssueResolve(StrictModel):
    reason: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class RevisionCreate(StrictModel):
    unit_index_id: str
    verifier_id: str
    candidate: dict[str, Any]
    reason: str = Field(min_length=1)


class RevisionVerify(StrictModel):
    outcome: Literal["PASS", "FAIL"]
    reason: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(min_length=1)
