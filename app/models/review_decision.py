import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ReviewDecisionType
from app.models.mixins import UUIDPrimaryKeyMixin, pg_enum


class ReviewDecision(Base, UUIDPrimaryKeyMixin):
    """Immutable record of a human CPA's decision. This table has no
    UPDATE or DELETE grant for ANY application role in the migration —
    not even datumai_cpa_service — and no INSERT grant for datumai_ai_service
    at all. A correction is a new ReviewDecision row (or a new reversing
    JournalEntry), never an edit to this one. See Section 10.1."""

    __tablename__ = "review_decisions"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposed_journal_entries.id"), nullable=False, index=True
    )
    cpa_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decision: Mapped[ReviewDecisionType] = mapped_column(
        pg_enum(ReviewDecisionType, "review_decision_type"), nullable=False
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
