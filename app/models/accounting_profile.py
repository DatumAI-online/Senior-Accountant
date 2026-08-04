import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class ClientAccountingProfile(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Controlled client memory: chart-of-accounts template, materiality
    threshold, and other CPA-governed policy fields. Only a CPA-authenticated
    write path may change policy_approved_* fields — see
    DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 13. AI agents may read this
    table (via the ai_service role) but the migration grants no UPDATE on it
    to that role at all; only datumai_cpa_service can write it."""

    __tablename__ = "client_accounting_profiles"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, unique=True, index=True
    )
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    coa_template: Mapped[str] = mapped_column(String(64), default="service_business_default")
    materiality_threshold: Mapped[float] = mapped_column(Numeric(14, 2), default=500.00)
    payroll_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revenue_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    policy_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Engagement(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "engagements"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    service_tier: Mapped[str] = mapped_column(String(64), default="core_bookkeeping")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
