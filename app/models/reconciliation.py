import uuid
from datetime import date, datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    FinancialAccountType,
    ReconciliationItemStatus,
    ReconciliationStatus,
    TransactionMatchMethod,
)
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FinancialAccount(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """A client's bank/credit-card/payroll-clearing account. Linked to the
    GL account it reconciles against — the Reconciliation & Close Agent
    compares this account's imported transactions to that GL account's
    balance, never the other way around."""

    __tablename__ = "financial_accounts"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    gl_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gl_accounts.id"), nullable=False
    )
    account_type: Mapped[FinancialAccountType] = mapped_column(
        pg_enum(FinancialAccountType, "financial_account_type"), nullable=False
    )
    institution: Mapped[str] = mapped_column(String(128), nullable=False)
    mask: Mapped[str] = mapped_column(String(4), nullable=False)  # last 4 digits only — never a full number
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class ImportedTransaction(Base, UUIDPrimaryKeyMixin):
    """One bank/CC feed line item, from a CSV/OFX import. amount is signed:
    negative = money out, positive = money in, matching typical bank-feed
    convention."""

    __tablename__ = "imported_transactions"

    financial_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    transaction_date: Mapped[date] = mapped_column(nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class TransactionMatch(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Deterministic link between an imported transaction and the proposed
    journal entry it corresponds to. match_method records how — never an
    LLM judgment, always a rule."""

    __tablename__ = "transaction_matches"

    imported_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imported_transactions.id"), nullable=False, index=True
    )
    entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposed_journal_entries.id"), nullable=True
    )
    match_method: Mapped[TransactionMatchMethod] = mapped_column(
        pg_enum(TransactionMatchMethod, "transaction_match_method"), nullable=False
    )


class Reconciliation(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One account's reconciliation for one period. gl_balance and
    difference are deterministic aggregations, never model output."""

    __tablename__ = "reconciliations"

    financial_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_periods.id"), nullable=False, index=True
    )
    status: Mapped[ReconciliationStatus] = mapped_column(
        pg_enum(ReconciliationStatus, "reconciliation_status"),
        default=ReconciliationStatus.IN_PROGRESS,
        nullable=False,
    )
    statement_balance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    gl_balance: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    difference: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReconciliationItem(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "reconciliation_items"

    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reconciliations.id"), nullable=False, index=True
    )
    imported_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imported_transactions.id"), nullable=True
    )
    status: Mapped[ReconciliationItemStatus] = mapped_column(
        pg_enum(ReconciliationItemStatus, "reconciliation_item_status"), nullable=False
    )
