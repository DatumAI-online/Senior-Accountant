import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ExceptionSeverity, ExceptionStatus, ExceptionType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class ExceptionRecord(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Named ExceptionRecord (not Exception) to avoid shadowing the Python
    builtin. Maps to the taxonomy in DATUM_AI_BOOKKEEPING_TEAM_PLAN.md
    Section 12 — every row here is produced by a deterministic rule or a
    confidence-score threshold, never an unexplained model judgment."""

    __tablename__ = "exception_records"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_periods.id"), nullable=True
    )
    related_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposed_journal_entries.id"), nullable=True
    )
    type: Mapped[ExceptionType] = mapped_column(pg_enum(ExceptionType, "exception_type"), nullable=False)
    severity: Mapped[ExceptionSeverity] = mapped_column(
        pg_enum(ExceptionSeverity, "exception_severity"), nullable=False
    )
    status: Mapped[ExceptionStatus] = mapped_column(
        pg_enum(ExceptionStatus, "exception_status"), default=ExceptionStatus.OPEN, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_by: Mapped[str] = mapped_column(String(64), nullable=False)  # agent_type or "rule:<name>"
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
