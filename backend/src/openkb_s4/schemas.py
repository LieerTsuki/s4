"""Narrow mutation schemas; unknown keys cannot add identity or role claims."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["admin", "lead", "annotator", "arbitrator", "auditor"]


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
