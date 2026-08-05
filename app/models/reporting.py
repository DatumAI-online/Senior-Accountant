import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import FinancialReportType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class FinancialReport(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """A generated statement. `data` is built entirely from a deterministic
    aggregation query scoped to approved/posted entries only — see
    app/agents/reporting_insights/tools.py. approved_by is set only via the
    CPA-only deliverable-approval endpoint."""

    __tablename__ = "financial_reports"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_periods.id"), nullable=False, index=True
    )
    report_type: Mapped[FinancialReportType] = mapped_column(
        pg_enum(FinancialReportType, "financial_report_type"), nullable=False
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(64), nullable=False)  # agent_type value
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class ExecutiveSummary(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One-page Claude-drafted narrative for a client/period. Every
    variance figure it cites must trace back to a FinancialReport row —
    the Reporting Agent is instructed to quote only numbers it was given,
    never to compute its own (Section 9's source-grounding requirement)."""

    __tablename__ = "executive_summaries"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_periods.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    skill_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class RecommendedAction(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "recommended_actions"

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("executive_summaries.id"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
