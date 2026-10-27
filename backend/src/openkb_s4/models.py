"""Transactional S4 operational records, separate from evaluated knowledge stores."""
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Record(Base):
    __abstract__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Record):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    person_id: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    roles: Mapped[list[str]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(Record):
    __tablename__ = "sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    csrf_token: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginRate(Base):
    __tablename__ = "login_rates"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SourceImport(Record):
    __tablename__ = "source_imports"
    batch_id: Mapped[str] = mapped_column(String(160))
    source_revision: Mapped[str] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30), default="VALIDATED")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    blocked_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("batch_id", "source_revision"),)


class AnnotationBatch(Record):
    __tablename__ = "annotation_batches"
    import_id: Mapped[str] = mapped_column(ForeignKey("source_imports.id"), index=True)
    dataset: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(30), default="BLIND_OPEN")
    round: Mapped[int] = mapped_column(Integer, default=1)
    annotator_a: Mapped[str] = mapped_column(ForeignKey("users.id"))
    annotator_b: Mapped[str] = mapped_column(ForeignKey("users.id"))
    profile_version: Mapped[str] = mapped_column(String(80))
    selected_ids: Mapped[list[str]] = mapped_column(JSON)
    sample_ledger: Mapped[dict[str, Any]] = mapped_column(JSON)
    blocked_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    seed: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("annotation_batches.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("annotator_a <> annotator_b", name="different_annotators"),)


class Assignment(Record):
    __tablename__ = "assignments"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"), index=True)
    unit_id: Mapped[str] = mapped_column(String(160))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    seat: Mapped[str] = mapped_column(String(1))
    content_revision: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("batch_id", "unit_id", "seat"),)


class WorkingDraft(Record):
    __tablename__ = "working_drafts"
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"))
    phase: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("assignment_id", "phase"),)


class Submission(Record):
    __tablename__ = "submissions"
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), index=True)
    phase: Mapped[str] = mapped_column(String(10))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    __table_args__ = (UniqueConstraint("assignment_id", "phase"),)


class Agreement(Record):
    __tablename__ = "agreements"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"), unique=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))
    vectors: Mapped[dict[str, Any]] = mapped_column(JSON)


class Arbitration(Record):
    __tablename__ = "arbitrations"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"), index=True)
    unit_id: Mapped[str] = mapped_column(String(160))
    arbitrator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    final_gold: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    confirmation_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("batch_id", "unit_id"),)


class FinalDecision(Record):
    __tablename__ = "final_decisions"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"))
    unit_id: Mapped[str] = mapped_column(String(160))
    final_gold: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("batch_id", "unit_id"),)


class Exposure(Record):
    __tablename__ = "exposures"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    unit_id: Mapped[str] = mapped_column(String(160), index=True)
    family_keys: Mapped[list[str]] = mapped_column(JSON)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("annotation_batches.id"))
    reason: Mapped[str] = mapped_column(String(100))


class Job(Record):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(30))
    business_key: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class Handoff(Record):
    __tablename__ = "handoffs"
    import_id: Mapped[str] = mapped_column(ForeignKey("source_imports.id"))
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    blocked_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    external_status: Mapped[str] = mapped_column(String(30), default="NOT_ALIGNED")
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True)
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class AuditEvent(Record):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str | None] = mapped_column(String(160))
    request_id: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
