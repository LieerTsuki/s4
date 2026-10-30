"""Index-only state for immutable process packages and real receipt evidence."""
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Record


class V13Handoff(Record):
    __tablename__ = "v13_handoffs"
    import_id: Mapped[str] = mapped_column(ForeignKey("v13_imports.id"), index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="EXPORTED_DEMO")
    manifest_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("import_id", "snapshot_hash"),)


class V13Delivery(Record):
    __tablename__ = "v13_deliveries"
    handoff_id: Mapped[str] = mapped_column(ForeignKey("v13_handoffs.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    payload_hash: Mapped[str] = mapped_column(String(64))
    evidence_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("handoff_id", "idempotency_key"),)
