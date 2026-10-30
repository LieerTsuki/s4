"""v1.3 operational indexes. Sensitive content exists only in verified object files."""

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Record


class V13Import(Record):
    __tablename__ = "v13_imports"
    batch_id: Mapped[str] = mapped_column(String(160))
    source_revision: Mapped[str] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(10))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(40), default="WAITING_VERIFICATION")
    blockers: Mapped[list[str]] = mapped_column(JSON, default=list)
    parent_import_id: Mapped[str | None] = mapped_column(ForeignKey("v13_imports.id"))
    __table_args__ = (UniqueConstraint("batch_id", "source_revision"),)


class V13Unit(Record):
    __tablename__ = "v13_units"
    import_id: Mapped[str] = mapped_column(ForeignKey("v13_imports.id"), index=True)
    unit_id: Mapped[str] = mapped_column(String(160))
    dataset: Mapped[str] = mapped_column(String(20))
    difficulty: Mapped[str] = mapped_column(String(10))
    content_revision: Mapped[str] = mapped_column(String(64))
    material_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    gold_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    family_keys: Mapped[list[str]] = mapped_column(JSON)
    final_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    final_revision: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("import_id", "unit_id"),)


class V13Batch(Record):
    __tablename__ = "v13_batches"
    import_id: Mapped[str] = mapped_column(ForeignKey("v13_imports.id"), index=True)
    dataset: Mapped[str] = mapped_column(String(20))
    workflow_kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(40), default="BLIND_OPEN")
    round: Mapped[int] = mapped_column(Integer, default=1)
    selected_ids: Mapped[list[str]] = mapped_column(JSON)
    sample_ledger: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    profile_version: Mapped[str] = mapped_column(String(100))
    manual_version: Mapped[str] = mapped_column(String(100))
    frozen_hash: Mapped[str] = mapped_column(String(64))
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    quality_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("v13_batches.id"))
    __table_args__ = (UniqueConstraint("import_id", "dataset", "workflow_kind", "round"),)


class V13Assignment(Record):
    __tablename__ = "v13_assignments"
    batch_id: Mapped[str] = mapped_column(ForeignKey("v13_batches.id"), index=True)
    unit_index_id: Mapped[str] = mapped_column(ForeignKey("v13_units.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    seat: Mapped[str] = mapped_column(String(1))
    phase: Mapped[str] = mapped_column(String(10), default="BLIND")
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    content_revision: Mapped[str] = mapped_column(String(64))
    material_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    gold_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (Index("uq_v13_assignment_active_seat", "batch_id", "unit_index_id", "seat", unique=True, postgresql_where=text("active")),)


class V13Draft(Record):
    __tablename__ = "v13_drafts"
    assignment_id: Mapped[str] = mapped_column(ForeignKey("v13_assignments.id"))
    phase: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("assignment_id", "phase"),)


class V13Submission(Record):
    __tablename__ = "v13_submissions"
    assignment_id: Mapped[str] = mapped_column(ForeignKey("v13_assignments.id"), index=True)
    phase: Mapped[str] = mapped_column(String(10))
    payload_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    __table_args__ = (UniqueConstraint("assignment_id", "phase"),)


class V13LateSubmission(Record):
    __tablename__ = "v13_late_submissions"
    assignment_id: Mapped[str] = mapped_column(ForeignKey("v13_assignments.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    payload_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    __table_args__ = (UniqueConstraint("assignment_id", "idempotency_key"),)


class V13Exposure(Record):
    __tablename__ = "v13_exposures"
    person_id: Mapped[str] = mapped_column(String(100), index=True)
    family_key: Mapped[str] = mapped_column(String(160), index=True)
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("v13_assignments.id"))
    reason: Mapped[str] = mapped_column(String(80))


class V13Verification(Record):
    __tablename__ = "v13_verifications"
    import_id: Mapped[str] = mapped_column(ForeignKey("v13_imports.id"), index=True)
    unit_index_id: Mapped[str] = mapped_column(ForeignKey("v13_units.id"))
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("v13_assignments.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    content_revision: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(30))
    record_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("assignment_id", "content_revision",
                                      name="uq_v13_verification_assignment_revision"),)


class V13QualityAction(Record):
    __tablename__ = "v13_quality_actions"
    batch_id: Mapped[str] = mapped_column(ForeignKey("v13_batches.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    record_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    related_batch_id: Mapped[str | None] = mapped_column(ForeignKey("v13_batches.id"))


class V13Issue(Record):
    __tablename__ = "v13_issues"
    import_id: Mapped[str] = mapped_column(ForeignKey("v13_imports.id"), index=True)
    unit_index_id: Mapped[str] = mapped_column(ForeignKey("v13_units.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    record_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    resolution_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resolver_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class V13Revision(Record):
    __tablename__ = "v13_revisions"
    unit_index_id: Mapped[str] = mapped_column(ForeignKey("v13_units.id"), index=True)
    proposer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    verifier_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    candidate_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    record_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    verification_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source_revision: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
