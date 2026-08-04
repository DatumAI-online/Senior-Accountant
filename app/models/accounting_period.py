import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import CloseStatus, GLAccountType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class AccountingPeriod(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One month's close cycle for an engagement. close_status may only
    reach APPROVED/DELIVERED via the CPA-service role — see
    entry_state_machine.py for the (currently entry-level) enforcement
    pattern this column will follow once the Reconciliation & Close Agent
    is built."""

    __tablename__ = "accounting_periods"
    __table_args__ = (UniqueConstraint("engagement_id", "period", name="uq_engagement_period"),)

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    close_status: Mapped[CloseStatus] = mapped_column(
        pg_enum(CloseStatus, "close_status"), default=CloseStatus.NOT_STARTED, nullable=False
    )


class GLAccount(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Per-client chart-of-accounts entry. Not in the founders' original
    entity list, but required for double-entry JournalEntryLine references —
    flagged as an addition in DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 8."""

    __tablename__ = "gl_accounts"
    __table_args__ = (UniqueConstraint("client_id", "code", name="uq_client_gl_code"),)

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[GLAccountType] = mapped_column(
        pg_enum(GLAccountType, "gl_account_type"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
