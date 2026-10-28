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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
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
    review_version: Mapped[str] = mapped_column(String(40), default="openkb.s4-review.v1", server_default="openkb.s4-review.v1")
    profile_revision_id: Mapped[str | None] = mapped_column(ForeignKey("profile_revisions.id"))
    profile_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    profile_hash: Mapped[str | None] = mapped_column(String(64))
    manual_version: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    resume_state: Mapped[str | None] = mapped_column(String(30))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_interval_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    calibration_id: Mapped[str | None] = mapped_column(ForeignKey("calibration_records.id"))
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
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    replacement_id: Mapped[str | None] = mapped_column(ForeignKey("seat_replacements.id"))
    replaced_by_id: Mapped[str | None] = mapped_column(ForeignKey("assignments.id"))
    unit_revision_id: Mapped[str | None] = mapped_column(ForeignKey("unit_revisions.id"))
    gold_revision_id: Mapped[str | None] = mapped_column(ForeignKey("gold_revisions.id"))
    content_revision: Mapped[str] = mapped_column(String(64))
    __table_args__ = (Index("uq_assignment_active_seat", "batch_id", "unit_id", "seat", unique=True, postgresql_where=text("active")),)


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
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class ProfileRevision(Record):
    __tablename__ = "profile_revisions"
    dataset: Mapped[str] = mapped_column(String(20))
    version: Mapped[str] = mapped_column(String(80))
    manual_version: Mapped[str] = mapped_column(String(80))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    canonical_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="DRAFT")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    creator_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approver_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approval: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("dataset", "version"),)


class UnitRevision(Record):
    __tablename__ = "unit_revisions"
    import_id: Mapped[str] = mapped_column(ForeignKey("source_imports.id"))
    unit_id: Mapped[str] = mapped_column(String(160))
    material: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("import_id", "unit_id"),)


class GoldRevision(Record):
    __tablename__ = "gold_revisions"
    unit_revision_id: Mapped[str] = mapped_column(ForeignKey("unit_revisions.id"), unique=True)
    gold: Mapped[dict[str, Any]] = mapped_column(JSON)
    review_material: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))


class SeatReplacement(Record):
    __tablename__ = "seat_replacements"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"))
    seat: Mapped[str] = mapped_column(String(1))
    old_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    new_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)


class LateSubmission(Record):
    __tablename__ = "late_submissions"
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"))
    phase: Mapped[str] = mapped_column(String(10))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="INVALID_LATE")
    __table_args__ = (UniqueConstraint("assignment_id", "idempotency_key"),)


class WorkIssue(Record):
    __tablename__ = "work_issues"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"))
    unit_id: Mapped[str] = mapped_column(String(160))
    issue_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    locators: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    resolver_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    revision_ref: Mapped[str | None] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer, default=1)


class CalibrationRecord(Record):
    __tablename__ = "calibration_records"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"))
    original_agreement: Mapped[dict[str, Any]] = mapped_column(JSON)
    meeting_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    participant_ids: Mapped[list[str]] = mapped_column(JSON)
    case_refs: Mapped[list[str]] = mapped_column(JSON)
    decisions: Mapped[str] = mapped_column(Text)
    manual_version: Mapped[str] = mapped_column(String(80))
    training_refs: Mapped[list[str]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Qualification(Record):
    __tablename__ = "qualifications"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    dataset: Mapped[str] = mapped_column(String(20))
    available: Mapped[bool] = mapped_column(Boolean)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    approver_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ValidationRevision(Record):
    __tablename__ = "validation_revisions"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"))
    unit_id: Mapped[str] = mapped_column(String(160))
    content_hash: Mapped[str] = mapped_column(String(64))
    profile_hash: Mapped[str] = mapped_column(String(64))
    final_gold: Mapped[dict[str, Any]] = mapped_column(JSON)
    validation_revision: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20))
    change_kind: Mapped[str] = mapped_column(String(30))
    editor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    verifier_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("batch_id", "unit_id", "content_hash", "validation_revision"),)


class ChangeEvent(Record):
    __tablename__ = "change_events"
    batch_id: Mapped[str] = mapped_column(ForeignKey("annotation_batches.id"))
    change_type: Mapped[str] = mapped_column(String(40))
    revision_ref: Mapped[str] = mapped_column(String(160))
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    next_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)


class ReconciliationRun(Record):
    __tablename__ = "reconciliation_runs"
    state: Mapped[str] = mapped_column(String(20))
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creator_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ReconciliationFinding(Record):
    __tablename__ = "reconciliation_findings"
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"))
    kind: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str] = mapped_column(String(160))
    severity: Mapped[str] = mapped_column(String(20))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")


class Notification(Record):
    __tablename__ = "notifications"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    business_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HandoffSent(Record):
    __tablename__ = "handoff_sent"
    handoff_id: Mapped[str] = mapped_column(ForeignKey("handoffs.id"))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    destination_ref: Mapped[str] = mapped_column(String(160))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    mode: Mapped[str] = mapped_column(String(10))
