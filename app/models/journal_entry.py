import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import EntryStatus
from app.models.mixins import UUIDPrimaryKeyMixin, pg_enum


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProposedJournalEntry(Base, UUIDPrimaryKeyMixin):
    """The core work unit. status must never be written to APPROVED/
    REJECTED/POSTED/REVERSED by anything running under the ai_service
    Postgres role — enforced by both the application-level state machine
    (app/services/accounting/entry_state_machine.py) and a database trigger
    (see alembic/versions/0001_initial_schema.py). This is a defense-in-
    depth pair, not a single point of enforcement."""

    __tablename__ = "proposed_journal_entries"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_periods.id"), nullable=False, index=True
    )
    status: Mapped[EntryStatus] = mapped_column(
        pg_enum(EntryStatus, "entry_status"), default=EntryStatus.DRAFT, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.id"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    lines: Mapped[list["JournalEntryLine"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )


class JournalEntryLine(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "journal_entry_lines"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposed_journal_entries.id"), nullable=False, index=True
    )
    gl_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gl_accounts.id"), nullable=False
    )
    debit: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    credit: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    memo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    entry: Mapped["ProposedJournalEntry"] = relationship(back_populates="lines")
